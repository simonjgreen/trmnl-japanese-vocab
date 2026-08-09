"""Schema and semantic validation for the canonical corpus and generated API.

Validation is deliberately noisy about *where* a problem is: every issue
carries the file, the entry ID and the field path, because a corpus of several
thousand words is unfixable otherwise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from .furigana import check_segments
from .models import LEVELS, STATUSES, VocabularyEntry, level_key
from .normalise import display_width, has_control_characters, nfc
from .provenance import SourceRegister

DISPLAY_GLOSS_RECOMMENDED = 60
DISPLAY_GLOSS_HARD_MAX = 90
EXAMPLE_JA_RECOMMENDED = 50
EXAMPLE_JA_HARD_MAX = 80
EXAMPLE_EN_RECOMMENDED = 100
EXAMPLE_EN_HARD_MAX = 160

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    severity: str
    message: str
    file: str | None = None
    entry_id: str | None = None
    path: str | None = None

    def format(self) -> str:
        location = " ".join(
            part
            for part in (
                self.file,
                f"[{self.entry_id}]" if self.entry_id else None,
                f".{self.path}" if self.path else None,
            )
            if part
        )
        return f"{self.severity.upper()}: {location}: {self.message}".replace(
            ": :", ":"
        )


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, severity: str, message: str, **location: Any) -> None:
        self.issues.append(Issue(severity, message, **location))

    def error(self, message: str, **location: Any) -> None:
        self.add(ERROR, message, **location)

    def warn(self, message: str, **location: Any) -> None:
        self.add(WARNING, message, **location)

    def extend(self, other: "Report") -> None:
        self.issues.extend(other.issues)
        self.counts.update(other.counts)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "counts": self.counts,
            "errors": [i.format() for i in self.errors],
            "warnings": [i.format() for i in self.warnings],
        }


def load_schema(name: str, schema_dir: Path = Path("schemas")) -> dict[str, Any]:
    return json.loads((schema_dir / name).read_text(encoding="utf-8"))


def _validator(schema: dict[str, Any], schema_dir: Path) -> jsonschema.Validator:
    """Build a validator that can resolve sibling ``$ref`` files locally."""
    store = {}
    for path in schema_dir.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        store[path.name] = doc
        if "$id" in doc:
            store[doc["$id"]] = doc

    from referencing import Registry, Resource

    resources = [
        (name, Resource.from_contents(doc))
        for name, doc in store.items()
        if isinstance(doc, dict)
    ]
    registry = Registry().with_resources(resources)
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema, registry=registry)


# --------------------------------------------------------------------------
# Entry-level checks
# --------------------------------------------------------------------------


def _raw_text_fields(raw: dict[str, Any]) -> list[tuple[str, str]]:
    """Text fields to check, read straight from the file.

    Hygiene has to be checked against the raw document rather than the parsed
    entry: parsing normalises whitespace and Unicode, so by the time an entry
    object exists the very problems this is looking for have been tidied away.
    """
    fields: list[tuple[str, str]] = []
    for key in ("surface", "reading", "display_gloss"):
        value = raw.get(key)
        if isinstance(value, str):
            fields.append((key, value))
    for index, gloss in enumerate(raw.get("glosses") or []):
        if isinstance(gloss, str):
            fields.append((f"glosses.{index}", gloss))
    example = raw.get("example") or {}
    if isinstance(example, dict):
        for key in ("ja", "en"):
            value = example.get(key)
            if isinstance(value, str):
                fields.append((f"example.{key}", value))
    return fields


def _check_text_hygiene(
    report: Report, raw: dict[str, Any], entry_id: str | None, file_label: str
) -> None:
    for path, value in _raw_text_fields(raw):
        if not value:
            report.error("must not be empty", file=file_label, entry_id=entry_id, path=path)
            continue
        if value != nfc(value):
            report.error(
                "text is not NFC-normalised",
                file=file_label,
                entry_id=entry_id,
                path=path,
            )
        if value != value.strip():
            report.error(
                "leading or trailing whitespace",
                file=file_label,
                entry_id=entry_id,
                path=path,
            )
        if has_control_characters(value):
            report.error(
                "contains control characters",
                file=file_label,
                entry_id=entry_id,
                path=path,
            )
        if "<" in value or ">" in value:
            report.error(
                "HTML markup is not permitted in vocabulary data",
                file=file_label,
                entry_id=entry_id,
                path=path,
            )


def validate_entry(
    entry: VocabularyEntry,
    file_label: str,
    expected_level: str,
    register: SourceRegister | None = None,
    raw: dict[str, Any] | None = None,
) -> Report:
    """Semantic checks for one canonical entry.

    *raw* is the entry exactly as it appears in the file; text hygiene is
    checked against it so that normalisation performed during parsing cannot
    hide a problem.
    """
    report = Report()

    _check_text_hygiene(report, raw if raw is not None else entry.to_json(),
                        entry.id, file_label)

    if entry.status not in STATUSES:
        report.error(
            f"invalid status {entry.status!r}",
            file=file_label,
            entry_id=entry.id,
            path="status",
        )
    if entry.jlpt.level not in LEVELS:
        report.error(
            f"invalid JLPT level {entry.jlpt.level!r}",
            file=file_label,
            entry_id=entry.id,
            path="jlpt.level",
        )
    elif entry.jlpt.level != expected_level:
        report.error(
            f"entry level {entry.jlpt.level} does not match its file ({expected_level})",
            file=file_label,
            entry_id=entry.id,
            path="jlpt.level",
        )

    if not entry.source_refs:
        report.error(
            "entry has no provenance reference",
            file=file_label,
            entry_id=entry.id,
            path="source_refs",
        )
    if register is not None:
        for index, ref in enumerate(entry.source_refs):
            if ref.source_id not in register:
                report.error(
                    f"unknown source ID {ref.source_id!r}; declare it in data/sources.yml",
                    file=file_label,
                    entry_id=entry.id,
                    path=f"source_refs.{index}.source_id",
                )
        if entry.jlpt.source_id not in register:
            report.error(
                f"unknown level source ID {entry.jlpt.source_id!r}",
                file=file_label,
                entry_id=entry.id,
                path="jlpt.source_id",
            )

    gloss_length = len(entry.display_gloss)
    if gloss_length > DISPLAY_GLOSS_HARD_MAX:
        report.error(
            f"display_gloss is {gloss_length} characters, hard maximum is {DISPLAY_GLOSS_HARD_MAX}",
            file=file_label,
            entry_id=entry.id,
            path="display_gloss",
        )
    elif gloss_length > DISPLAY_GLOSS_RECOMMENDED:
        report.warn(
            f"display_gloss is {gloss_length} characters, recommended maximum is "
            f"{DISPLAY_GLOSS_RECOMMENDED}",
            file=file_label,
            entry_id=entry.id,
            path="display_gloss",
        )

    # Furigana is the whole point of the plugin, so an active entry with a
    # broken segmentation is fatal rather than a warning.
    problems = check_segments(entry.surface, entry.reading, entry.ruby_segments)
    for problem in problems:
        severity = report.error if entry.is_active else report.warn
        severity(problem, file=file_label, entry_id=entry.id, path="ruby_segments")

    if entry.example is not None:
        _validate_example(report, entry, file_label)

    return report


def _validate_example(
    report: Report, entry: VocabularyEntry, file_label: str
) -> None:
    example = entry.example
    assert example is not None

    if not example.ja:
        report.error(
            "example is present but has no Japanese sentence",
            file=file_label,
            entry_id=entry.id,
            path="example.ja",
        )
        return

    ja_length = len(example.ja)
    if ja_length > EXAMPLE_JA_HARD_MAX:
        report.error(
            f"example.ja is {ja_length} characters, hard maximum is {EXAMPLE_JA_HARD_MAX}",
            file=file_label,
            entry_id=entry.id,
            path="example.ja",
        )
    elif display_width(example.ja) > EXAMPLE_JA_RECOMMENDED:
        report.warn(
            "example.ja exceeds the recommended display width",
            file=file_label,
            entry_id=entry.id,
            path="example.ja",
        )

    if example.en:
        en_length = len(example.en)
        if en_length > EXAMPLE_EN_HARD_MAX:
            report.error(
                f"example.en is {en_length} characters, hard maximum is "
                f"{EXAMPLE_EN_HARD_MAX}",
                file=file_label,
                entry_id=entry.id,
                path="example.en",
            )
        elif en_length > EXAMPLE_EN_RECOMMENDED:
            report.warn(
                f"example.en is {en_length} characters, recommended maximum is "
                f"{EXAMPLE_EN_RECOMMENDED}",
                file=file_label,
                entry_id=entry.id,
                path="example.en",
            )

    if example.focus_form and example.focus_form not in example.ja:
        # Conjugation means the dictionary form usually will not appear, so
        # this is only a signal that the sentence may have been mismatched.
        report.warn(
            f"focus_form {example.focus_form!r} does not occur in the example sentence",
            file=file_label,
            entry_id=entry.id,
            path="example.focus_form",
        )


# --------------------------------------------------------------------------
# Corpus-level checks
# --------------------------------------------------------------------------


def validate_corpus(
    vocabulary_dir: Path = Path("data/vocabulary"),
    sources_path: Path = Path("data/sources.yml"),
    schema_dir: Path = Path("schemas"),
    minimum_per_level: int = 1,
) -> tuple[Report, dict[str, list[VocabularyEntry]]]:
    """Validate every level file and return the loaded corpus."""
    report = Report()
    corpus: dict[str, list[VocabularyEntry]] = {}

    if not sources_path.exists():
        report.error(f"missing provenance register {sources_path}")
        register = SourceRegister({})
    else:
        register = SourceRegister.load(sources_path)
        sources_schema = load_schema("sources.schema.json", schema_dir)
        import yaml

        raw_sources = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
        for error in _validator(sources_schema, schema_dir).iter_errors(raw_sources):
            report.error(
                error.message,
                file=str(sources_path),
                path=".".join(str(p) for p in error.absolute_path),
            )

    entry_schema = load_schema("vocabulary-entry.schema.json", schema_dir)
    validator = _validator(entry_schema, schema_dir)

    seen_ids: dict[str, str] = {}

    for level in LEVELS:
        key = level_key(level)
        path = vocabulary_dir / f"{key}.json"
        file_label = str(path)

        if not path.exists():
            report.error(f"missing level file {path}")
            corpus[key] = []
            continue

        try:
            raw_entries = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            report.error(f"invalid JSON: {exc}", file=file_label)
            corpus[key] = []
            continue

        if not isinstance(raw_entries, list):
            report.error("level file must contain a JSON array", file=file_label)
            corpus[key] = []
            continue

        entries: list[VocabularyEntry] = []
        for index, raw in enumerate(raw_entries):
            entry_id = raw.get("id", f"<index {index}>") if isinstance(raw, dict) else None
            schema_failed = False
            for error in validator.iter_errors(raw):
                schema_failed = True
                report.error(
                    error.message,
                    file=file_label,
                    entry_id=entry_id,
                    path=".".join(str(p) for p in error.absolute_path),
                )
            if schema_failed:
                continue

            entry = VocabularyEntry.from_json(raw)
            entries.append(entry)

            if entry.id in seen_ids:
                report.error(
                    f"duplicate entry ID, already defined in {seen_ids[entry.id]}",
                    file=file_label,
                    entry_id=entry.id,
                    path="id",
                )
            else:
                seen_ids[entry.id] = file_label

            report.extend(validate_entry(entry, file_label, level, register, raw=raw))

        _check_file_invariants(report, entries, file_label, key, minimum_per_level)
        corpus[key] = entries

    report.counts = {key: sum(1 for e in v if e.is_active) for key, v in corpus.items()}
    report.counts["total_active"] = sum(report.counts.values())
    return report, corpus


def _check_file_invariants(
    report: Report,
    entries: list[VocabularyEntry],
    file_label: str,
    key: str,
    minimum_per_level: int,
) -> None:
    ids = [e.id for e in entries]
    if ids != sorted(ids):
        report.error(
            "entries are not stable-sorted by id; run `kotoba import` to rewrite",
            file=file_label,
        )

    active = [e for e in entries if e.is_active]
    if len(active) < minimum_per_level:
        report.error(
            f"level {key.upper()} has {len(active)} active entries, "
            f"minimum is {minimum_per_level}",
            file=file_label,
        )

    seen: dict[tuple[str, str, str], str] = {}
    for entry in active:
        signature = (entry.surface, entry.reading, entry.display_gloss)
        if signature in seen:
            report.error(
                f"duplicate surface/reading/gloss, already used by {seen[signature]}",
                file=file_label,
                entry_id=entry.id,
            )
        else:
            seen[signature] = entry.id


# --------------------------------------------------------------------------
# Generated site checks
# --------------------------------------------------------------------------


def validate_site(
    site_dir: Path = Path("site"),
    schema_dir: Path = Path("schemas"),
    hard_size_limit: int = 8192,
) -> Report:
    """Validate the generated static API against its schema and constraints."""
    report = Report()
    api = site_dir / "api" / "v1"
    manifest_path = api / "manifest.json"

    if not (site_dir / "index.html").exists():
        report.error("generated site has no index.html", file=str(site_dir))
    if not manifest_path.exists():
        report.error("missing manifest.json", file=str(manifest_path))
        return report

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    slot_count = manifest.get("slots", {}).get("count")
    payload_schema = load_schema("card-payload.schema.json", schema_dir)
    validator = _validator(payload_schema, schema_dir)

    checked = 0
    for key in ("n5", "n4", "n3", "n2", "n1"):
        level_dir = api / "card" / key
        if not level_dir.is_dir():
            report.error(f"missing generated level directory {level_dir}")
            continue

        slots = sorted(
            (p for p in level_dir.glob("*.json") if p.stem != "sample"),
            key=lambda p: int(p.stem),
        )
        expected = manifest.get("generated_files", {}).get(key)
        if expected is not None and expected != len(slots):
            report.error(
                f"manifest claims {expected} slots for {key} but {len(slots)} exist",
                file=str(level_dir),
            )

        # Every slot the polling URL can ask for must exist, or a device
        # lands on a 404 and shows nothing at all.
        if slot_count is not None:
            present = {int(p.stem) for p in slots}
            missing = [i for i in range(slot_count) if i not in present]
            if missing:
                report.error(
                    f"{len(missing)} slot file(s) missing, first {missing[:3]}",
                    file=str(level_dir),
                )

        for path in slots:
            checked += 1
            size = path.stat().st_size
            if size > hard_size_limit:
                report.error(
                    f"payload is {size} bytes, hard limit is {hard_size_limit}",
                    file=str(path),
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            for error in validator.iter_errors(payload):
                report.error(
                    error.message,
                    file=str(path),
                    path=".".join(str(p) for p in error.absolute_path),
                )
            if payload.get("slot", {}).get("index") != int(path.stem):
                report.error(
                    f"slot index {payload.get('slot', {}).get('index')!r} does not "
                    "match filename",
                    file=str(path),
                )
            if payload.get("level") != key:
                report.error(
                    f"payload level {payload.get('level')!r} does not match its directory",
                    file=str(path),
                )

        if not (level_dir / "sample.json").exists():
            report.error(f"missing {level_dir / 'sample.json'}")

    report.counts["payloads_checked"] = checked
    return report


def summarise(report: Report, limit: int = 25) -> str:
    """Render a concise human-readable summary."""
    lines: list[str] = []
    for issue in report.errors[:limit]:
        lines.append(issue.format())
    if len(report.errors) > limit:
        lines.append(f"... and {len(report.errors) - limit} further errors")
    for issue in report.warnings[:limit]:
        lines.append(issue.format())
    if len(report.warnings) > limit:
        lines.append(f"... and {len(report.warnings) - limit} further warnings")
    lines.append(
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    return "\n".join(lines)

"""The import pipeline: source records in, canonical corpus out.

Stages, in order (see ``docs/data-sourcing.md``):

1. read source records via an adapter;
2. normalise Unicode, whitespace, level names and kana;
3. map into the canonical shape;
4. deduplicate exact lexical duplicates;
5. align furigana where the source supplied no segmentation;
6. apply overrides;
7. validate;
8. write canonical files, stable-sorted by ID;
9. write a review report for anything unresolved.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .furigana import NEEDS_REVIEW, resolve
from .models import (
    LEVELS,
    Example,
    JlptAssignment,
    RubySegment,
    SourceRef,
    VocabularyEntry,
    derive_entry_id,
    level_key,
    lexical_id,
    normalise_level,
    sort_entries,
)
from .normalise import clean_text
from .sources.base import RawRecord

#: A display gloss longer than this is trimmed to its first sense rather than
#: being allowed to dominate the screen.
DISPLAY_GLOSS_TARGET = 60
#: Two lines are allowed for unusually long material; beyond this a gloss is
#: truncated. Mirrors the validation limit.
DISPLAY_GLOSS_HARD_MAX = 90


@dataclass
class ImportStats:
    read: int = 0
    skipped_bad_level: int = 0
    skipped_duplicate: int = 0
    needs_review: int = 0
    overrides_applied: int = 0
    written: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "read": self.read,
            "skipped_bad_level": self.skipped_bad_level,
            "skipped_duplicate": self.skipped_duplicate,
            "needs_review": self.needs_review,
            "overrides_applied": self.overrides_applied,
            "written": dict(self.written),
        }


@dataclass
class ReviewItem:
    entry_id: str
    surface: str
    reading: str
    level: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.entry_id,
            "surface": self.surface,
            "reading": self.reading,
            "level": self.level,
            "reason": self.reason,
        }


def load_overrides(path: Path) -> dict[str, list[RubySegment]]:
    """Load ``data/overrides/furigana.yml`` keyed by stable entry ID."""
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    overrides: dict[str, list[RubySegment]] = {}
    for entry_id, segments in (raw.get("overrides") or {}).items():
        overrides[entry_id] = [
            RubySegment(base=s["base"], reading=s.get("reading") or None)
            for s in segments
        ]
    return overrides


def choose_display_gloss(glosses: Iterable[str]) -> str:
    """Pick a concise, screen-safe gloss from the source's sense list.

    The first gloss wins. JMdict orders glosses within a sense by prominence,
    so the leading one is the meaning a learner should take away.

    An earlier version picked the *shortest* of the first few glosses, on the
    theory that brevity suits a small screen. It does not: brevity is not
    accuracy. That rule turned 混雑 into "crush" rather than "congestion",
    ぐっすり into "fast" rather than "soundly (asleep)", and — worst of all —
    いらっしゃい into "go" when it means "come". It rewrote the meaning of
    roughly two entries in five. A slightly longer, correct gloss beats a
    short, misleading one every time.

    Later glosses are consulted only when the first genuinely will not fit.
    """
    candidates = [t for t in (_tidy_gloss(g) for g in glosses) if t]
    if not candidates:
        return ""

    primary = candidates[0]
    if len(primary) <= DISPLAY_GLOSS_TARGET:
        return primary

    # Too long for one comfortable line. Prefer, in order: a shorter sibling
    # gloss, the first clause of a comma-separated list, then two lines.
    for alternative in candidates[1:4]:
        if len(alternative) <= DISPLAY_GLOSS_TARGET:
            return alternative

    if ", " in primary:
        # Some JMdict glosses are a whole list in one string, e.g.
        # "wound, injury, hurt, cut, gash, bruise, scratch, scar, weak point".
        # The first clause is the meaning; the rest is a thesaurus.
        first_clause = primary.split(", ", 1)[0].strip()
        if 3 <= len(first_clause) <= DISPLAY_GLOSS_HARD_MAX:
            return first_clause

    # Two lines are permitted for unusually long material, so use the full
    # gloss up to the hard limit rather than truncating mid-word.
    if len(primary) <= DISPLAY_GLOSS_HARD_MAX:
        return primary

    return primary[: DISPLAY_GLOSS_HARD_MAX - 1].rstrip(" ,;") + "…"


#: Matches a parenthetical group at the very end of a gloss.
_TRAILING_BRACKET = re.compile(r"\s*\([^()]*\)\s*$")


def _tidy_gloss(gloss: str) -> str:
    """Normalise one gloss for display.

    Trailing qualifiers are dropped — "to eat (colloquial)" becomes "to eat",
    and "(East Asian) rainy season (in Japan, usu. from early June to
    mid-July)" becomes "(East Asian) rainy season". A *leading* bracket is
    kept, because "(flower) vase" and "(be) still" lose their sense without
    it.
    """
    text = clean_text(gloss)
    if not text:
        return ""

    while True:
        trimmed = _TRAILING_BRACKET.sub("", text).strip()
        # Never trim away the whole gloss, and never leave a useless stub.
        if trimmed == text or len(trimmed) < 3:
            break
        text = trimmed

    return text.rstrip(" ,;")


def build_entry(
    record: RawRecord,
    overrides: dict[str, list[RubySegment]],
    stats: ImportStats,
    review: list[ReviewItem],
) -> VocabularyEntry | None:
    """Turn one raw record into a canonical entry, or ``None`` if unusable."""
    try:
        level = normalise_level(record.level)
    except ValueError:
        stats.skipped_bad_level += 1
        return None

    surface = clean_text(record.surface).replace(" ", "")
    reading = clean_text(record.reading).replace(" ", "")
    if not surface or not reading:
        return None

    if record.source_entry_id:
        entry_id = lexical_id(
            record.source_id, record.source_entry_id, surface, reading
        )
    else:
        entry_id = derive_entry_id(record.source_id, surface, reading, level)

    display_gloss = choose_display_gloss(record.glosses)
    if not display_gloss:
        return None

    alignment = resolve(
        entry_id,
        surface,
        reading,
        existing=record.ruby_segments,
        overrides=overrides,
    )
    if entry_id in overrides:
        stats.overrides_applied += 1

    status = "active"
    if alignment.status == NEEDS_REVIEW:
        stats.needs_review += 1
        review.append(
            ReviewItem(
                entry_id=entry_id,
                surface=surface,
                reading=reading,
                level=level,
                reason=alignment.reason or "unresolved furigana",
            )
        )
        # An entry we cannot render correctly is disabled rather than dropped,
        # so that a human can see it, fix it with an override, and re-enable it
        # without the ID changing.
        status = "disabled"

    segments = alignment.segments or [RubySegment(base=surface, reading=None)]

    example = None
    if record.example_ja:
        example = Example(
            ja=clean_text(record.example_ja),
            en=clean_text(record.example_en) if record.example_en else None,
            focus_form=clean_text(record.extra.get("focus_form") or "") or None,
            source_ref=record.example_source_ref,
        )

    source_refs = [
        SourceRef(source_id=record.source_id, source_entry_id=record.source_entry_id)
    ]
    for extra_id, present in (
        ("jmdict", record.extra.get("has_jmdict")),
        ("jmdict-furigana", record.extra.get("has_furigana")),
    ):
        if present:
            source_refs.append(
                SourceRef(source_id=extra_id, source_entry_id=record.source_entry_id)
            )

    return VocabularyEntry(
        id=entry_id,
        surface=surface,
        reading=reading,
        ruby_segments=segments,
        glosses=[clean_text(g) for g in record.glosses if clean_text(g)],
        display_gloss=display_gloss,
        jlpt=JlptAssignment(
            level=level,
            source_id=record.source_id,
            confidence="community-estimated",
        ),
        source_refs=source_refs,
        status=status,
        part_of_speech=list(record.part_of_speech),
        example=example,
        notes=record.notes,
    )


def run_import(
    records: Iterable[RawRecord],
    vocabulary_dir: Path = Path("data/vocabulary"),
    overrides_path: Path = Path("data/overrides/furigana.yml"),
    review_dir: Path = Path("data/review"),
) -> ImportStats:
    """Execute the full pipeline and write canonical files."""
    overrides = load_overrides(overrides_path)
    stats = ImportStats()
    review: list[ReviewItem] = []

    by_level: dict[str, dict[str, VocabularyEntry]] = {
        level_key(level): {} for level in LEVELS
    }
    # Lexical identity, used to drop the same word appearing twice.
    seen_lexical: dict[tuple[str, str], str] = {}

    for record in records:
        stats.read += 1
        entry = build_entry(record, overrides, stats, review)
        if entry is None:
            continue

        signature = (entry.surface, entry.reading)
        if signature in seen_lexical:
            stats.skipped_duplicate += 1
            continue
        seen_lexical[signature] = entry.id

        bucket = by_level[level_key(entry.jlpt.level)]
        if entry.id in bucket:
            stats.skipped_duplicate += 1
            continue
        bucket[entry.id] = entry

    vocabulary_dir.mkdir(parents=True, exist_ok=True)
    for key, bucket in by_level.items():
        entries = sort_entries(bucket.values())
        path = vocabulary_dir / f"{key}.json"
        path.write_text(
            json.dumps(
                [e.to_json() for e in entries],
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            + "\n",
            encoding="utf-8",
        )
        stats.written[key] = sum(1 for e in entries if e.is_active)

    _write_review(review, review_dir)
    return stats


def _write_review(review: list[ReviewItem], review_dir: Path) -> None:
    """Write the unresolved-furigana report in both machine and human form."""
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "furigana-review.json").write_text(
        json.dumps([r.as_dict() for r in review], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Furigana review queue",
        "",
        "Entries whose ruby segmentation could not be resolved automatically.",
        "They are written to the corpus with `status: disabled` so they never",
        "reach a device. Add a segmentation to `data/overrides/furigana.yml`",
        "keyed by the entry ID, re-run `make import`, and the entry becomes",
        "active again without its ID changing.",
        "",
    ]
    if not review:
        lines.append("Nothing to review.")
    else:
        lines.append("| ID | Surface | Reading | Level | Reason |")
        lines.append("| -- | ------- | ------- | ----- | ------ |")
        for item in sorted(review, key=lambda r: r.entry_id):
            reason = item.reason.replace("|", "\\|")
            lines.append(
                f"| `{item.entry_id}` | {item.surface} | {item.reading} "
                f"| {item.level} | {reason} |"
            )
    (review_dir / "furigana-review.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

"""Canonical vocabulary data model.

These dataclasses are the in-memory form of the JSON documents under
``data/vocabulary``. They carry no behaviour beyond serialisation so that the
JSON schemas in ``schemas/`` remain the single authority on shape.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable

from .normalise import clean_text, nfc

LEVELS: tuple[str, ...] = ("N5", "N4", "N3", "N2", "N1")
LEVEL_KEYS: tuple[str, ...] = ("n5", "n4", "n3", "n2", "n1")
STATUSES: tuple[str, ...] = ("active", "disabled")


def level_key(level: str) -> str:
    """``"N3"`` -> ``"n3"``."""
    return level.strip().lower()


def level_display(key: str) -> str:
    """``"n3"`` -> ``"N3"``."""
    return key.strip().upper()


def normalise_level(raw: Any) -> str:
    """Coerce a source's level spelling into the canonical ``N5``..``N1``.

    Accepts ``3``, ``"3"``, ``"n3"``, ``"N3"``, ``"JLPT N3"`` and
    ``"jlpt3"``. Raises ``ValueError`` for anything else so that a source
    with an unexpected vocabulary of level names fails loudly at import.
    """
    if raw is None:
        raise ValueError("missing JLPT level")
    text = str(raw).strip().upper().replace("JLPT", "").replace("-", "").strip()
    text = text.replace(" ", "")
    if text.startswith("N"):
        text = text[1:]
    if text in {"1", "2", "3", "4", "5"}:
        return f"N{text}"
    raise ValueError(f"unrecognised JLPT level: {raw!r}")


@dataclass(frozen=True)
class RubySegment:
    """One display run of the target word.

    ``reading`` is ``None`` for material that is already readable (kana and
    punctuation) and a kana string for a run that should be wrapped in
    ``<ruby>``.
    """

    base: str
    reading: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"base": self.base, "reading": self.reading}

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "RubySegment":
        reading = raw.get("reading")
        return RubySegment(
            base=nfc(raw["base"]),
            reading=nfc(reading) if reading else None,
        )


@dataclass(frozen=True)
class Example:
    ja: str
    en: str | None = None
    focus_form: str | None = None
    source_ref: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ja": self.ja}
        if self.en:
            out["en"] = self.en
        if self.focus_form:
            out["focus_form"] = self.focus_form
        if self.source_ref:
            out["source_ref"] = self.source_ref
        return out

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "Example":
        return Example(
            ja=clean_text(raw.get("ja", "")),
            en=clean_text(raw["en"]) if raw.get("en") else None,
            focus_form=clean_text(raw["focus_form"]) if raw.get("focus_form") else None,
            source_ref=raw.get("source_ref"),
        )


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    source_entry_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"source_id": self.source_id}
        if self.source_entry_id is not None:
            out["source_entry_id"] = str(self.source_entry_id)
        return out

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "SourceRef":
        entry_id = raw.get("source_entry_id")
        return SourceRef(
            source_id=raw["source_id"],
            source_entry_id=str(entry_id) if entry_id is not None else None,
        )


@dataclass(frozen=True)
class JlptAssignment:
    level: str
    source_id: str
    confidence: str = "source-assigned"

    def to_json(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "source_id": self.source_id,
            "confidence": self.confidence,
        }

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "JlptAssignment":
        return JlptAssignment(
            level=raw["level"],
            source_id=raw["source_id"],
            confidence=raw.get("confidence", "source-assigned"),
        )


@dataclass
class VocabularyEntry:
    id: str
    surface: str
    reading: str
    ruby_segments: list[RubySegment]
    glosses: list[str]
    display_gloss: str
    jlpt: JlptAssignment
    source_refs: list[SourceRef]
    status: str = "active"
    part_of_speech: list[str] = field(default_factory=list)
    example: Example | None = None
    notes: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def to_json(self) -> dict[str, Any]:
        """Serialise with a stable key order for reviewable diffs."""
        out: dict[str, Any] = {
            "id": self.id,
            "surface": self.surface,
            "reading": self.reading,
            "ruby_segments": [s.to_json() for s in self.ruby_segments],
            "glosses": list(self.glosses),
            "display_gloss": self.display_gloss,
        }
        if self.part_of_speech:
            out["part_of_speech"] = list(self.part_of_speech)
        out["jlpt"] = self.jlpt.to_json()
        if self.example is not None:
            out["example"] = self.example.to_json()
        out["source_refs"] = [r.to_json() for r in self.source_refs]
        out["status"] = self.status
        out["notes"] = self.notes
        return out

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "VocabularyEntry":
        return VocabularyEntry(
            id=raw["id"],
            surface=nfc(raw["surface"]),
            reading=nfc(raw["reading"]),
            ruby_segments=[RubySegment.from_json(s) for s in raw.get("ruby_segments", [])],
            glosses=[clean_text(g) for g in raw.get("glosses", [])],
            display_gloss=clean_text(raw.get("display_gloss", "")),
            jlpt=JlptAssignment.from_json(raw["jlpt"]),
            source_refs=[SourceRef.from_json(r) for r in raw.get("source_refs", [])],
            status=raw.get("status", "active"),
            part_of_speech=list(raw.get("part_of_speech", [])),
            example=Example.from_json(raw["example"]) if raw.get("example") else None,
            notes=raw.get("notes"),
        )


def derive_entry_id(
    source_id: str, surface: str, reading: str, source_level: str
) -> str:
    """Derive a stable ID from immutable lexical identity fields.

    Used only when a source supplies no stable identifier of its own. The
    digest deliberately excludes glosses, examples and notes so that editorial
    improvements never renumber the corpus (and therefore never reshuffle the
    daily rotation).
    """
    payload = "\0".join(
        [source_id, nfc(surface), nfc(reading), normalise_level(source_level)]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{digest}"


def namespaced_id(source_id: str, source_entry_id: str) -> str:
    """Namespace a source-supplied identifier, e.g. ``jmdict:1234567``."""
    return f"{source_id}:{source_entry_id}"


def lexical_id(
    source_id: str, source_entry_id: str, surface: str, reading: str
) -> str:
    """Namespace a source identifier and pin it to one spelling.

    A source key is not necessarily one-to-one with a learnable word. JMdict,
    for instance, files 会う and 遭う under a single entry, and the JLPT lists
    place them at different levels — they are two words to a learner and must
    be two records here.

    Appending a short digest of the lexical identity makes the identifier
    unique without making it volatile: it is computed from surface and reading
    alone, so glosses, examples and level lists can all change without
    renumbering the corpus and reshuffling the daily rotation.
    """
    payload = "\0".join([nfc(surface), nfc(reading)])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:6]
    return f"{source_id}:{source_entry_id}-{digest}"


def sort_entries(entries: Iterable[VocabularyEntry]) -> list[VocabularyEntry]:
    """Stable-sort by ID using Unicode code-point ordering."""
    return sorted(entries, key=lambda e: e.id)

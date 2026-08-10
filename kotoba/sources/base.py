"""Source adapter protocol and the intermediate record every adapter yields.

Adapters know about file formats and column names. They do not know about
furigana alignment, validation or the canonical on-disk layout — those stages
run once, over the intermediate records, regardless of where the data came
from. That separation is what lets a new vocabulary source be added without
touching the rest of the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..models import RubySegment


@dataclass
class RawRecord:
    """One vocabulary item as read from a source, before canonicalisation."""

    source_id: str
    surface: str
    reading: str
    level: str
    glosses: list[str] = field(default_factory=list)
    source_entry_id: str | None = None
    part_of_speech: list[str] = field(default_factory=list)
    example_ja: str | None = None
    example_en: str | None = None
    example_source_ref: str | None = None
    #: Segmentation supplied by the source, if it has one. When present it is
    #: still validated before use; the aligner is the fallback, not the
    #: override.
    ruby_segments: list[RubySegment] | None = None
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """Anything that can yield :class:`RawRecord` objects."""

    #: Stable source identifier, matching an entry in ``data/sources.yml``.
    source_id: str

    def read(self) -> Iterator[RawRecord]:
        """Yield one record per vocabulary item in the source."""
        ...

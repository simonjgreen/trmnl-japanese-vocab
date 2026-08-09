"""Generic delimited-text adapter driven by a field mapping.

Column names live in ``config/sources.yml``, never in this file, so a new CSV
or TSV source needs configuration rather than code.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterator

from ..normalise import clean_text
from .base import RawRecord

#: Mapping keys understood by this adapter. Anything else in ``mapping`` is a
#: configuration error and is reported rather than silently ignored.
KNOWN_FIELDS = {
    "source_entry_id",
    "surface",
    "reading",
    "level",
    "gloss",
    "part_of_speech",
    "example_ja",
    "example_en",
    "notes",
}

#: Characters that separate several glosses inside a single cell.
GLOSS_SEPARATORS = (";", "/", "|")


def split_multi(value: str) -> list[str]:
    """Split a multi-valued cell on the first separator that appears."""
    value = clean_text(value)
    if not value:
        return []
    for sep in GLOSS_SEPARATORS:
        if sep in value:
            return [part for part in (clean_text(p) for p in value.split(sep)) if part]
    return [value]


class CsvSource:
    """Reads a delimited file using a declarative column mapping."""

    def __init__(
        self,
        source_id: str,
        path: Path,
        mapping: dict[str, str],
        encoding: str = "utf-8-sig",
        delimiter: str = ",",
        level: str | None = None,
    ) -> None:
        unknown = set(mapping) - KNOWN_FIELDS
        if unknown:
            raise ValueError(
                f"source {source_id!r}: unknown mapping fields {sorted(unknown)}; "
                f"supported fields are {sorted(KNOWN_FIELDS)}"
            )
        self.source_id = source_id
        self.path = Path(path)
        self.mapping = mapping
        self.encoding = encoding
        self.delimiter = delimiter
        #: Used when the file itself carries no level column, e.g. one file
        #: per JLPT level.
        self.fixed_level = level

    def _cell(self, row: dict[str, Any], field: str) -> str:
        column = self.mapping.get(field)
        if column is None:
            return ""
        return clean_text(row.get(column, "") or "")

    def read(self) -> Iterator[RawRecord]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"source {self.source_id!r}: missing input file {self.path}"
            )
        with self.path.open(encoding=self.encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            for row in reader:
                surface = self._cell(row, "surface")
                reading = self._cell(row, "reading")
                # Kana-only vocabulary often leaves the kanji column empty.
                if not surface:
                    surface = reading
                if not surface or not reading:
                    continue
                level = self._cell(row, "level") or self.fixed_level or ""
                yield RawRecord(
                    source_id=self.source_id,
                    surface=surface,
                    reading=reading,
                    level=level,
                    glosses=split_multi(self._cell(row, "gloss")),
                    source_entry_id=self._cell(row, "source_entry_id") or None,
                    part_of_speech=split_multi(self._cell(row, "part_of_speech")),
                    example_ja=self._cell(row, "example_ja") or None,
                    example_en=self._cell(row, "example_en") or None,
                    notes=self._cell(row, "notes") or None,
                )

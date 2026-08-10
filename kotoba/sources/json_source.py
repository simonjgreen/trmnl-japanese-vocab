"""Generic JSON adapter driven by a field mapping.

Field paths use dotted notation with numeric indices, e.g.
``sense.0.gloss.0.text``, so a nested source can be mapped without code.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..normalise import clean_text
from .base import RawRecord
from .csv_source import KNOWN_FIELDS


def resolve_path(document: Any, path: str) -> Any:
    """Resolve a dotted path against nested dicts and lists.

    Returns ``None`` when any step is missing rather than raising, because a
    source that omits an optional field for some entries is normal.
    """
    current = document
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError:
                return None
            if not -len(current) <= index < len(current):
                return None
            current = current[index]
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class JsonSource:
    """Reads a JSON array (or a nested array at ``root_path``) of records."""

    def __init__(
        self,
        source_id: str,
        path: Path,
        mapping: dict[str, str],
        root_path: str | None = None,
        encoding: str = "utf-8",
        level: str | None = None,
    ) -> None:
        unknown = set(mapping) - KNOWN_FIELDS
        if unknown:
            raise ValueError(
                f"source {source_id!r}: unknown mapping fields {sorted(unknown)}"
            )
        self.source_id = source_id
        self.path = Path(path)
        self.mapping = mapping
        self.root_path = root_path
        self.encoding = encoding
        self.fixed_level = level

    def _value(self, record: Any, field: str) -> str:
        path = self.mapping.get(field)
        if path is None:
            return ""
        return clean_text(resolve_path(record, path) or "")

    def _values(self, record: Any, field: str) -> list[str]:
        """Read a field that may resolve to either a scalar or a list."""
        path = self.mapping.get(field)
        if path is None:
            return []
        raw = resolve_path(record, path)
        if raw is None:
            return []
        if isinstance(raw, list):
            return [clean_text(v) for v in raw if clean_text(v)]
        return [clean_text(raw)] if clean_text(raw) else []

    def read(self) -> Iterator[RawRecord]:
        if not self.path.exists():
            raise FileNotFoundError(
                f"source {self.source_id!r}: missing input file {self.path}"
            )
        document = json.loads(self.path.read_text(encoding=self.encoding))
        records = resolve_path(document, self.root_path) if self.root_path else document
        if not isinstance(records, list):
            # Deliberately ValueError and not the TypeError ruff would prefer:
            # this is malformed input data rather than a programming error, and
            # kotoba.cli.main only turns ValueError and FileNotFoundError into a
            # tidy message. A TypeError here would reach the user as a traceback.
            raise ValueError(  # noqa: TRY004
                f"source {self.source_id!r}: expected a JSON array"
                + (f" at {self.root_path!r}" if self.root_path else "")
            )

        for record in records:
            surface = self._value(record, "surface")
            reading = self._value(record, "reading")
            if not surface:
                surface = reading
            if not surface or not reading:
                continue
            yield RawRecord(
                source_id=self.source_id,
                surface=surface,
                reading=reading,
                level=self._value(record, "level") or self.fixed_level or "",
                glosses=self._values(record, "gloss"),
                source_entry_id=self._value(record, "source_entry_id") or None,
                part_of_speech=self._values(record, "part_of_speech"),
                example_ja=self._value(record, "example_ja") or None,
                example_en=self._value(record, "example_en") or None,
                notes=self._value(record, "notes") or None,
            )

"""Source provenance register and NOTICE generation.

Every canonical record must point at a declared source, and every declared
source must carry a licence and attribution. The generated ``NOTICE.md`` is
derived from this register so the two can never drift apart.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

NOTICE_HEADER = """# NOTICE

This file is generated from `data/sources.yml` by `kotoba validate --write-notice`.
Do not edit it by hand.

The **code** in this repository is licensed under the MIT Licence (see
`LICENSE`). The **vocabulary data** is not: it is derived from the third-party
sources listed below and remains subject to their licences. A permissive code
licence does not relicense the data.

JLPT level assignments in this repository are community-estimated. The Japan
Foundation and JEES no longer publish an official vocabulary specification, so
no list here is, or claims to be, an official JLPT vocabulary list.
"""

#: Spelled out in NOTICE.md because a reader of the licensing file should not
#: have to know the register's vocabulary to understand what a digest promises.
UPSTREAM_LABELS = {
    "pinned": "pinned release artefact; the recorded digests must match exactly",
    "head-tracked": (
        "tracks a branch head; the recorded digests describe the revision "
        "actually imported, and upstream may have moved since"
    ),
}


@dataclass(frozen=True)
class SourceFile:
    """One file a source contributes to ``data/raw``, and its SHA-256.

    The digest is held on its own, with nothing else in the field. An earlier
    revision recorded a truncated digest with an explanatory sentence appended,
    which read plausibly in ``NOTICE.md`` and was worthless for verification.
    """

    path: str
    sha256: str


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    homepage: str
    retrieved: str
    licence: str
    licence_url: str
    attribution: str
    fields_used: list[str] = field(default_factory=list)
    version: str | None = None
    upstream: str | None = None
    files: list[SourceFile] = field(default_factory=list)
    redistribution_notes: str | None = None

    @staticmethod
    def from_json(raw: dict[str, Any]) -> "Source":
        return Source(
            id=raw["id"],
            name=raw["name"],
            homepage=raw["homepage"],
            retrieved=str(raw["retrieved"]),
            licence=raw["licence"],
            licence_url=raw["licence_url"],
            attribution=raw["attribution"],
            fields_used=list(raw.get("fields_used", [])),
            version=raw.get("version"),
            upstream=raw.get("upstream"),
            files=[
                SourceFile(path=f["path"], sha256=f["sha256"])
                for f in raw.get("files", [])
            ],
            redistribution_notes=raw.get("redistribution_notes"),
        )


@dataclass
class SourceRegister:
    sources: dict[str, Source]

    @staticmethod
    def load(path: Path) -> "SourceRegister":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = [Source.from_json(s) for s in raw.get("sources", [])]
        return SourceRegister({s.id: s for s in entries})

    def __contains__(self, source_id: str) -> bool:
        return source_id in self.sources

    def __getitem__(self, source_id: str) -> Source:
        return self.sources[source_id]

    def summary(self) -> list[dict[str, str]]:
        """A compact form suitable for embedding in the build manifest."""
        return [
            {
                "id": s.id,
                "name": s.name,
                "licence": s.licence,
                "version": s.version or s.retrieved,
            }
            for s in sorted(self.sources.values(), key=lambda s: s.id)
        ]

    def render_notice(self) -> str:
        """Render ``NOTICE.md`` from the register."""
        parts = [NOTICE_HEADER]
        for source in sorted(self.sources.values(), key=lambda s: s.id):
            parts.append(f"\n## {source.name}\n")
            parts.append(f"- **Source ID:** `{source.id}`")
            parts.append(f"- **Homepage:** {source.homepage}")
            parts.append(f"- **Retrieved:** {source.retrieved}")
            if source.version:
                parts.append(f"- **Version:** {source.version}")
            parts.append(f"- **Licence:** {source.licence} ({source.licence_url})")
            parts.append(f"- **Fields used:** {', '.join(source.fields_used)}")
            if source.upstream:
                parts.append(f"- **Upstream:** {UPSTREAM_LABELS[source.upstream]}")
            if source.files:
                parts.append("- **Checksums (SHA-256):**")
                for entry in source.files:
                    parts.append(f"  - `{entry.path}` — `{entry.sha256}`")
            parts.append(f"\n> {source.attribution}\n")
            if source.redistribution_notes:
                parts.append(f"**Redistribution notes:** {source.redistribution_notes}\n")
        return "\n".join(parts).rstrip() + "\n"


def file_checksum(path: Path) -> str:
    """SHA-256 of a source file, in the bare-hex form the register records.

    Bare hex rather than a ``sha256:`` prefix so the value can be compared with
    a recorded digest, and pasted into ``sha256sum -c``, without stripping.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

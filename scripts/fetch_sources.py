#!/usr/bin/env python3
"""Download the third-party source files into ``data/raw``.

This is the *only* part of the toolchain that touches the network, and it is
never run by CI. Imports are performed locally, the canonical diff is reviewed
by a human, and the reviewed output is committed. That keeps the Pages build
deterministic and stops an upstream change from altering the corpus silently.

Nothing downloaded here is committed: ``data/raw`` is gitignored, because the
raw dumps are large and the canonical corpus is what this repository
redistributes.

Usage::

    python scripts/fetch_sources.py            # fetch anything missing
    python scripts/fetch_sources.py --force    # re-fetch everything
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

RAW = Path("data/raw")

JMDICT_RELEASE = "3.6.2+20260803141815"
FURIGANA_RELEASE = "2.3.1+2026-07-25"

LEVEL_URL = (
    "https://raw.githubusercontent.com/stephenmk/yomitan-jlpt-vocab/HEAD/"
    "original_data/{level}.csv"
)
JMDICT_URL = (
    "https://github.com/scriptin/jmdict-simplified/releases/download/"
    f"{JMDICT_RELEASE.replace('+', '%2B')}/"
    f"jmdict-examples-eng-{JMDICT_RELEASE.replace('+', '%2B')}.json.tgz"
)
FURIGANA_URL = (
    "https://github.com/Doublevil/JmdictFurigana/releases/download/"
    f"{FURIGANA_RELEASE.replace('+', '%2B')}/JmdictFurigana.txt"
)

USER_AGENT = "kotoba-trmnl-plugin/1.0 (+https://github.com/simonjgreen/trmnl-japanese-vocab)"


def download(url: str, destination: Path) -> bytes:
    """Fetch *url*, writing it to *destination* and returning the bytes."""
    print(f"  fetching {url}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    print(f"  -> {destination} ({len(payload) / 1e6:.1f} MB)")
    return payload


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def fetch_levels(force: bool) -> None:
    print("JLPT level lists (stephenmk/yomitan-jlpt-vocab, CC BY-SA 4.0)")
    target_dir = RAW / "jlpt"
    for level in ("n1", "n2", "n3", "n4", "n5"):
        target = target_dir / f"{level}.csv"
        if target.exists() and not force:
            print(f"  {target} present, skipping")
            continue
        download(LEVEL_URL.format(level=level), target)


def fetch_jmdict(force: bool) -> None:
    print("JMdict with examples (scriptin/jmdict-simplified, CC BY-SA 4.0)")
    target = RAW / "jmdict-examples-eng.json"
    if target.exists() and not force:
        print(f"  {target} present, skipping")
        return
    archive = RAW / "jmdict-examples-eng.json.tgz"
    download(JMDICT_URL, archive)
    print("  extracting")
    with tarfile.open(archive, "r:gz") as tar:
        member = next(
            (m for m in tar.getmembers() if m.name.endswith(".json")), None
        )
        if member is None:
            raise SystemExit("no .json member found in the JMdict archive")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise SystemExit("could not read the JMdict archive member")
        with target.open("wb") as out:
            shutil.copyfileobj(extracted, out)
    archive.unlink()
    print(f"  -> {target} ({target.stat().st_size / 1e6:.1f} MB)")


def fetch_furigana(force: bool) -> None:
    print("Furigana segmentation (Doublevil/JmdictFurigana, CC BY-SA 4.0)")
    target = RAW / "JmdictFurigana.txt"
    if target.exists() and not force:
        print(f"  {target} present, skipping")
        return
    download(FURIGANA_URL, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-download files that already exist"
    )
    parser.add_argument(
        "--checksums",
        action="store_true",
        help="print SHA-256 checksums for data/sources.yml",
    )
    args = parser.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    fetch_levels(args.force)
    fetch_jmdict(args.force)
    fetch_furigana(args.force)

    if args.checksums:
        print("\nchecksums:")
        for path in sorted(RAW.rglob("*")):
            if path.is_file() and path.name != ".gitkeep":
                print(f"  {path}: {sha256(path)}")

    print("\nDone. Next: make import")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Download the third-party source files into ``data/raw``.

This is the *only* part of the toolchain that touches the network, and it is
never run by CI. Imports are performed locally, the canonical diff is reviewed
by a human, and the reviewed output is committed. That keeps the Pages build
deterministic and stops an upstream change from altering the corpus silently.

Nothing downloaded here is committed: ``data/raw`` is gitignored, because the
raw dumps are large and the canonical corpus is what this repository
redistributes.

Every file is checked against the SHA-256 recorded for it in
``data/sources.yml``. The two kinds of source are not treated alike, because a
scheme that cries wolf gets switched off:

* The JMdict and furigana URLs name immutable release artefacts, so a digest
  mismatch means a corrupt or truncated download, or a re-tagged release. That
  is an error and the fetch stops.
* The JLPT level lists are served from a branch head, so upstream can change at
  any time and a mismatch is expected occasionally. That is a warning asking
  for the canonical diff to be reviewed and the register updated.

Usage::

    python scripts/fetch_sources.py            # fetch anything missing, verify
    python scripts/fetch_sources.py --force    # re-fetch everything
    python scripts/fetch_sources.py --checksums        # print digests
    python scripts/fetch_sources.py --update-checksums # record them
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - environment problem, not logic
    raise SystemExit(
        "PyYAML is required to read data/sources.yml. Run this script through "
        "the project virtualenv (make fetch-sources), or pip install -e '.[dev]'."
    ) from None

RAW = Path("data/raw")
SOURCES = Path("data/sources.yml")

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

# Identifies the tool to upstream hosts without naming a particular fork.
USER_AGENT = "kotoba-trmnl-plugin/1.0 (+https://github.com/topics/trmnl)"

#: Which register entry owns which downloaded file. The script owns the fetch
#: plan; the register owns the digests and the pinned/head-tracked judgement.
#: Keeping the mapping here means an unrecorded file can still be attributed to
#: a source, and so still be reported rather than passing unnoticed.
OWNERS: dict[str, tuple[Path, ...]] = {
    "jlpt-waller": tuple(RAW / "jlpt" / f"{level}.csv" for level in
                         ("n1", "n2", "n3", "n4", "n5")),
    "jmdict": (RAW / "jmdict-examples-eng.json",),
    "jmdict-furigana": (RAW / "JmdictFurigana.txt",),
}


# --------------------------------------------------------------------------
# The provenance register
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Expectation:
    """What the register says a downloaded file should hash to."""

    source_id: str
    path: Path
    sha256: str | None
    pinned: bool


class Register:
    """The digests recorded in ``data/sources.yml``, and the verdicts so far.

    Verification results are accumulated rather than raised, so that one run
    reports on every file. A single mismatch printed halfway through a fetch of
    seven files tells a maintainer much less than the whole picture.
    """

    def __init__(self, expectations: dict[Path, Expectation]) -> None:
        self._expectations = expectations
        self.failures: list[str] = []
        self.warnings: list[str] = []

    @staticmethod
    def load(path: Path = SOURCES) -> "Register":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        by_id = {entry["id"]: entry for entry in raw.get("sources", [])}
        expectations: dict[Path, Expectation] = {}
        for source_id, owned in OWNERS.items():
            entry = by_id.get(source_id)
            if entry is None:
                raise SystemExit(
                    f"{path}: no source declared with id {source_id!r}; the "
                    "fetch plan and the provenance register have diverged"
                )
            upstream = entry.get("upstream")
            if upstream not in ("pinned", "head-tracked"):
                raise SystemExit(
                    f"{path}: source {source_id!r} must declare upstream as "
                    "'pinned' or 'head-tracked' so a digest mismatch can be "
                    "judged"
                )
            recorded = {
                Path(f["path"]): f["sha256"] for f in entry.get("files", [])
            }
            for owned_path in owned:
                expectations[owned_path] = Expectation(
                    source_id=source_id,
                    path=owned_path,
                    sha256=recorded.get(owned_path),
                    pinned=upstream == "pinned",
                )
        return Register(expectations)

    def __iter__(self):
        return iter(self._expectations.values())

    def verify(self, path: Path) -> None:
        """Check *path* against its recorded digest and record the verdict."""
        expected = self._expectations.get(path)
        if expected is None:
            self.warnings.append(
                f"{path} is not claimed by any source in {SOURCES}"
            )
            return
        if expected.sha256 is None:
            self.warnings.append(
                f"{path} has no recorded digest, so nothing was verified; "
                "run --update-checksums to record one"
            )
            return
        actual = sha256(path)
        if actual == expected.sha256:
            print(f"  checksum ok ({actual[:12]}…)")
            return
        if expected.pinned:
            self.failures.append(
                f"{path} does not match the digest recorded for "
                f"{expected.source_id}\n"
                f"    recorded: {expected.sha256}\n"
                f"    actual:   {actual}\n"
                "    This URL names an immutable release, so the download is "
                "corrupt or the release was re-tagged. Delete the file and "
                "re-run with --force; if it still differs, check upstream "
                "before touching the register."
            )
        else:
            self.warnings.append(
                f"{path} does not match the digest recorded for "
                f"{expected.source_id}\n"
                f"    recorded: {expected.sha256}\n"
                f"    actual:   {actual}\n"
                "    This source tracks a branch head, so upstream has moved. "
                "Run make import, review the canonical diff, then record the "
                "new digest with --update-checksums --accept-upstream-change."
            )

    def report(self) -> int:
        """Print the accumulated verdicts and return a process exit code."""
        for warning in self.warnings:
            print(f"\nwarning: {warning}")
        for failure in self.failures:
            print(f"\nerror: {failure}")
        return 1 if self.failures else 0


# --------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------


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
    """Bare-hex SHA-256, matching the form recorded in the register."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_levels(force: bool, register: Register) -> None:
    print("JLPT level lists (stephenmk/yomitan-jlpt-vocab, CC BY-SA 4.0)")
    target_dir = RAW / "jlpt"
    for level in ("n1", "n2", "n3", "n4", "n5"):
        target = target_dir / f"{level}.csv"
        if target.exists() and not force:
            print(f"  {target} present, skipping")
        else:
            download(LEVEL_URL.format(level=level), target)
        # Files already on disk are verified too. A download interrupted on an
        # earlier run leaves a short file that the skip path would otherwise
        # keep reusing for ever.
        register.verify(target)


def fetch_jmdict(force: bool, register: Register) -> None:
    print("JMdict with examples (scriptin/jmdict-simplified, CC BY-SA 4.0)")
    target = RAW / "jmdict-examples-eng.json"
    if target.exists() and not force:
        print(f"  {target} present, skipping")
        register.verify(target)
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
    # The archive is deleted, so the extracted JSON is what the register
    # records and what a later run can re-check.
    register.verify(target)


def fetch_furigana(force: bool, register: Register) -> None:
    print("Furigana segmentation (Doublevil/JmdictFurigana, CC BY-SA 4.0)")
    target = RAW / "JmdictFurigana.txt"
    if target.exists() and not force:
        print(f"  {target} present, skipping")
    else:
        download(FURIGANA_URL, target)
    register.verify(target)


# --------------------------------------------------------------------------
# Recording digests
# --------------------------------------------------------------------------


def print_checksums(register: Register) -> None:
    print("\nchecksums:")
    for expected in register:
        if expected.path.exists():
            print(f"  - path: {expected.path}")
            print(f"    sha256: {sha256(expected.path)}")
        else:
            print(f"  # {expected.path} is not present")
    print(
        "\nPaste these under the owning source's `files:` key in "
        f"{SOURCES}, or let --update-checksums do it."
    )


def rewrite_digest(text: str, path: Path, digest: str) -> str:
    """Return *text* with the ``sha256`` recorded for *path* set to *digest*.

    Edited as text rather than round-tripped through the YAML writer, which
    would discard every comment in the register — and the comments are the part
    explaining why the digests are there at all.
    """
    lines = text.splitlines(keepends=True)
    anchor = re.compile(rf"^\s*-\s+path:\s+{re.escape(str(path))}\s*$")
    for index, line in enumerate(lines):
        if not anchor.match(line.rstrip("\n")):
            continue
        for offset in range(index + 1, min(index + 4, len(lines))):
            match = re.match(r"^(\s*sha256:\s+)[0-9a-f]{64}\s*$", lines[offset])
            if match:
                lines[offset] = f"{match.group(1)}{digest}\n"
                return "".join(lines)
            if re.match(r"^\s*-\s+path:", lines[offset]):
                break
        break
    raise SystemExit(
        f"{SOURCES}: could not find the sha256 recorded for {path}; the "
        "register has been reformatted and needs editing by hand"
    )


def update_checksums(register: Register, accept_upstream_change: bool) -> int:
    """Write current digests back into the register, refusing to launder.

    An existing digest is never overwritten unless the maintainer says, in the
    command line, that they have looked at the change. Otherwise this command
    would turn any bad download into a recorded, blessed digest simply by being
    run twice — which is exactly the accident verification exists to catch.
    """
    text = SOURCES.read_text(encoding="utf-8")
    changed = 0
    blocked = 0
    for expected in register:
        if not expected.path.exists():
            print(f"  {expected.path} not present, skipping")
            continue
        actual = sha256(expected.path)
        if expected.sha256 is None:
            print(
                f"  {expected.path} has no entry in the register. Add one "
                f"under source {expected.source_id!r}:\n"
                f"      - path: {expected.path}\n"
                f"        sha256: {actual}"
            )
            blocked += 1
        elif actual == expected.sha256:
            print(f"  {expected.path} unchanged")
        elif expected.pinned:
            print(
                f"  {expected.path} differs, and {expected.source_id} is "
                "pinned to an immutable release, so the recorded digest is "
                "not rewritten here. If the release genuinely moved, bump the "
                "release constant in this script and the version in the "
                "register, delete the recorded sha256 line, and re-run."
            )
            blocked += 1
        elif not accept_upstream_change:
            print(
                f"  {expected.path} differs. Review the canonical diff from "
                "make import, then re-run with --accept-upstream-change to "
                f"record {actual}."
            )
            blocked += 1
        else:
            text = rewrite_digest(text, expected.path, actual)
            print(f"  {expected.path}\n    {expected.sha256} -> {actual}")
            changed += 1

    if changed:
        SOURCES.write_text(text, encoding="utf-8")
        print(f"\nWrote {changed} digest(s) to {SOURCES}.")
        print("Next: kotoba validate --write-notice, then review the diff.")
    else:
        print(f"\nNo digests written to {SOURCES}.")
    return 1 if blocked else 0


def main() -> int:
    # The module docstring is the operator's guide to this script, so it is
    # shown verbatim rather than reflowed into one paragraph.
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--force", action="store_true", help="re-download files that already exist"
    )
    parser.add_argument(
        "--checksums",
        action="store_true",
        help="print SHA-256 checksums for data/sources.yml",
    )
    parser.add_argument(
        "--update-checksums",
        action="store_true",
        help="record current digests in data/sources.yml (never silently "
        "overwriting one that has already been recorded)",
    )
    parser.add_argument(
        "--accept-upstream-change",
        action="store_true",
        help="with --update-checksums, allow a head-tracked source's recorded "
        "digest to be replaced, having reviewed the resulting corpus diff",
    )
    args = parser.parse_args()

    register = Register.load()

    RAW.mkdir(parents=True, exist_ok=True)
    fetch_levels(args.force, register)
    fetch_jmdict(args.force, register)
    fetch_furigana(args.force, register)

    if args.checksums:
        print_checksums(register)

    status = register.report()

    if args.update_checksums:
        print("\nrecording digests:")
        status = max(status, update_checksums(register, args.accept_upstream_change))

    if status:
        print("\nStopped: the checks above must be resolved first.")
        return status

    print("\nDone. Next: make import")
    return 0


if __name__ == "__main__":
    sys.exit(main())

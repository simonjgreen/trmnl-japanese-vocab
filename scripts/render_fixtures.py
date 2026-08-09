#!/usr/bin/env python3
"""Render every visual fixture through ``trmnlp`` and collect the artefacts.

``trmnlp`` always reads ``.trmnlp.yml`` from the project directory, and it
polls the configured URL when it renders. Both are inconvenient for fixtures,
so each fixture is rendered in a throwaway copy of ``src/`` whose
``.trmnlp.yml`` injects the payload through ``variables:``. That keeps the
render hermetic — no network, no live data — and leaves the working tree
untouched.

Usage::

    python scripts/render_fixtures.py                 # HTML for every fixture
    python scripts/render_fixtures.py --png           # HTML and PNG
    python scripts/render_fixtures.py --only full_reference
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO / "tests" / "fixtures"
OUTPUT_DIR = REPO / "dist" / "renders"
DOCKER_IMAGE = os.environ.get("KOTOBA_TRMNLP_IMAGE", "kotoba/trmnlp:latest")

VIEWS = ("full", "half_horizontal", "half_vertical", "quadrant")

#: Nominal pixel dimensions per view on the original 800x480 panel.
VIEW_SIZES = {
    "full": (800, 480),
    "half_horizontal": (800, 240),
    "half_vertical": (400, 480),
    "quadrant": (400, 240),
}


def have_local_trmnlp() -> bool:
    return shutil.which("trmnlp") is not None


def run_trmnlp(project: Path, png: bool) -> subprocess.CompletedProcess[str]:
    """Run ``trmnlp build`` against *project*, preferring a local install."""
    args = ["build"] + (["--png"] if png else [])
    if have_local_trmnlp():
        return subprocess.run(
            ["trmnlp", *args],
            cwd=project,
            capture_output=True,
            text=True,
        )
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-u",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{project}:/plugin",
            "-w",
            "/plugin",
            # Selenium needs a writable HOME for its driver cache; without one
            # the PNG render fails while the HTML build quietly succeeds.
            "-e",
            "HOME=/tmp",
            "--shm-size=512m",
            DOCKER_IMAGE,
            *args,
        ],
        capture_output=True,
        text=True,
    )


def build_config(fixture: dict) -> dict:
    """Build a ``.trmnlp.yml`` that injects *fixture* instead of polling."""
    settings = fixture.get("_settings", {})
    config = {
        "watch": False,
        "custom_fields": {
            "jlpt_level": fixture.get("level", "n3"),
            "show_example_translation": str(
                settings.get("show_example_translation", False)
            ).lower(),
            "show_rotation_progress": str(
                settings.get("show_rotation_progress", False)
            ).lower(),
            # Deliberately unreachable: a fixture render must never poll.
            "data_base_url": "http://fixture.invalid/api/v1",
        },
        "time_zone": "Europe/London",
        "variables": {"trmnl": {}},
    }
    payload = {k: v for k, v in fixture.items() if not k.startswith("_")}
    config["variables"].update(payload)
    return config


def render_fixture(path: Path, png: bool, keep: bool = False) -> bool:
    """Render one fixture. Returns True on success."""
    fixture = json.loads(path.read_text(encoding="utf-8"))
    name = path.stem
    destination = OUTPUT_DIR / name
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"kotoba-{name}-") as tmp:
        project = Path(tmp)
        shutil.copytree(REPO / "src", project / "src")
        (project / ".trmnlp.yml").write_text(
            yaml.safe_dump(build_config(fixture), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = run_trmnlp(project, png)
        if result.returncode != 0:
            print(f"  FAILED {name}: {result.stderr.strip()[:400]}", file=sys.stderr)
            return False

        produced = 0
        for artefact in sorted((project / "_build").glob("*")):
            if artefact.suffix in (".html", ".png"):
                shutil.copy2(artefact, destination / artefact.name)
                produced += 1

        if keep:
            shutil.copytree(project, destination / "_project", dirs_exist_ok=True)

    missing = [v for v in VIEWS if not (destination / f"{v}.html").exists()]
    if missing:
        print(f"  FAILED {name}: no output for {', '.join(missing)}", file=sys.stderr)
        return False

    if png:
        empty = [
            p.name
            for p in destination.glob("*.png")
            if p.stat().st_size == 0
        ]
        if empty:
            print(f"  FAILED {name}: empty PNGs {empty}", file=sys.stderr)
            return False

    print(f"  {name}: {produced} artefact(s) -> {destination.relative_to(REPO)}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", action="store_true", help="also render PNGs")
    parser.add_argument("--only", help="render a single fixture by name")
    parser.add_argument(
        "--keep", action="store_true", help="keep the generated project directories"
    )
    args = parser.parse_args()

    fixtures = sorted(FIXTURE_DIR.glob("*.json"))
    if args.only:
        fixtures = [p for p in fixtures if p.stem == args.only]
        if not fixtures:
            print(f"no fixture named {args.only!r}", file=sys.stderr)
            return 1

    if not fixtures:
        print(f"no fixtures found in {FIXTURE_DIR}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"rendering {len(fixtures)} fixture(s){' with PNGs' if args.png else ''}")

    failures = [p.stem for p in fixtures if not render_fixture(p, args.png, args.keep)]
    if failures:
        print(f"\n{len(failures)} fixture(s) failed: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"\nall fixtures rendered into {OUTPUT_DIR.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

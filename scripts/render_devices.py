#!/usr/bin/env python3
"""Render a fixture across every distinct TRMNL device viewport.

TRMNL supports around fifty devices, but what matters to this plugin's CSS is
the *CSS viewport* — the panel resolution divided by the device's scale factor,
with a quarter-turn applied for rotated models. Fifty-two models collapse to
twenty-six distinct viewports, and those are what get rendered here.

`trmnlp` always previews at 800x480 and emits a bare ``.screen``, so each
viewport is simulated by injecting the ``--screen-w`` / ``--screen-h`` custom
properties the Framework would set, then rendering at that size. The card
sizes itself from those two variables, so this exercises the real code path.

Usage::

    python scripts/render_devices.py                    # TRMNL's own devices
    python scripts/render_devices.py --all              # every viewport
    python scripts/render_devices.py --fixture kana_only --png
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO / "tests" / "fixtures"
OUTPUT_DIR = REPO / "dist" / "devices"
DOCKER_IMAGE = os.environ.get("KOTOBA_TRMNLP_IMAGE", "kotoba/trmnlp:latest")

VIEWS = ("full", "half_horizontal", "half_vertical", "quadrant")


@dataclass(frozen=True)
class Viewport:
    name: str
    css_w: int
    css_h: int
    models: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.name} ({self.css_w}x{self.css_h})"


#: Distinct CSS viewports, derived from TRMNL's /api/models on 2026-08-09.
#: Regenerate with `--from-api` if the device list changes.
VIEWPORTS: tuple[Viewport, ...] = (
    Viewport("trmnl-og", 800, 480, ("og_png", "og_plus", "og_bwry")),
    Viewport("trmnl-x", 1040, 780, ("v2",)),
    Viewport("kobo-sage", 1371, 1028, ("kobo_sage", "kobo_forma")),
    Viewport("boox-poke5", 1081, 800, ("onyx_boox_poke_5",)),
    Viewport("inkplate-5-2", 1067, 600, ("inkplate_5_2", "raspberry_pi_touch_2")),
    Viewport("meta-portal", 1040, 650, ("meta_portal",)),
    Viewport("remarkable-2", 780, 1040, ("remarkable_paper_2",)),
    Viewport("kindle-scribe", 744, 992, ("amazon_kindle_scribe",)),
    Viewport("boox-go-7", 702, 1044, ("onyx_boox_go_7",)),
    Viewport("kindle-pw7", 670, 905, ("amazon_kindle_paperwhite_7th_gen",)),
    Viewport("kindle-basic", 600, 800, ("amazon_kindle_7", "nook_simple_touch")),
    Viewport("kobo-libra-2", 840, 632, ("kobo_libra_2",)),
    Viewport("kobo-aura-hd", 800, 600, ("kobo_aura_hd", "inky_impression_13_3")),
    Viewport("m5-paper", 960, 540, ("m5_paper_s3",)),
    Viewport("inkplate-10", 800, 550, ("inkplate_10",)),
    Viewport("kindle-2024", 480, 800, ("amazon_kindle_2024",)),
    # The two shortest panels: width says grow, height says shrink.
    Viewport("generic-16-9", 800, 450, ("generic_16_9",)),
    Viewport("boox-palma", 824, 412, ("palma",)),
)

#: TRMNL's own hardware. Everything else is bring-your-own-device.
TRMNL_OWN = ("trmnl-og", "trmnl-x")


def have_local_trmnlp() -> bool:
    return shutil.which("trmnlp") is not None


def run_trmnlp(project: Path, png: bool, width: int, height: int):
    args = ["build"]
    if png:
        args += ["--png", "--width", str(width), "--height", str(height)]
    if have_local_trmnlp():
        return subprocess.run(args, cwd=project, capture_output=True, text=True)
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-u", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{project}:/plugin", "-w", "/plugin",
            "-e", "HOME=/tmp", "--shm-size=512m",
            DOCKER_IMAGE, *args,
        ],
        capture_output=True,
        text=True,
    )


def render(viewport: Viewport, fixture_path: Path, png: bool) -> tuple[bool, str]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    settings = fixture.get("_settings", {})
    payload = {k: v for k, v in fixture.items() if not k.startswith("_")}

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
            "data_base_url": "http://fixture.invalid/api/v1",
        },
        "time_zone": "Europe/London",
        "variables": {"trmnl": {}, **payload},
    }

    destination = OUTPUT_DIR / fixture_path.stem / viewport.name
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"kotoba-{viewport.name}-") as tmp:
        project = Path(tmp)
        shutil.copytree(REPO / "src", project / "src")
        # Inject exactly what the Framework's screen--<device> class sets.
        shared = project / "src" / "shared.liquid"
        shared.write_text(
            shared.read_text(encoding="utf-8")
            + f"\n<style>.screen{{--screen-w:{viewport.css_w}px;"
              f"--screen-h:{viewport.css_h}px;}}</style>\n",
            encoding="utf-8",
        )
        (project / ".trmnlp.yml").write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        result = run_trmnlp(project, png, viewport.css_w, viewport.css_h)
        if result.returncode != 0:
            return False, result.stderr.strip()[:300]

        for artefact in sorted((project / "_build").glob("*")):
            if artefact.suffix in (".html", ".png"):
                shutil.copy2(artefact, destination / artefact.name)

    missing = [v for v in VIEWS if not (destination / f"{v}.html").exists()]
    if missing:
        return False, f"no output for {', '.join(missing)}"
    return True, str(destination.relative_to(REPO))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", default="full_reference")
    parser.add_argument("--png", action="store_true")
    parser.add_argument(
        "--all", action="store_true", help="every viewport, not just TRMNL's own"
    )
    parser.add_argument("--only", help="render a single viewport by name")
    args = parser.parse_args()

    fixture_path = FIXTURE_DIR / f"{args.fixture}.json"
    if not fixture_path.exists():
        print(f"no fixture named {args.fixture!r}", file=sys.stderr)
        return 1

    targets = list(VIEWPORTS)
    if args.only:
        targets = [v for v in targets if v.name == args.only]
        if not targets:
            print(f"no viewport named {args.only!r}", file=sys.stderr)
            return 1
    elif not args.all:
        targets = [v for v in targets if v.name in TRMNL_OWN]

    print(f"fixture {args.fixture}: {len(targets)} viewport(s)")
    failures = []
    for viewport in targets:
        ok, detail = render(viewport, fixture_path, args.png)
        status = "ok  " if ok else "FAIL"
        print(f"  {status} {viewport.label:26} {detail}")
        if not ok:
            failures.append(viewport.name)

    if failures:
        print(f"\n{len(failures)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print(f"\nrendered into {OUTPUT_DIR.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

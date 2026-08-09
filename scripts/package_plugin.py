#!/usr/bin/env python3
"""Package the plugin as a flat ZIP for manual import into TRMNL.

This is the fallback path for anyone who does not want to wire up
``trmnlp push``. TRMNL's private-plugin import expects a flat archive — the
settings file and the Liquid views at the root, with no directory prefix.

Usage::

    python scripts/package_plugin.py
    python scripts/package_plugin.py --output dist/kotoba.zip
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

SRC = Path("src")
DEFAULT_OUTPUT = Path("dist/kotoba-plugin.zip")

REQUIRED = ("settings.yml", "full.liquid")
OPTIONAL = (
    "shared.liquid",
    "half_horizontal.liquid",
    "half_vertical.liquid",
    "quadrant.liquid",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default=str(SRC))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    src = Path(args.src)
    output = Path(args.output)

    missing = [name for name in REQUIRED if not (src / name).is_file()]
    if missing:
        print(f"missing required file(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    settings = (src / "settings.yml").read_text(encoding="utf-8")
    if "GITHUB_OWNER" in settings:
        print(
            "warning: settings.yml still contains the placeholder data endpoint.\n"
            "         run scripts/configure_repo.py first, or set the endpoint\n"
            "         by hand in the TRMNL UI after importing.",
            file=sys.stderr,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in (*REQUIRED, *OPTIONAL):
            path = src / name
            if not path.is_file():
                continue
            # Flat: arcname is the bare filename, never a nested path.
            archive.write(path, arcname=name)
            included.append(name)

    size = output.stat().st_size
    print(f"wrote {output} ({size} bytes)")
    for name in included:
        print(f"  {name}")
    print(
        "\nImport it in TRMNL under Plugins -> Private Plugin -> Import,\n"
        "then set the learner level and confirm the data endpoint."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

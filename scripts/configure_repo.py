#!/usr/bin/env python3
"""Point the plugin at your own GitHub Pages deployment.

``src/settings.yml`` ships pointing at this project's own Pages site, so that
someone who imports the plugin ZIP without forking gets working data straight
away (README "Route 1"). This script repoints it at your deployment, and is
idempotent: running it twice changes nothing the second time.

The shipped endpoint and the historical ``GITHUB_OWNER`` placeholder are both
treated as defaults that may be overwritten freely. Only an endpoint you set
yourself is protected behind ``--force``.

Usage::

    python scripts/configure_repo.py                        # detect from git
    python scripts/configure_repo.py --owner me --repo mine
    python scripts/configure_repo.py --owner me --repo mine --force
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

SETTINGS = Path("src/settings.yml")

PLACEHOLDER_OWNER = "GITHUB_OWNER"
PLACEHOLDER_REPO = "GITHUB_REPO"
PLACEHOLDER_URL = (
    f"https://{PLACEHOLDER_OWNER}.github.io/{PLACEHOLDER_REPO}/api/v1"
)

#: The endpoint this repository ships with. Not a secret and not personal
#: data — it is the public data API the plugin defaults to. Listed here so a
#: fresh fork is not mistaken for a deliberately customised checkout.
SHIPPED_URL = "https://simonjgreen.github.io/trmnl-japanese-vocab/api/v1"

#: Endpoints that `configure_repo` may overwrite without `--force`.
DEFAULT_URLS = (PLACEHOLDER_URL, SHIPPED_URL)

# GitHub's own rules: owners are alphanumeric with single hyphens; repository
# names additionally allow dots and underscores.
OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")

REMOTE_PATTERNS = (
    re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>.+?)(?:\.git)?$"),
    re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>.+?)(?:\.git)?$"),
    re.compile(r"^ssh://git@github\.com/(?P<owner>[^/]+)/(?P<repo>.+?)(?:\.git)?$"),
)


def detect_from_git(remote: str = "origin") -> tuple[str, str] | None:
    """Read owner and repository from a conventional GitHub remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    url = result.stdout.strip()
    for pattern in REMOTE_PATTERNS:
        match = pattern.match(url)
        if match:
            return match.group("owner"), match.group("repo")
    return None


def pages_url(owner: str, repo: str) -> str:
    return f"https://{owner}.github.io/{repo}/api/v1"


def current_endpoint(text: str) -> str | None:
    """Extract the configured `data_base_url` default, if there is one."""
    match = re.search(
        r"keyname:\s*data_base_url.*?^\s*default:\s*(\S+)\s*$",
        text,
        re.DOTALL | re.MULTILINE,
    )
    return match.group(1) if match else None


def rewrite(text: str, owner: str, repo: str) -> str:
    """Replace every occurrence of the placeholder endpoint."""
    target = pages_url(owner, repo)
    existing = current_endpoint(text)
    if existing and existing != PLACEHOLDER_URL:
        # Rewrite whatever is currently configured, not just the placeholder,
        # so that re-pointing an already-configured checkout works. This also
        # catches the `placeholder:` field, which carries the same URL.
        text = text.replace(existing, target)
    return text.replace(PLACEHOLDER_URL, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", help="GitHub user or organisation")
    parser.add_argument("--repo", help="GitHub repository name")
    parser.add_argument("--remote", default="origin", help="git remote to inspect")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an endpoint that is not the shipped placeholder",
    )
    parser.add_argument("--settings", default=str(SETTINGS))
    args = parser.parse_args()

    owner, repo = args.owner, args.repo
    # `is None` rather than falsiness: an explicitly empty --owner is a bad
    # value to reject, not a request to fall back to git detection.
    if owner is None or repo is None:
        detected = detect_from_git(args.remote)
        if detected is None:
            print(
                "could not determine owner/repo from git; pass --owner and --repo",
                file=sys.stderr,
            )
            return 1
        owner, repo = detected
        print(f"detected {owner}/{repo} from the {args.remote!r} remote")

    if not OWNER_PATTERN.match(owner):
        print(f"invalid GitHub owner name: {owner!r}", file=sys.stderr)
        return 1
    if not REPO_PATTERN.match(repo):
        print(f"invalid GitHub repository name: {repo!r}", file=sys.stderr)
        return 1

    path = Path(args.settings)
    if not path.exists():
        print(f"missing {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    target = pages_url(owner, repo)
    existing = current_endpoint(text)

    if existing == target:
        print(f"already configured for {owner}/{repo}; nothing to do")
        return 0

    if existing and existing not in DEFAULT_URLS and not args.force:
        print(
            f"refusing to overwrite a custom data endpoint:\n  {existing}\n"
            "re-run with --force if that is what you want",
            file=sys.stderr,
        )
        return 1

    path.write_text(rewrite(text, owner, repo), encoding="utf-8")

    print(f"configured {path} for {owner}/{repo}")
    print(f"\n  Pages site:   https://{owner}.github.io/{repo}/")
    print(f"  Data API:     {target}")
    print(f"  Example URL:  {target}/card/n5/0.json")

    # A committed plugin id belongs to whoever created that plugin. Pushing a
    # fork with the upstream id still in place targets someone else's plugin,
    # which the API will reject — confusingly, and after the fact.
    inherited = re.search(r"^\s*id:\s*(\d+)\s*$", text, re.MULTILINE)
    id_step = "  4. bin/trmnlp login && bin/trmnlp push   (creates the plugin)"
    if inherited:
        print(
            f"\nNOTE: {path} still carries the upstream plugin id "
            f"{inherited.group(1)}.\n"
            "      That id is not yours. Delete the `id:` line before your\n"
            "      first push, then commit the new id that push prints."
        )
        id_step = (
            "  4. remove the `id:` line, then "
            "bin/trmnlp login && bin/trmnlp push"
        )

    print(
        "\nNext:\n"
        "  1. make validate && make build-site\n"
        "  2. commit and push to GitHub\n"
        "  3. Settings -> Pages -> Source: GitHub Actions\n"
        f"{id_step}\n"
        "  5. add the returned id: to src/settings.yml and commit it\n"
        "  6. add TRMNL_API_KEY as a repository Actions secret"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

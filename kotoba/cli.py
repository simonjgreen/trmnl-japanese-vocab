"""``kotoba`` command line interface.

Every subcommand exits non-zero on failure, prints concise human-readable
output by default, and offers ``--json`` where a machine-readable form is
useful in CI. ``validate`` and ``build-site`` never touch the network.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .furigana import align
from .importer import run_import
from .models import level_key
from .provenance import SourceRegister
from .selection import Scheduler
from .site_builder import BuildConfig, SelectionConfig, build_site
from .validation import summarise, validate_corpus, validate_site

DEFAULT_VOCAB_DIR = Path("data/vocabulary")
DEFAULT_SOURCES = Path("data/sources.yml")
DEFAULT_SCHEMAS = Path("schemas")
DEFAULT_VERSION_FILE = Path("data/VERSION")


def dataset_version(commit_sha: str | None = None) -> str:
    """``2026.08.1+1a2b3c4d`` — corpus version plus the building commit."""
    base = "0.0.0"
    if DEFAULT_VERSION_FILE.exists():
        base = DEFAULT_VERSION_FILE.read_text(encoding="utf-8").strip() or base
    sha = commit_sha or _git_sha()
    return f"{base}+{sha}" if sha else base


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip() or None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _emit(data: dict[str, Any], as_json: bool, human: str) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(human)


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_import(args: argparse.Namespace) -> int:
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    sources = config.get("sources", [])
    if not sources:
        print(f"no sources declared in {args.config}", file=sys.stderr)
        return 1

    records: list[Any] = []
    for spec in sources:
        adapter = _build_adapter(spec)
        print(f"reading source {spec['id']} ({spec['type']})")
        records.extend(adapter.read())
        if getattr(adapter, "stats", None):
            for key, value in adapter.stats.items():
                print(f"  {key}: {value}")

    stats = run_import(
        records,
        vocabulary_dir=Path(args.vocabulary_dir),
        overrides_path=Path(args.overrides),
        review_dir=Path(args.review_dir),
    )
    _emit(
        stats.as_dict(),
        args.json,
        "\n".join(
            [
                f"read {stats.read} source records",
                f"skipped {stats.skipped_bad_level} with an unusable level",
                f"skipped {stats.skipped_duplicate} duplicates",
                f"{stats.overrides_applied} furigana overrides applied",
                f"{stats.needs_review} entries need furigana review "
                f"(written disabled; see {args.review_dir}/furigana-review.md)",
                "written: "
                + ", ".join(f"{k}={v}" for k, v in sorted(stats.written.items())),
            ]
        ),
    )
    return 0


def _build_adapter(spec: dict[str, Any]) -> Any:
    """Instantiate the adapter named by a ``config/sources.yml`` entry."""
    kind = spec.get("type")
    if kind == "csv":
        from .sources.csv_source import CsvSource

        return CsvSource(
            source_id=spec["id"],
            path=Path(spec["path"]),
            mapping=spec.get("mapping", {}),
            encoding=spec.get("encoding", "utf-8-sig"),
            delimiter=spec.get("delimiter", ","),
            level=spec.get("level"),
        )
    if kind == "json":
        from .sources.json_source import JsonSource

        return JsonSource(
            source_id=spec["id"],
            path=Path(spec["path"]),
            mapping=spec.get("mapping", {}),
            root_path=spec.get("root_path"),
            encoding=spec.get("encoding", "utf-8"),
            level=spec.get("level"),
        )
    if kind == "jlpt-jmdict":
        from .sources.jlpt_jmdict import JlptJmdictSource

        return JlptJmdictSource(
            source_id=spec["id"],
            levels_dir=Path(spec.get("levels_dir", "data/raw/jlpt")),
            jmdict_path=Path(spec.get("jmdict_path", "data/raw/jmdict-examples-eng.json")),
            furigana_path=Path(spec.get("furigana_path", "data/raw/JmdictFurigana.txt")),
            jmdict_source_id=spec.get("jmdict_source_id", "jmdict"),
            furigana_source_id=spec.get("furigana_source_id", "jmdict-furigana"),
            example_source_id=spec.get("example_source_id", "tatoeba"),
        )
    raise ValueError(f"unknown source type {kind!r}")


def cmd_validate(args: argparse.Namespace) -> int:
    build_config = BuildConfig.load(Path(args.build_config))
    minimum = 1 if args.demo else build_config.minimum_entries_per_level
    report, _ = validate_corpus(
        vocabulary_dir=Path(args.vocabulary_dir),
        sources_path=Path(args.sources),
        schema_dir=Path(args.schemas),
        minimum_per_level=minimum,
    )

    if args.write_notice:
        register = SourceRegister.load(Path(args.sources))
        Path("NOTICE.md").write_text(register.render_notice(), encoding="utf-8")
        print("wrote NOTICE.md")

    _emit(report.to_json(), args.json, summarise(report))
    return 0 if report.ok else 1


def cmd_build_site(args: argparse.Namespace) -> int:
    build_config = BuildConfig.load(Path(args.build_config))
    if args.slots is not None:
        build_config = BuildConfig(**{**build_config.__dict__, "slot_count": args.slots})
    if args.demo:
        build_config = BuildConfig(
            **{**build_config.__dict__, "status": "demo", "minimum_entries_per_level": 1}
        )

    selection_config = SelectionConfig.load(Path(args.selection_config))
    report, corpus = validate_corpus(
        vocabulary_dir=Path(args.vocabulary_dir),
        sources_path=Path(args.sources),
        schema_dir=Path(args.schemas),
        minimum_per_level=build_config.minimum_entries_per_level,
    )
    if not report.ok:
        print(summarise(report), file=sys.stderr)
        print("refusing to build a site from an invalid corpus", file=sys.stderr)
        return 1

    register = SourceRegister.load(Path(args.sources))
    output = Path(args.output)
    result = build_site(
        corpus=corpus,
        output_dir=output,
        build_config=build_config,
        selection_config=selection_config,
        dataset_version=dataset_version(args.commit_sha),
        sources_summary=register.summary(),
        commit_sha=args.commit_sha or _git_sha(),
        today=date.fromisoformat(args.today) if args.today else None,
        generated_at=datetime.now(timezone.utc),
    )

    total_files = sum(result.file_counts.values())
    _emit(
        {
            "dataset_version": result.dataset_version,
            "slot_seconds": result.slot_seconds,
            "slot_count": result.slot_count,
            "active_entries": result.entry_counts,
            "deck_pool": result.pool_counts,
            "generated_files": result.file_counts,
            "largest_payload_bytes": result.largest_payload,
        },
        args.json,
        "\n".join(
            [
                f"dataset {result.dataset_version}",
                f"{result.slot_count} slots of {result.slot_seconds}s "
                f"(~{result.slot_count * result.slot_seconds / 86400:.1f} day cycle)",
                "deck pools: "
                + ", ".join(f"{k}={v}" for k, v in result.pool_counts.items()),
                f"generated {total_files} card payloads into {output}",
                f"largest payload {result.largest_payload} bytes",
            ]
        ),
    )
    return 0


def cmd_validate_site(args: argparse.Namespace) -> int:
    # Read the limit from the build config rather than trusting a default;
    # the two must agree or a site that built cleanly fails validation.
    build_config = BuildConfig.load(Path(args.build_config))
    report = validate_site(
        site_dir=Path(args.site),
        schema_dir=Path(args.schemas),
        hard_size_limit=build_config.hard_limit_bytes,
    )
    _emit(report.to_json(), args.json, summarise(report))
    return 0 if report.ok else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    selection_config = SelectionConfig.load(Path(args.selection_config))
    report, corpus = validate_corpus(
        vocabulary_dir=Path(args.vocabulary_dir),
        sources_path=Path(args.sources),
        schema_dir=Path(args.schemas),
    )
    key = level_key(args.level)
    active = sorted(
        (e for e in corpus.get(key, []) if e.is_active), key=lambda e: e.id
    )
    if not active:
        print(f"no active entries for level {key}", file=sys.stderr)
        return 1

    day = date.fromisoformat(args.date) if args.date else date.today()
    scheduler = Scheduler(
        [e.id for e in active],
        key,
        selection_config.epoch_date,
        selection_config.selection_version,
        selection_config.selection_salt,
    )
    selection = scheduler.select(day)
    entry = next(e for e in active if e.id == selection.entry_id)

    ruby = "".join(
        f"{s.base}[{s.reading}]" if s.reading else s.base for s in entry.ruby_segments
    )
    _emit(
        {
            "date": day.isoformat(),
            "level": key,
            "entry": entry.to_json(),
            "sequence": {
                "cycle": selection.cycle,
                "position": selection.position,
                "total": selection.total,
            },
        },
        args.json,
        "\n".join(
            [
                f"{day.isoformat()}  {key.upper()}  ({selection.position}/{selection.total},"
                f" cycle {selection.cycle})",
                f"  {entry.surface}  {entry.reading}",
                f"  ruby: {ruby}",
                f"  gloss: {entry.display_gloss}",
                f"  example: {entry.example.ja if entry.example else '-'}",
                f"  english: {entry.example.en if entry.example and entry.example.en else '-'}",
            ]
        ),
    )
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    result = align(args.surface, args.reading)
    rendered = "".join(
        f"<ruby><rb>{s.base}</rb><rt>{s.reading}</rt></ruby>" if s.reading else s.base
        for s in result.segments
    )
    _emit(
        {
            "status": result.status,
            "reason": result.reason,
            "segments": [s.to_json() for s in result.segments],
            "html": rendered,
        },
        args.json,
        "\n".join(
            [
                f"status: {result.status}" + (f" ({result.reason})" if result.reason else ""),
                "segments: "
                + " ".join(
                    f"{s.base}[{s.reading}]" if s.reading else s.base
                    for s in result.segments
                ),
                f"html: {rendered}",
            ]
        ),
    )
    return 0 if result.ok else 1


def cmd_manifest(args: argparse.Namespace) -> int:
    path = Path(args.site) / "api" / "v1" / "manifest.json"
    if not path.exists():
        print(f"no manifest at {path}; run `kotoba build-site` first", file=sys.stderr)
        return 1
    manifest = json.loads(path.read_text(encoding="utf-8"))
    _emit(
        manifest,
        args.json,
        "\n".join(
            [
                f"dataset {manifest['dataset_version']} ({manifest['status']})",
                f"generated {manifest['generated_at']} from commit {manifest.get('commit_sha')}",
                f"slots {manifest['slots']['count']} x {manifest['slots']['seconds']}s",
                "active entries: "
                + ", ".join(f"{k}={v}" for k, v in manifest["active_entries"].items()),
                "files: "
                + ", ".join(f"{k}={v}" for k, v in manifest["generated_files"].items()),
            ]
        ),
    )
    return 0


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kotoba", description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--vocabulary-dir", default=str(DEFAULT_VOCAB_DIR))
        p.add_argument("--sources", default=str(DEFAULT_SOURCES))
        p.add_argument("--schemas", default=str(DEFAULT_SCHEMAS))
        p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    p_import = sub.add_parser("import", help="import sources into the canonical corpus")
    p_import.add_argument("--config", default="config/sources.yml")
    p_import.add_argument("--vocabulary-dir", default=str(DEFAULT_VOCAB_DIR))
    p_import.add_argument("--overrides", default="data/overrides/furigana.yml")
    p_import.add_argument("--review-dir", default="data/review")
    p_import.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    p_import.set_defaults(func=cmd_import)

    p_validate = sub.add_parser("validate", help="validate the corpus and provenance")
    common(p_validate)
    p_validate.add_argument("--build-config", default="config/build.yml")
    p_validate.add_argument("--demo", action="store_true", help="relax minimum counts")
    p_validate.add_argument(
        "--write-notice", action="store_true", help="regenerate NOTICE.md"
    )
    p_validate.set_defaults(func=cmd_validate)

    p_build = sub.add_parser("build-site", help="generate the static Pages site")
    common(p_build)
    p_build.add_argument("--output", default="site")
    p_build.add_argument("--build-config", default="config/build.yml")
    p_build.add_argument("--selection-config", default="config/selection.yml")
    p_build.add_argument(
        "--slots", type=int, help="override the number of slot files per level"
    )
    p_build.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    p_build.add_argument("--commit-sha")
    p_build.add_argument("--demo", action="store_true")
    p_build.set_defaults(func=cmd_build_site)

    p_vsite = sub.add_parser("validate-site", help="validate the generated static API")
    p_vsite.add_argument("--site", default="site")
    p_vsite.add_argument("--schemas", default=str(DEFAULT_SCHEMAS))
    p_vsite.add_argument("--build-config", default="config/build.yml")
    p_vsite.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    p_vsite.set_defaults(func=cmd_validate_site)

    p_inspect = sub.add_parser("inspect", help="show the word for a level and date")
    common(p_inspect)
    p_inspect.add_argument("--level", required=True)
    p_inspect.add_argument("--date")
    p_inspect.add_argument("--selection-config", default="config/selection.yml")
    p_inspect.set_defaults(func=cmd_inspect)

    p_align = sub.add_parser("align", help="align a reading onto a surface")
    p_align.add_argument("--surface", required=True)
    p_align.add_argument("--reading", required=True)
    p_align.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    p_align.set_defaults(func=cmd_align)

    p_manifest = sub.add_parser("manifest", help="summarise the generated manifest")
    p_manifest.add_argument("--site", default="site")
    p_manifest.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    p_manifest.set_defaults(func=cmd_manifest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Generate the static date-specific JSON API served from GitHub Pages.

One tiny document per level per date. The payload changes every day, which is
what gives TRMNL a reason to redraw the screen, and a date-specific URL is
naturally cacheable and inspectable in a browser.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .models import LEVELS, VocabularyEntry, level_display, level_key
from .normalise import display_width
from .selection import Scheduler

SCHEMA_VERSION = "1.0"

#: Ratio of ruby text size to base text size, mirroring the CSS in
#: ``src/shared.liquid``. Used to notice when a long reading over a single
#: kanji is wider than the kanji itself.
RUBY_RATIO = 0.30

#: Word size classes, as (maximum estimated full-width units, class name).
#: Tuned against 800x480 renders; see docs/visual-design.md.
WORD_SIZE_STEPS: tuple[tuple[float, str], ...] = (
    (3.0, "short"),
    (5.0, "medium"),
    (7.5, "long"),
)
WORD_SIZE_FALLBACK = "xlong"

EXAMPLE_SIZE_STEPS: tuple[tuple[float, str], ...] = (
    (22.0, "normal"),
    (34.0, "compact"),
)
EXAMPLE_SIZE_FALLBACK = "tiny"


@dataclass(frozen=True)
class BuildConfig:
    past_days: int = 90
    future_days: int = 3650
    recommended_bytes: int = 5120
    hard_limit_bytes: int = 10240
    minify: bool = True
    status: str = "production"
    minimum_entries_per_level: int = 1

    @staticmethod
    def load(path: Path) -> "BuildConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        date_range = raw.get("date_range", {})
        payload = raw.get("payload", {})
        return BuildConfig(
            past_days=int(date_range.get("past_days", 90)),
            future_days=int(date_range.get("future_days", 3650)),
            recommended_bytes=int(payload.get("recommended_bytes", 5120)),
            hard_limit_bytes=int(payload.get("hard_limit_bytes", 10240)),
            minify=bool(payload.get("minify", True)),
            status=str(raw.get("status", "production")),
            minimum_entries_per_level=int(raw.get("minimum_entries_per_level", 1)),
        )


@dataclass(frozen=True)
class SelectionConfig:
    epoch_date: date
    selection_version: str = "1"
    selection_salt: str = ""

    @staticmethod
    def load(path: Path) -> "SelectionConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        epoch = raw.get("epoch_date")
        epoch_date = epoch if isinstance(epoch, date) else date.fromisoformat(str(epoch))
        return SelectionConfig(
            epoch_date=epoch_date,
            selection_version=str(raw.get("selection_version", "1")),
            selection_salt=str(raw.get("selection_salt", "")),
        )


# --------------------------------------------------------------------------
# Display sizing
# --------------------------------------------------------------------------


def estimated_word_width(entry: VocabularyEntry) -> float:
    """Estimate the rendered width of the target word in full-width units.

    A single kanji carrying a five-kana reading (承る / うけたまわる) is wider
    than the kanji alone, so each segment contributes whichever of its base or
    its ruby is wider.
    """
    total = 0.0
    for segment in entry.ruby_segments:
        base = display_width(segment.base)
        ruby = display_width(segment.reading) * RUBY_RATIO if segment.reading else 0.0
        total += max(base, ruby)
    return total


def classify(value: float, steps: Iterable[tuple[float, str]], fallback: str) -> str:
    for threshold, name in steps:
        if value <= threshold:
            return name
    return fallback


def word_size_class(entry: VocabularyEntry) -> str:
    return classify(estimated_word_width(entry), WORD_SIZE_STEPS, WORD_SIZE_FALLBACK)


def example_size_class(entry: VocabularyEntry) -> str:
    if entry.example is None:
        return "normal"
    return classify(
        display_width(entry.example.ja), EXAMPLE_SIZE_STEPS, EXAMPLE_SIZE_FALLBACK
    )


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------


def build_payload(
    entry: VocabularyEntry,
    level: str,
    day: date,
    dataset_version: str,
    selection_version: str,
    cycle: int,
    position: int,
    total: int,
) -> dict[str, Any]:
    """Build one daily payload. No HTML, no markup, no remote references."""
    word: dict[str, Any] = {
        "id": entry.id,
        "surface": entry.surface,
        "reading": entry.reading,
        "ruby_segments": [s.to_json() for s in entry.ruby_segments],
        "display_gloss": entry.display_gloss,
    }
    if entry.part_of_speech:
        word["part_of_speech"] = entry.part_of_speech[:2]
    if entry.example is not None and entry.example.ja:
        example: dict[str, Any] = {"ja": entry.example.ja}
        if entry.example.en:
            example["en"] = entry.example.en
        word["example"] = example
    word["display"] = {
        "word_size": word_size_class(entry),
        "example_size": example_size_class(entry),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "date": day.isoformat(),
        "level": level,
        "level_display": level_display(level),
        "dataset_version": dataset_version,
        "selection_version": selection_version,
        "word": word,
        "sequence": {"cycle": cycle, "position": position, "total": total},
    }


def dump_payload(payload: dict[str, Any], minify: bool) -> str:
    """Serialise a payload as UTF-8 JSON with Japanese left readable."""
    if minify:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Site build
# --------------------------------------------------------------------------


@dataclass
class BuildResult:
    start_date: date
    end_date: date
    entry_counts: dict[str, int]
    file_counts: dict[str, int]
    dataset_version: str
    largest_payload: int
    oversized: list[str]


def build_site(
    corpus: dict[str, list[VocabularyEntry]],
    output_dir: Path,
    build_config: BuildConfig,
    selection_config: SelectionConfig,
    dataset_version: str,
    sources_summary: list[dict[str, str]] | None = None,
    commit_sha: str | None = None,
    today: date | None = None,
    generated_at: datetime | None = None,
) -> BuildResult:
    """Generate the complete static site into *output_dir*."""
    today = today or datetime.now(timezone.utc).date()
    generated_at = generated_at or datetime.now(timezone.utc)

    start_date = today - timedelta(days=build_config.past_days)
    end_date = today + timedelta(days=build_config.future_days)

    api_dir = output_dir / "api" / "v1"
    daily_dir = api_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    entry_counts: dict[str, int] = {}
    file_counts: dict[str, int] = {}
    largest = 0
    oversized: list[str] = []

    for level in LEVELS:
        key = level_key(level)
        active = sorted(
            (e for e in corpus.get(key, []) if e.is_active), key=lambda e: e.id
        )
        entry_counts[key] = len(active)
        if not active:
            raise ValueError(f"level {key} has no active entries; cannot build site")
        if len(active) < build_config.minimum_entries_per_level:
            raise ValueError(
                f"level {key} has {len(active)} active entries, minimum is "
                f"{build_config.minimum_entries_per_level}"
            )

        by_id = {e.id: e for e in active}
        scheduler = Scheduler(
            [e.id for e in active],
            key,
            selection_config.epoch_date,
            selection_config.selection_version,
            selection_config.selection_salt,
        )

        level_dir = daily_dir / key
        level_dir.mkdir(parents=True, exist_ok=True)

        count = 0
        last_text = ""
        day = start_date
        while day <= end_date:
            selection = scheduler.select(day)
            payload = build_payload(
                by_id[selection.entry_id],
                key,
                day,
                dataset_version,
                selection_config.selection_version,
                selection.cycle,
                selection.position,
                selection.total,
            )
            text = dump_payload(payload, build_config.minify)
            size = len(text.encode("utf-8"))
            largest = max(largest, size)
            if size > build_config.hard_limit_bytes:
                oversized.append(f"{key}/{day.isoformat()} ({size} bytes)")
            (level_dir / f"{day.isoformat()}.json").write_text(text, encoding="utf-8")
            count += 1
            last_text = text
            day += timedelta(days=1)

        file_counts[key] = count
        # For inspection only; the plugin always requests a date-specific path.
        (level_dir / "latest.json").write_text(last_text, encoding="utf-8")
        sample = dump_payload(
            build_payload(
                by_id[scheduler.select(today).entry_id],
                key,
                today,
                dataset_version,
                selection_config.selection_version,
                scheduler.select(today).cycle,
                scheduler.select(today).position,
                scheduler.select(today).total,
            ),
            minify=False,
        )
        (level_dir / "sample.json").write_text(sample, encoding="utf-8")

    if oversized:
        raise ValueError(
            "payloads exceed the hard size limit: " + ", ".join(oversized[:5])
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.replace(microsecond=0).isoformat(),
        "dataset_version": dataset_version,
        "selection_version": selection_config.selection_version,
        "epoch_date": selection_config.epoch_date.isoformat(),
        "status": build_config.status,
        "earliest_date": start_date.isoformat(),
        "latest_date": end_date.isoformat(),
        "active_entries": entry_counts,
        "generated_files": file_counts,
        "sources": sources_summary or [],
        "commit_sha": commit_sha,
    }
    (api_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    health = {
        "status": "ok",
        "dataset_version": dataset_version,
        "generated_at": manifest["generated_at"],
        "earliest_date": manifest["earliest_date"],
        "latest_date": manifest["latest_date"],
        "total_active_entries": sum(entry_counts.values()),
        "data_status": build_config.status,
    }
    (output_dir / "health.json").write_text(
        json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    (output_dir / "index.html").write_text(
        render_index(manifest, today), encoding="utf-8"
    )
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    return BuildResult(
        start_date=start_date,
        end_date=end_date,
        entry_counts=entry_counts,
        file_counts=file_counts,
        dataset_version=dataset_version,
        largest_payload=largest,
        oversized=oversized,
    )


INDEX_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 46rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; line-height: 1.55; }
h1 { margin-bottom: 0.25rem; }
.sub { opacity: 0.7; margin-top: 0; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid rgba(128,128,128,0.3); }
code { background: rgba(128,128,128,0.15); padding: 0.1rem 0.35rem; border-radius: 3px; }
footer { margin-top: 2.5rem; font-size: 0.85rem; opacity: 0.8; }
"""


def render_index(manifest: dict[str, Any], today: date) -> str:
    """Render the Pages landing page.

    The page doubles as the public attribution surface required by the EDRDG
    licence, so the source credits are part of the page rather than a link.
    """
    rows = "".join(
        "<tr><td><code>{key}</code></td><td>{count}</td>"
        '<td><a href="api/v1/daily/{key}/{today}.json">today</a></td>'
        '<td><a href="api/v1/daily/{key}/sample.json">sample</a></td></tr>'.format(
            key=key,
            count=manifest["active_entries"].get(key, 0),
            today=today.isoformat(),
        )
        for key in ("n5", "n4", "n3", "n2", "n1")
    )
    sources = "".join(
        f"<li>{html.escape(s['name'])} — {html.escape(s['licence'])}</li>"
        for s in manifest.get("sources", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kotoba — JLPT Word of the Day: data API</title>
<style>{INDEX_CSS}</style>
</head>
<body>
<h1>Kotoba — JLPT Word of the Day</h1>
<p class="sub">Static data API for the TRMNL private plugin.</p>

<p>Each day and level resolves to one small JSON document. The plugin requests
a date-specific path built from its selected level and the device's local date.</p>

<table>
<thead><tr><th>Level</th><th>Active words</th><th>Today</th><th>Sample</th></tr></thead>
<tbody>{rows}</tbody>
</table>

<p>
<a href="api/v1/manifest.json">manifest.json</a> ·
<a href="health.json">health.json</a>
</p>

<h2>Build</h2>
<ul>
<li>Dataset version: <code>{html.escape(str(manifest["dataset_version"]))}</code></li>
<li>Selection version: <code>{html.escape(str(manifest["selection_version"]))}</code></li>
<li>Generated: <code>{html.escape(str(manifest["generated_at"]))}</code></li>
<li>Date coverage: <code>{manifest["earliest_date"]}</code> to <code>{manifest["latest_date"]}</code></li>
<li>Data status: <code>{html.escape(str(manifest["status"]))}</code></li>
</ul>

<h2>Data sources and licences</h2>
<ul>{sources}</ul>
<p>JMdict is the property of the
<a href="https://www.edrdg.org/">Electronic Dictionary Research and Development Group</a>
and is used in conformance with the
<a href="https://www.edrdg.org/edrdg/licence.html">Group's licence</a>. Example
sentences come from the <a href="https://tatoeba.org/">Tatoeba Project</a>
(CC BY 2.0 FR). Furigana segmentation is from
<a href="https://github.com/Doublevil/JmdictFurigana">JmdictFurigana</a>.
JLPT level estimates originate with
<a href="http://www.tanos.co.uk/jlpt/">Jonathan Waller's JLPT Resources</a>.</p>

<footer>
<p><strong>JLPT level assignments here are community estimates.</strong> The
Japan Foundation and JEES no longer publish official vocabulary lists, and
nothing on this site is endorsed by or affiliated with them.</p>
<p>Plugin code is MIT licensed; the vocabulary data is CC BY-SA 4.0.</p>
</footer>
</body>
</html>
"""

"""Generate the static JSON API served from GitHub Pages.

One tiny document per level per time slot. TRMNL skips rendering when a
polled payload is unchanged, so the card has to differ in the *data* rather
than being chosen in the template — each slot is its own file, and the
plugin's polling URL selects one from the clock.

Slot URLs carry no date, so the API cannot run out of coverage.
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

SCHEMA_VERSION = "3.0"

#: Levels from easiest to hardest. A learner's deck is every level up to and
#: including the one they choose, so N3 means N5 + N4 + N3.
LEVEL_ORDER = ("N5", "N4", "N3", "N2", "N1")

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
    recommended_bytes: int = 2048
    hard_limit_bytes: int = 8192
    minify: bool = True
    status: str = "production"
    minimum_entries_per_level: int = 1
    #: How long one card stays up, and how many slot files exist per level.
    slot_seconds: int = 600
    slot_count: int = 4096

    @staticmethod
    def load(path: Path) -> "BuildConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        payload = raw.get("payload", {})
        slots = raw.get("slots", {})
        return BuildConfig(
            recommended_bytes=int(payload.get("recommended_bytes", 2048)),
            hard_limit_bytes=int(payload.get("hard_limit_bytes", 8192)),
            minify=bool(payload.get("minify", True)),
            status=str(raw.get("status", "production")),
            minimum_entries_per_level=int(raw.get("minimum_entries_per_level", 1)),
            slot_seconds=int(slots.get("seconds", 600)),
            slot_count=int(slots.get("count", 4096)),
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


def cumulative_entries(
    corpus: dict[str, list[VocabularyEntry]], level: str
) -> list[VocabularyEntry]:
    """Active entries for *level* and every easier level, sorted by ID.

    Selecting N3 gives N5, N4 and N3 material together. Learners revise
    downwards as well as forwards, and a deck limited to one band drops
    everything already learned the moment the level is raised.
    """
    wanted = LEVEL_ORDER[: LEVEL_ORDER.index(level_display(level)) + 1]
    entries = [
        entry
        for band in wanted
        for entry in corpus.get(level_key(band), [])
        if entry.is_active
    ]
    return sorted(entries, key=lambda e: e.id)


# --------------------------------------------------------------------------
# Payload construction
# --------------------------------------------------------------------------


def build_card(
    entry: VocabularyEntry,
    level: str,
    slot: int,
    position: int,
    pool: int,
    dataset_version: str,
    selection_version: str,
    slot_seconds: int,
    slot_count: int,
) -> dict[str, Any]:
    """One slot's payload: exactly the card to show. No HTML, no markup."""
    word: dict[str, Any] = {
        "id": entry.id,
        "surface": entry.surface,
        "reading": entry.reading,
        "ruby_segments": [s.to_json() for s in entry.ruby_segments],
        "display_gloss": entry.display_gloss,
        "level": entry.jlpt.level,
    }
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
        "level": level,
        "level_display": level_display(level),
        "dataset_version": dataset_version,
        "selection_version": selection_version,
        "slot": {
            "index": slot,
            "seconds": slot_seconds,
            "count": slot_count,
        },
        "sequence": {"position": position, "pool": pool},
        "word": word,
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
    entry_counts: dict[str, int]
    pool_counts: dict[str, int]
    file_counts: dict[str, int]
    dataset_version: str
    largest_payload: int
    oversized: list[str]
    slot_seconds: int
    slot_count: int


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

    api_dir = output_dir / "api" / "v1"
    card_dir = api_dir / "card"
    card_dir.mkdir(parents=True, exist_ok=True)

    entry_counts: dict[str, int] = {}
    pool_counts: dict[str, int] = {}
    file_counts: dict[str, int] = {}
    largest = 0
    oversized: list[str] = []

    # Where in the rotation this build starts. Advancing it with the calendar
    # means successive rebuilds carry on through the corpus rather than
    # replaying the same slice, which matters for the larger levels where the
    # pool is bigger than the slot space.
    build_offset = (today - selection_config.epoch_date).days

    for level in LEVELS:
        key = level_key(level)
        # The learner's pool is this level plus every easier one.
        active = cumulative_entries(corpus, key)
        own = sum(1 for e in corpus.get(key, []) if e.is_active)
        entry_counts[key] = own
        pool_counts[key] = len(active)
        if not active:
            raise ValueError(f"level {key} has no active entries; cannot build site")
        if own < build_config.minimum_entries_per_level:
            raise ValueError(
                f"level {key} has {own} active entries of its own, minimum is "
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

        level_dir = card_dir / key
        level_dir.mkdir(parents=True, exist_ok=True)

        for slot in range(build_config.slot_count):
            selection = scheduler.at_position(build_offset + slot)
            payload = build_card(
                by_id[selection.entry_id],
                key,
                slot,
                selection.position,
                selection.total,
                dataset_version,
                selection_config.selection_version,
                build_config.slot_seconds,
                build_config.slot_count,
            )
            text = dump_payload(payload, build_config.minify)
            size = len(text.encode("utf-8"))
            largest = max(largest, size)
            if size > build_config.hard_limit_bytes:
                oversized.append(f"{key}/{slot} ({size} bytes)")
            (level_dir / f"{slot}.json").write_text(text, encoding="utf-8")

        file_counts[key] = build_config.slot_count
        # For inspection only; the plugin always requests a slot path.
        (level_dir / "sample.json").write_text(
            dump_payload(
                build_card(
                    by_id[scheduler.at_position(build_offset).entry_id],
                    key, 0, scheduler.at_position(build_offset).position,
                    scheduler.at_position(build_offset).total,
                    dataset_version, selection_config.selection_version,
                    build_config.slot_seconds, build_config.slot_count,
                ),
                minify=False,
            ),
            encoding="utf-8",
        )

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
        "active_entries": entry_counts,
        "deck_pool": pool_counts,
        "generated_files": file_counts,
        "slots": {
            "seconds": build_config.slot_seconds,
            "count": build_config.slot_count,
            "cycle_days": round(
                build_config.slot_count * build_config.slot_seconds / 86400, 1
            ),
            "cumulative_levels": True,
        },
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
        "total_active_entries": sum(entry_counts.values()),
        "deck_pool": pool_counts,
        "slots": manifest["slots"],
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
        entry_counts=entry_counts,
        pool_counts=pool_counts,
        file_counts=file_counts,
        dataset_version=dataset_version,
        largest_payload=largest,
        oversized=oversized,
        slot_seconds=build_config.slot_seconds,
        slot_count=build_config.slot_count,
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
        "<tr><td><code>{key}</code></td><td>{own}</td><td>{pool}</td>"
        '<td><a href="api/v1/card/{key}/0.json">slot 0</a></td>'
        '<td><a href="api/v1/card/{key}/sample.json">sample</a></td></tr>'.format(
            key=key,
            own=manifest["active_entries"].get(key, 0),
            pool=manifest["deck_pool"].get(key, 0),
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

<p>Each level and time slot resolves to one small JSON document holding a
single card. The plugin builds the path from its selected level and the
current time, so the card changes every
<code>" + str(manifest["slots"]["seconds"]) + "</code> seconds. A level includes every easier level, so
N3 draws on N5, N4 and N3 together.</p>

<table>
<thead><tr><th>Level</th><th>Own words</th><th>Deck pool</th><th>Slot 0</th><th>Sample</th></tr></thead>
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
<li>Slots: <code>{manifest["slots"]["count"]}</code> per level, one every
    <code>{manifest["slots"]["seconds"]}s</code> — a
    <code>{manifest["slots"]["cycle_days"]}</code>-day cycle</li>
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

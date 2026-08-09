"""Production adapter: JLPT levels joined onto JMdict, with real furigana.

Three files are combined, all of them downloaded beforehand by
``scripts/fetch_sources.py`` into ``data/raw`` — this adapter never touches the
network:

``jlpt-waller`` (``original_data/n*.csv`` from ``stephenmk/yomitan-jlpt-vocab``)
    Community-estimated JLPT level per word. Crucially it carries a
    ``jmdict_seq`` column, so levels join onto JMdict on the canonical entry
    identifier rather than on fuzzy surface strings.

``jmdict`` (``jmdict-examples-eng`` from ``scriptin/jmdict-simplified``)
    Readings, glosses, parts of speech, and Tatoeba example sentences already
    aligned to a specific sense.

``jmdict-furigana`` (``JmdictFurigana.txt`` from ``Doublevil/JmdictFurigana``)
    Hand-checked ruby segmentation keyed on surface plus reading, including
    jukujikun such as 明白/あからさま that no aligner could derive.

The level list decides which words exist and how they are spelled; JMdict only
enriches them. That ordering matters, because the spelling a learner is taught
should be the one on the level list.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from ..models import RubySegment
from ..normalise import clean_text, display_width
from .base import RawRecord

LEVEL_FILES = ("n5", "n4", "n3", "n2", "n1")

#: JMdict part-of-speech codes worth spelling out. Anything unmapped is kept
#: verbatim; the field is metadata and is never rendered on screen.
POS_NAMES = {
    "n": "noun",
    "adj-i": "i-adjective",
    "adj-na": "na-adjective",
    "adj-no": "no-adjective",
    "adv": "adverb",
    "vs": "suru verb",
    "vs-i": "suru verb",
    "vk": "kuru verb",
    "vi": "intransitive verb",
    "vt": "transitive verb",
    "v1": "ichidan verb",
    "v5u": "godan verb",
    "v5k": "godan verb",
    "v5g": "godan verb",
    "v5s": "godan verb",
    "v5t": "godan verb",
    "v5n": "godan verb",
    "v5b": "godan verb",
    "v5m": "godan verb",
    "v5r": "godan verb",
    "v5k-s": "godan verb",
    "v5aru": "godan verb",
    "exp": "expression",
    "int": "interjection",
    "conj": "conjunction",
    "pn": "pronoun",
    "prt": "particle",
    "pref": "prefix",
    "suf": "suffix",
    "ctr": "counter",
    "num": "numeric",
    "aux-v": "auxiliary verb",
    "aux-adj": "auxiliary adjective",
}

#: Example-sentence preferences. Shorter sentences read far better on a
#: 800x480 panel, so a comfortable one is preferred over a merely legal one.
EXAMPLE_PREFERRED_WIDTH = 34.0
EXAMPLE_MAX_WIDTH = 44.0
EXAMPLE_HARD_MAX_CHARS = 80
EXAMPLE_EN_PREFERRED_CHARS = 100
EXAMPLE_EN_HARD_MAX_CHARS = 160


# --------------------------------------------------------------------------
# JmdictFurigana
# --------------------------------------------------------------------------


def parse_furigana_segments(surface: str, spec: str) -> list[RubySegment] | None:
    """Parse one JmdictFurigana segment specification.

    The third field of each line is a semicolon-separated list of
    ``start[-end]:kana`` items. Indices are zero-based character offsets into
    the surface and are inclusive at both ends. Only ruby-bearing positions
    appear; everything omitted is kana that already reads itself.

    ``阿吽の呼吸|あうんのこきゅう|0:あ;1:うん;3:こ;4:きゅう`` therefore means
    阿=あ, 吽=うん, の plain, 呼=こ, 吸=きゅう.
    """
    covered: dict[int, tuple[int, str]] = {}
    for item in spec.split(";"):
        item = item.strip()
        if not item:
            continue
        location, _, kana = item.partition(":")
        if not kana:
            return None
        if "-" in location:
            start_text, _, end_text = location.partition("-")
        else:
            start_text = end_text = location
        try:
            start, end = int(start_text), int(end_text)
        except ValueError:
            return None
        if not (0 <= start <= end < len(surface)):
            return None
        covered[start] = (end, kana)

    segments: list[RubySegment] = []
    index = 0
    while index < len(surface):
        if index in covered:
            end, kana = covered[index]
            segments.append(RubySegment(base=surface[index : end + 1], reading=kana))
            index = end + 1
        else:
            # Accumulate the plain run up to the next ruby span.
            start = index
            while index < len(surface) and index not in covered:
                index += 1
            segments.append(RubySegment(base=surface[start:index], reading=None))
    return segments or None


def load_furigana(path: Path) -> dict[tuple[str, str], list[RubySegment]]:
    """Load JmdictFurigana.txt into a ``(surface, reading)`` lookup.

    The file carries a UTF-8 BOM, hence ``utf-8-sig``: reading it as plain
    UTF-8 corrupts the very first entry.
    """
    table: dict[tuple[str, str], list[RubySegment]] = {}
    with path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("|")
            if len(parts) != 3:
                continue
            surface, reading, spec = parts
            segments = parse_furigana_segments(surface, spec)
            if segments:
                table[(surface, reading)] = segments
    return table


# --------------------------------------------------------------------------
# JLPT level list
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LevelRow:
    jmdict_seq: str
    kana: str
    kanji: str
    definition: str
    level: str

    @property
    def surface(self) -> str:
        """Kana-only vocabulary leaves the kanji column empty."""
        return self.kanji or self.kana


def load_levels(directory: Path) -> list[LevelRow]:
    """Read the five ``n*.csv`` level files."""
    rows: list[LevelRow] = []
    for key in LEVEL_FILES:
        path = directory / f"{key}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing JLPT level file {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                kana = clean_text(raw.get("kana", ""))
                if not kana:
                    continue
                rows.append(
                    LevelRow(
                        jmdict_seq=clean_text(raw.get("jmdict_seq", "")),
                        kana=kana,
                        kanji=clean_text(raw.get("kanji", "")),
                        definition=clean_text(raw.get("waller_definition", "")),
                        level=key.upper(),
                    )
                )
    return rows


# --------------------------------------------------------------------------
# JMdict
# --------------------------------------------------------------------------


def _iter_jmdict_words(path: Path) -> Iterator[dict[str, Any]]:
    """Yield JMdict word objects, streaming when possible.

    The examples build is around 129 MB of JSON. ``ijson`` keeps that off the
    heap; without it we fall back to a plain load, which works but is hungry.
    """
    try:
        import ijson  # type: ignore
    except ImportError:
        document = json.loads(path.read_text(encoding="utf-8"))
        yield from document.get("words", [])
        return

    with path.open("rb") as handle:
        yield from ijson.items(handle, "words.item")


def _pick_example(word: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Choose the most screen-friendly Japanese/English example pair.

    Returns ``(ja, en, focus_form, tatoeba_id)``. Preference is for the
    shortest sentence that still reads naturally, because the panel has room
    for roughly one comfortable line of Japanese.
    """
    candidates: list[tuple[float, str, str, str, str]] = []
    for sense in word.get("sense", []):
        for example in sense.get("examples", []):
            sentences = {s.get("lang"): s.get("text", "") for s in example.get("sentences", [])}
            ja = clean_text(sentences.get("jpn", ""))
            en = clean_text(sentences.get("eng", ""))
            if not ja or not en:
                continue
            if len(ja) > EXAMPLE_HARD_MAX_CHARS or len(en) > EXAMPLE_EN_HARD_MAX_CHARS:
                continue
            width = display_width(ja)
            if width > EXAMPLE_MAX_WIDTH:
                continue
            focus = clean_text(example.get("text", ""))
            source = example.get("source", {}) or {}
            tatoeba_id = str(source.get("value", "")) if source.get("type") == "tatoeba" else ""
            # Sort key: comfortable sentences first, then shortest. A long
            # English translation is penalised too, since it has to fit under
            # the Japanese when the optional translation is switched on.
            penalty = 0.0 if width <= EXAMPLE_PREFERRED_WIDTH else 1.0
            if len(en) > EXAMPLE_EN_PREFERRED_CHARS:
                penalty += 0.5
            candidates.append((penalty + width / 100.0, ja, en, focus, tatoeba_id))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    _, ja, en, focus, tatoeba_id = candidates[0]
    return ja, en, focus, tatoeba_id


def load_jmdict(
    path: Path, wanted_ids: set[str]
) -> dict[str, dict[str, Any]]:
    """Extract glosses, parts of speech and one example for the wanted IDs."""
    result: dict[str, dict[str, Any]] = {}
    for word in _iter_jmdict_words(path):
        word_id = str(word.get("id", ""))
        if word_id not in wanted_ids:
            continue

        glosses: list[str] = []
        pos: list[str] = []
        for sense in word.get("sense", []):
            for gloss in sense.get("gloss", []):
                if gloss.get("lang") == "eng":
                    text = clean_text(gloss.get("text", ""))
                    if text and text not in glosses:
                        glosses.append(text)
            for code in sense.get("partOfSpeech", []):
                name = POS_NAMES.get(code, code)
                if name not in pos:
                    pos.append(name)
            if glosses:
                # Only the first sense that actually produced glosses is used;
                # a screen gloss must not become a dictionary dump.
                break

        result[word_id] = {
            "glosses": glosses[:4],
            "part_of_speech": pos[:3],
            "example": _pick_example(word),
            "kana": [k.get("text", "") for k in word.get("kana", [])],
            "kanji": [k.get("text", "") for k in word.get("kanji", [])],
        }
    return result


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------


class JlptJmdictSource:
    """Composite adapter producing the production corpus."""

    def __init__(
        self,
        source_id: str = "jlpt-waller",
        levels_dir: Path = Path("data/raw/jlpt"),
        jmdict_path: Path = Path("data/raw/jmdict-examples-eng.json"),
        furigana_path: Path = Path("data/raw/JmdictFurigana.txt"),
        jmdict_source_id: str = "jmdict",
        furigana_source_id: str = "jmdict-furigana",
        example_source_id: str = "tatoeba",
    ) -> None:
        self.source_id = source_id
        self.levels_dir = Path(levels_dir)
        self.jmdict_path = Path(jmdict_path)
        self.furigana_path = Path(furigana_path)
        self.jmdict_source_id = jmdict_source_id
        self.furigana_source_id = furigana_source_id
        self.example_source_id = example_source_id
        #: Populated during :meth:`read` for the import report.
        self.stats: dict[str, int] = {}

    def read(self) -> Iterator[RawRecord]:
        rows = load_levels(self.levels_dir)
        furigana = load_furigana(self.furigana_path)
        wanted = {r.jmdict_seq for r in rows if r.jmdict_seq}
        jmdict = load_jmdict(self.jmdict_path, wanted)

        stats = {
            "level_rows": len(rows),
            "jmdict_matched": 0,
            "furigana_matched": 0,
            "with_example": 0,
            "skipped_no_gloss": 0,
        }

        for row in rows:
            entry = jmdict.get(row.jmdict_seq) or {}
            if entry:
                stats["jmdict_matched"] += 1

            glosses = list(entry.get("glosses") or [])
            if not glosses and row.definition:
                # Fall back to the level list's own short definition so that a
                # word dropped from JMdict is not silently lost.
                glosses = [row.definition]
            if not glosses:
                stats["skipped_no_gloss"] += 1
                continue

            segments = furigana.get((row.surface, row.kana))
            if segments:
                stats["furigana_matched"] += 1

            example = entry.get("example")
            example_ja = example_en = focus = example_ref = None
            if example:
                example_ja, example_en, focus, tatoeba_id = example
                example_ref = (
                    f"{self.example_source_id}:{tatoeba_id}"
                    if tatoeba_id
                    else self.example_source_id
                )
                stats["with_example"] += 1

            record = RawRecord(
                source_id=self.source_id,
                surface=row.surface,
                reading=row.kana,
                level=row.level,
                glosses=glosses,
                source_entry_id=row.jmdict_seq or None,
                part_of_speech=list(entry.get("part_of_speech") or []),
                example_ja=example_ja,
                example_en=example_en,
                example_source_ref=example_ref,
                ruby_segments=segments,
                extra={
                    "waller_definition": row.definition,
                    "focus_form": focus,
                    "jmdict_seq": row.jmdict_seq,
                    "has_jmdict": bool(entry),
                    "has_furigana": bool(segments),
                },
            )
            yield record

        self.stats = stats

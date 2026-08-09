"""Conservative furigana alignment.

The renderer must never guess furigana at screen-render time, so this module
resolves the final ruby segmentation once, during import, and refuses to guess
when the alignment is not forced by the data.

The strategy is deliberately unclever: split the surface into alternating
*literal* runs (kana, which we can read directly) and *ruby-candidate* runs
(kanji and friends, which we cannot). Anchor the literal runs inside the
complete reading, and whatever falls between the anchors belongs to the
neighbouring ruby-candidate run. A contiguous kanji compound is kept as a
single ruby group, because splitting ``学校`` into ``学``/``校`` requires
per-kanji reading knowledge that the surface plus reading simply does not
contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import RubySegment
from .normalise import (
    NON_RUBY_PUNCTUATION,
    clean_text,
    is_kana,
    nfc,
    to_hiragana,
)

#: Status values for an alignment attempt.
OK = "ok"
NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class AlignmentResult:
    status: str
    segments: list[RubySegment]
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == OK


@dataclass(frozen=True)
class _Run:
    text: str
    is_literal: bool


def _is_literal_char(ch: str) -> bool:
    """True when the character carries its own pronunciation on screen.

    Kana is literal. Punctuation and spacing are treated as literal too: they
    are never given ruby, and they do not appear in a kana reading, so they
    are handled separately by :func:`_split_runs`.
    """
    return is_kana(ch) or ch in NON_RUBY_PUNCTUATION


def _split_runs(surface: str) -> list[_Run]:
    """Split *surface* into alternating literal and ruby-candidate runs."""
    runs: list[_Run] = []
    for ch in surface:
        literal = _is_literal_char(ch)
        if runs and runs[-1].is_literal == literal:
            runs[-1] = _Run(runs[-1].text + ch, literal)
        else:
            runs.append(_Run(ch, literal))
    return runs


def _anchor_text(run_text: str) -> str:
    """The comparison form of a literal run, with unpronounced marks dropped.

    Punctuation inside the surface does not appear in the kana reading, so it
    must not be part of the anchor we search for.
    """
    return "".join(
        to_hiragana(ch) for ch in run_text if ch not in NON_RUBY_PUNCTUATION
    )


def align(surface: str, reading: str) -> AlignmentResult:
    """Align *reading* onto *surface*, returning ruby segments or a review flag.

    The result is only ``ok`` when the alignment is unambiguous: a greedy and
    a lazy match of the same pattern must agree. Where they disagree the entry
    is sent for human review rather than guessed at.
    """
    surface = clean_text(surface).replace(" ", "")
    reading_clean = clean_text(reading).replace(" ", "")

    if not surface:
        return AlignmentResult(NEEDS_REVIEW, [], "empty surface")
    if not reading_clean:
        return AlignmentResult(NEEDS_REVIEW, [], "empty reading")

    # ``to_hiragana`` is a one-to-one character mapping, so offsets into the
    # comparison form index the original reading exactly. That lets us slice
    # readings out of the source string and preserve its script.
    reading_cmp = to_hiragana(reading_clean)
    assert len(reading_cmp) == len(reading_clean)

    runs = _split_runs(surface)
    ruby_runs = [r for r in runs if not r.is_literal]

    if not ruby_runs:
        # Nothing can carry ruby. The surface must simply *be* the reading.
        if _anchor_text(surface) != reading_cmp:
            return AlignmentResult(
                NEEDS_REVIEW,
                [],
                f"kana-only surface {surface!r} does not match reading {reading_clean!r}",
            )
        return AlignmentResult(OK, [RubySegment(base=surface, reading=None)])

    # Build one regex over the whole reading: literal runs become anchors,
    # ruby-candidate runs become capture groups of at least one character.
    def build_pattern(lazy: bool) -> str:
        quantifier = "+?" if lazy else "+"
        parts = ["^"]
        for run in runs:
            if run.is_literal:
                parts.append(re.escape(_anchor_text(run.text)))
            else:
                parts.append(f"(.{quantifier})")
        parts.append("$")
        return "".join(parts)

    lazy_match = re.match(build_pattern(True), reading_cmp)
    greedy_match = re.match(build_pattern(False), reading_cmp)

    if lazy_match is None or greedy_match is None:
        return AlignmentResult(
            NEEDS_REVIEW,
            [],
            f"reading {reading_clean!r} cannot be aligned to surface {surface!r}",
        )

    if len(ruby_runs) > 1 and lazy_match.groups() != greedy_match.groups():
        return AlignmentResult(
            NEEDS_REVIEW,
            [],
            "ambiguous alignment: greedy and lazy matches disagree "
            f"({greedy_match.groups()} vs {lazy_match.groups()})",
        )

    segments: list[RubySegment] = []
    group_index = 0
    for run in runs:
        if run.is_literal:
            segments.append(RubySegment(base=run.text, reading=None))
            continue
        group_index += 1
        start, end = lazy_match.span(group_index)
        # Slice the *original* reading so katakana source readings survive.
        run_reading = reading_clean[start:end]
        if not run_reading:
            return AlignmentResult(
                NEEDS_REVIEW, [], f"zero-length reading for run {run.text!r}"
            )
        segments.append(RubySegment(base=run.text, reading=run_reading))

    return AlignmentResult(OK, _merge_plain_segments(segments))


def _merge_plain_segments(segments: list[RubySegment]) -> list[RubySegment]:
    """Collapse adjacent reading-less segments into one plain run."""
    merged: list[RubySegment] = []
    for seg in segments:
        if seg.reading is None and merged and merged[-1].reading is None:
            merged[-1] = RubySegment(base=merged[-1].base + seg.base, reading=None)
        else:
            merged.append(seg)
    return merged


def segments_surface(segments: list[RubySegment]) -> str:
    """Concatenate every segment base; must equal the entry's surface."""
    return "".join(s.base for s in segments)


def segments_reading(segments: list[RubySegment]) -> str:
    """Reconstruct the full reading in comparison form.

    Reading-less segments contribute their own kana; ruby segments contribute
    their reading. Punctuation is dropped because it never appears in a kana
    reading.
    """
    parts = []
    for seg in segments:
        source = seg.reading if seg.reading is not None else seg.base
        parts.append(_anchor_text(source) if seg.reading is None else to_hiragana(source))
    return "".join(parts)


def check_segments(
    surface: str, reading: str, segments: list[RubySegment]
) -> list[str]:
    """Return a list of human-readable problems with *segments*.

    An empty list means the segmentation is renderable and self-consistent.
    """
    problems: list[str] = []
    surface_n = nfc(clean_text(surface)).replace(" ", "")
    reading_n = to_hiragana(clean_text(reading)).replace(" ", "")

    if not segments:
        return ["no ruby segments"]

    rebuilt_surface = segments_surface(segments)
    if rebuilt_surface != surface_n:
        problems.append(
            f"segment bases {rebuilt_surface!r} do not concatenate to surface {surface_n!r}"
        )

    rebuilt_reading = segments_reading(segments)
    if rebuilt_reading != reading_n:
        problems.append(
            f"segments reconstruct reading {rebuilt_reading!r}, expected {reading_n!r}"
        )

    for seg in segments:
        if not seg.base:
            problems.append("empty segment base")
        if seg.reading is not None and not seg.reading.strip():
            problems.append(f"empty ruby reading on segment {seg.base!r}")
        if seg.reading is not None and to_hiragana(seg.reading) == to_hiragana(seg.base):
            problems.append(
                f"redundant ruby on segment {seg.base!r}: reading equals base"
            )
        if seg.reading is None and any(not _is_literal_char(ch) for ch in seg.base):
            problems.append(
                f"segment {seg.base!r} contains non-kana characters but has no reading"
            )
        if seg.reading is not None and any(not is_kana(ch) for ch in seg.reading):
            problems.append(
                f"ruby reading {seg.reading!r} on {seg.base!r} is not pure kana"
            )
        if seg.reading is not None and seg.base and (
            _is_literal_char(seg.base[0]) or _is_literal_char(seg.base[-1])
        ):
            # Okurigana belongs beside the ruby group, not underneath it.
            # Ruby over 食べる as a whole would put a reading above べる,
            # which the learner can already read.
            problems.append(
                f"ruby segment {seg.base!r} starts or ends with kana; "
                "split the okurigana into a plain segment"
            )

    return problems


def resolve(
    entry_id: str,
    surface: str,
    reading: str,
    existing: list[RubySegment] | None = None,
    overrides: dict[str, list[RubySegment]] | None = None,
) -> AlignmentResult:
    """Resolve the final segmentation for one entry.

    Precedence: explicit override, then a segmentation supplied by the source,
    then conservative automatic alignment.
    """
    overrides = overrides or {}

    if entry_id in overrides:
        segments = overrides[entry_id]
        problems = check_segments(surface, reading, segments)
        if problems:
            return AlignmentResult(
                NEEDS_REVIEW, segments, "invalid override: " + "; ".join(problems)
            )
        return AlignmentResult(OK, segments)

    if existing:
        problems = check_segments(surface, reading, existing)
        if not problems:
            return AlignmentResult(OK, existing)
        # Fall through to the aligner: a bad source segmentation should not be
        # fatal if the surface and reading alone are unambiguous.

    return align(surface, reading)

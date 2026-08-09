"""Import-stage decisions: gloss selection and entry construction."""

from __future__ import annotations

import pytest

from kotoba.importer import (
    DISPLAY_GLOSS_HARD_MAX,
    DISPLAY_GLOSS_TARGET,
    choose_display_gloss,
)


class TestChooseDisplayGloss:
    """The first gloss wins.

    JMdict orders glosses by prominence, so the leading one is the meaning to
    teach. Picking the shortest instead is how 混雑 became "crush" and
    いらっしゃい became "go" — the opposite of what it means.
    """

    @pytest.mark.parametrize(
        "glosses,expected",
        [
            (["congestion", "crush", "crowding", "jam"], "congestion"),
            (["come", "go", "stay"], "come"),
            (["properly", "accurately", "exactly"], "properly"),
            (["frequently", "repeatedly", "often"], "frequently"),
            (["continuously", "the whole time", "all the way"], "continuously"),
            (["chattering", "talk", "idle talk"], "chattering"),
        ],
    )
    def test_prefers_the_primary_sense_over_a_shorter_one(self, glosses, expected):
        assert choose_display_gloss(glosses) == expected

    def test_strips_a_trailing_qualifier(self):
        assert choose_display_gloss(["soundly (sleeping)"]) == "soundly"
        assert choose_display_gloss(["to eat (colloquial)"]) == "to eat"

    def test_keeps_a_leading_bracket(self):
        """"(flower) vase" and "(be) still" lose their meaning if trimmed."""
        assert choose_display_gloss(["(flower) vase"]) == "(flower) vase"
        assert choose_display_gloss(["(be) still"]) == "(be) still"

    def test_does_not_strip_when_little_would_remain(self):
        assert choose_display_gloss(["to (do)"]) == "to (do)"

    def test_falls_back_to_a_shorter_gloss_when_the_first_will_not_fit(self):
        long_first = "a " + "very " * 20 + "long gloss"
        assert len(long_first) > DISPLAY_GLOSS_TARGET
        assert choose_display_gloss([long_first, "brief"]) == "brief"

    def test_uses_two_lines_rather_than_truncating(self):
        """Between the recommended and hard limits, let it wrap."""
        gloss = "local specialty or souvenir bought as a gift while travelling"
        assert DISPLAY_GLOSS_TARGET < len(gloss) <= DISPLAY_GLOSS_HARD_MAX
        assert choose_display_gloss([gloss]) == gloss

    def test_takes_the_first_clause_of_a_comma_list(self):
        """Some JMdict glosses are a thesaurus crammed into one string."""
        gloss = ("wound, injury, hurt, cut, gash, bruise, scratch, scar, "
                 "weak point")
        assert choose_display_gloss([gloss]) == "wound"

    def test_strips_a_trailing_qualifier_even_with_a_leading_bracket(self):
        gloss = ("(East Asian) rainy season "
                 "(in Japan, usu. from early June to mid-July)")
        assert choose_display_gloss([gloss]) == "(East Asian) rainy season"

    def test_truncates_only_beyond_the_hard_limit(self):
        result = choose_display_gloss(["x" * 200])
        assert len(result) <= DISPLAY_GLOSS_HARD_MAX
        assert result.endswith("…")

    def test_ignores_blank_glosses(self):
        assert choose_display_gloss(["", "   ", "real"]) == "real"

    def test_returns_empty_for_no_usable_glosses(self):
        assert choose_display_gloss([]) == ""
        assert choose_display_gloss(["", "  "]) == ""

    def test_trims_trailing_punctuation(self):
        assert choose_display_gloss(["to run,"]) == "to run"


def test_no_shipped_gloss_is_truncated():
    """An ellipsis mid-word looks broken on a wall display."""
    import glob
    import json

    truncated = [
        e["surface"]
        for path in glob.glob("data/vocabulary/*.json")
        for e in json.load(open(path, encoding="utf-8"))
        if e["display_gloss"].endswith("…")
    ]
    assert truncated == [], f"truncated glosses: {truncated[:10]}"


def test_the_shipped_corpus_uses_primary_glosses():
    """Regression guard against the shortest-gloss rule creeping back in."""
    import glob
    import json

    mismatches = []
    for path in glob.glob("data/vocabulary/*.json"):
        for entry in json.load(open(path, encoding="utf-8")):
            glosses = entry.get("glosses") or []
            if not glosses:
                continue
            expected = choose_display_gloss(glosses)
            if expected and entry["display_gloss"] != expected:
                mismatches.append((entry["surface"], entry["display_gloss"], expected))

    assert not mismatches, (
        f"{len(mismatches)} entries disagree with the gloss rule; "
        f"run `make import`. First few: {mismatches[:5]}"
    )

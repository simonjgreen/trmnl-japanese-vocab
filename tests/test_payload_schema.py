"""The slot card payload contract, and the visual fixtures that model it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kotoba.validation import _validator, load_schema

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"

REQUIRED_FIXTURES = (
    "full_reference",      # the spec's reference word
    "kana_only",           # no ruby at all
    "compound_reading",    # grouped compound
    "irregular_reading",   # jukujikun
    "long_word",
    "long_example",
    "long_gloss",
    "missing_optional_fields",
    "with_translation",
    "with_progress",
    "empty_state",
    "level_strip_middle",
    "xlong_word",
    "wide_ruby",
    "short_word",
)


@pytest.fixture
def validator(schemas_dir):
    return _validator(load_schema("card-payload.schema.json", schemas_dir), schemas_dir)


def payload(name: str) -> dict:
    doc = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def test_every_required_fixture_exists():
    missing = [n for n in REQUIRED_FIXTURES if not (FIXTURES / f"{n}.json").is_file()]
    assert missing == []


def test_a_fixture_exists_for_every_level():
    for level in ("n5", "n4", "n3", "n2", "n1"):
        assert (FIXTURES / f"level_{level}.json").is_file()


@pytest.mark.parametrize("name", [n for n in REQUIRED_FIXTURES if n != "empty_state"])
def test_fixtures_satisfy_the_payload_schema(name, validator):
    errors = list(validator.iter_errors(payload(name)))
    assert errors == [], [e.message for e in errors]


def test_empty_state_fixture_deliberately_has_no_card(validator):
    doc = payload("empty_state")
    assert "word" not in doc
    # It is intentionally not schema-valid: it models a payload the renderer
    # must survive, not one the builder would ever produce.
    assert list(validator.iter_errors(doc))


def first_card(name: str) -> dict:
    return payload(name)["word"]


LEVEL_ORDER = ("N5", "N4", "N3", "N2", "N1")


def test_every_card_sits_within_its_deck_level():
    """A card must never come from a level harder than the deck's own.

    This is what the title-bar strip depends on: it lists N5 up to the deck
    level and underlines the card's, so a card from outside that range would
    have nothing to underline.
    """
    offenders = []
    for path in FIXTURES.glob("*.json"):
        doc = payload(path.stem)
        card = doc.get("word")
        if not card:
            continue
        limit = LEVEL_ORDER.index(doc["level_display"])
        if LEVEL_ORDER.index(card["level"]) > limit:
            offenders.append((path.stem, card["surface"], card["level"]))
    assert offenders == [], offenders


def test_the_middle_level_fixture_underlines_a_middle_band():
    """Guards the interesting case: not the first or last level in the strip."""
    doc = payload("level_strip_middle")
    assert doc["level_display"] == "N3"
    assert doc["word"]["level"] == "N4"


def test_reference_fixture_matches_the_specified_segmentation():
    word = first_card("full_reference")
    assert word["surface"] == "取り除く"
    assert word["reading"] == "とりのぞく"
    assert word["ruby_segments"] == [
        {"base": "取", "reading": "と"},
        {"base": "り", "reading": None},
        {"base": "除", "reading": "のぞ"},
        {"base": "く", "reading": None},
    ]
    assert word["display_gloss"] == "eliminate"


def test_kana_only_fixture_has_no_ruby():
    word = first_card("kana_only")
    assert all(s["reading"] is None for s in word["ruby_segments"])


class TestSchemaRejects:
    def test_a_bad_level(self, validator):
        doc = payload("full_reference")
        doc["level"] = "n9"
        assert list(validator.iter_errors(doc))

    def test_a_bad_date_format(self, validator):
        doc = payload("full_reference")
        doc["date"] = "09-08-2026"
        assert list(validator.iter_errors(doc))

    def test_an_unknown_word_size(self, validator):
        doc = payload("full_reference")
        doc["word"]["display"]["word_size"] = "enormous"
        assert list(validator.iter_errors(doc))

    def test_an_empty_ruby_segment_list(self, validator):
        doc = payload("full_reference")
        doc["word"]["ruby_segments"] = []
        assert list(validator.iter_errors(doc))

    def test_an_overlong_gloss(self, validator):
        doc = payload("full_reference")
        doc["word"]["display_gloss"] = "x" * 100
        assert list(validator.iter_errors(doc))

    def test_an_unexpected_extra_property(self, validator):
        doc = payload("full_reference")
        doc["word"]["html"] = "<b>no</b>"
        assert list(validator.iter_errors(doc))

    def test_a_missing_slot_block(self, validator):
        doc = payload("full_reference")
        del doc["slot"]
        assert list(validator.iter_errors(doc))

    def test_a_missing_word(self, validator):
        doc = payload("full_reference")
        del doc["word"]
        assert list(validator.iter_errors(doc))

    def test_a_card_without_a_level(self, validator):
        doc = payload("full_reference")
        del doc["word"]["level"]
        assert list(validator.iter_errors(doc))


def test_no_fixture_contains_markup():
    """Payloads carry data, never HTML — the renderer escapes, but still."""
    for path in FIXTURES.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "<" not in text and ">" not in text, path.name

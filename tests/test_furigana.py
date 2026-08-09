"""Furigana alignment, validation and override precedence."""

from __future__ import annotations

import pytest

from kotoba.furigana import (
    NEEDS_REVIEW,
    OK,
    align,
    check_segments,
    resolve,
    segments_reading,
    segments_surface,
)
from kotoba.models import RubySegment
from kotoba.normalise import nfc


def seg(result):
    return [(s.base, s.reading) for s in result.segments]


@pytest.mark.parametrize(
    "surface,reading,expected",
    [
        # Mixed kanji and okurigana.
        ("食べる", "たべる", [("食", "た"), ("べる", None)]),
        # The spec's reference word: two separated kanji groups.
        ("取り除く", "とりのぞく", [("取", "と"), ("り", None), ("除", "のぞ"), ("く", None)]),
        ("申し込む", "もうしこむ", [("申", "もう"), ("し", None), ("込", "こ"), ("む", None)]),
        # A compound whose reading cannot be split per character stays grouped.
        ("学校", "がっこう", [("学校", "がっこう")]),
        # Irregular (jukujikun) reading, likewise grouped.
        ("今日", "きょう", [("今日", "きょう")]),
        ("大人", "おとな", [("大人", "おとな")]),
        # Kana only: one plain run, and crucially no empty <rt>.
        ("ありがとう", "ありがとう", [("ありがとう", None)]),
        # Katakana, including the prolonged sound mark.
        ("コーヒー", "コーヒー", [("コーヒー", None)]),
        ("ラーメン", "らーめん", [("ラーメン", None)]),
        # Mixed scripts in the okurigana run.
        ("消しゴム", "けしごむ", [("消", "け"), ("しゴム", None)]),
        # Kanji iteration mark.
        ("時々", "ときどき", [("時々", "ときどき")]),
        # Repeated structure must not confuse the anchors.
        ("一つ一つ", "ひとつひとつ", [("一", "ひと"), ("つ", None), ("一", "ひと"), ("つ", None)]),
        # Small tsu inside the reading.
        ("引っ越す", "ひっこす", [("引", "ひ"), ("っ", None), ("越", "こ"), ("す", None)]),
        # Leading kana before the first kanji.
        ("お茶", "おちゃ", [("お", None), ("茶", "ちゃ")]),
        # A single kanji with a long reading.
        ("承る", "うけたまわる", [("承", "うけたまわ"), ("る", None)]),
    ],
)
def test_alignment(surface, reading, expected):
    result = align(surface, reading)
    assert result.status == OK, result.reason
    assert seg(result) == expected


def test_punctuation_is_not_given_ruby():
    result = align("お早う", "おはよう")
    assert result.status == OK
    assert seg(result) == [("お", None), ("早", "はよ"), ("う", None)]


def test_reading_that_cannot_be_aligned_is_rejected():
    result = align("食べる", "のむ")
    assert result.status == NEEDS_REVIEW
    assert result.reason


def test_kana_only_surface_with_wrong_reading_is_rejected():
    result = align("ありがとう", "さようなら")
    assert result.status == NEEDS_REVIEW


def test_empty_inputs_are_rejected():
    assert align("", "たべる").status == NEEDS_REVIEW
    assert align("食べる", "").status == NEEDS_REVIEW


def test_reconstruction_round_trips():
    result = align("取り除く", "とりのぞく")
    assert segments_surface(result.segments) == "取り除く"
    assert segments_reading(result.segments) == "とりのぞく"


def test_unicode_normalisation():
    # Decomposed dakuten must compare equal to the composed form.
    decomposed = "がっこう"  # か + combining dakuten
    result = align("学校", nfc("が") + "っこう")
    assert result.status == OK
    assert align("学校", nfc(decomposed)).status == OK


def test_katakana_reading_script_is_preserved():
    # The reading is sliced out of the source string, not the comparison form.
    result = align("消しゴム", "ケシゴム")
    assert result.status == OK
    assert result.segments[0].reading == "ケ"


class TestCheckSegments:
    def test_accepts_a_correct_segmentation(self):
        segments = [RubySegment("取", "と"), RubySegment("り", None)]
        assert check_segments("取り", "とり", segments) == []

    def test_rejects_base_concatenation_mismatch(self):
        segments = [RubySegment("取", "と")]
        problems = check_segments("取り", "とり", segments)
        assert any("concatenate" in p for p in problems)

    def test_rejects_reading_mismatch(self):
        segments = [RubySegment("取", "ぬ"), RubySegment("り", None)]
        problems = check_segments("取り", "とり", segments)
        assert any("reconstruct" in p for p in problems)

    def test_rejects_kanji_without_a_reading(self):
        segments = [RubySegment("取り", None)]
        problems = check_segments("取り", "とり", segments)
        assert problems

    def test_rejects_redundant_ruby_over_kana(self):
        segments = [RubySegment("とり", "とり")]
        problems = check_segments("とり", "とり", segments)
        assert any("redundant" in p for p in problems)

    def test_rejects_non_kana_ruby_reading(self):
        segments = [RubySegment("取", "to"), RubySegment("り", None)]
        problems = check_segments("取り", "とり", segments)
        assert any("pure kana" in p for p in problems)

    def test_reports_no_segments(self):
        assert check_segments("取り", "とり", []) == ["no ruby segments"]


class TestResolve:
    def test_override_takes_precedence_over_alignment(self):
        overrides = {"x:1": [RubySegment("明白", "あからさま")]}
        result = resolve("x:1", "明白", "あからさま", overrides=overrides)
        assert result.status == OK
        assert seg(result) == [("明白", "あからさま")]

    def test_invalid_override_is_flagged_rather_than_used(self):
        overrides = {"x:1": [RubySegment("明白", "まちがい")]}
        result = resolve("x:1", "明白", "あからさま", overrides=overrides)
        assert result.status == NEEDS_REVIEW
        assert "invalid override" in (result.reason or "")

    def test_source_segmentation_is_used_when_valid(self):
        existing = [RubySegment("明白", "あからさま")]
        result = resolve("x:1", "明白", "あからさま", existing=existing)
        assert result.status == OK
        assert seg(result) == [("明白", "あからさま")]

    def test_falls_back_to_the_aligner_when_source_segmentation_is_wrong(self):
        existing = [RubySegment("食べる", "たべる")]  # kana run carries ruby
        result = resolve("x:1", "食べる", "たべる", existing=existing)
        assert result.status == OK
        assert seg(result) == [("食", "た"), ("べる", None)]

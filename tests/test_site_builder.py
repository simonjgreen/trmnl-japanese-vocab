"""Static site generation: paths, payloads, manifest and reproducibility."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kotoba.models import Example, JlptAssignment, RubySegment, VocabularyEntry
from kotoba.site_builder import (
    BuildConfig,
    SelectionConfig,
    build_site,
    dump_payload,
    estimated_word_width,
    example_size_class,
    word_size_class,
)
from kotoba.validation import validate_corpus, validate_site

TODAY = date(2026, 8, 9)
EPOCH = date(2026, 1, 1)

# A five-word-per-level corpus, so the deck is deliberately tiny.
SMALL = BuildConfig(
    past_days=3,
    future_days=6,
    status="demo",
    minimum_entries_per_level=1,
    deck_size=5,
    slot_seconds=600,
    recommended_bytes=8192,
    hard_limit_bytes=16384,
)
SELECTION = SelectionConfig(epoch_date=EPOCH, selection_version="1", selection_salt="t")


@pytest.fixture
def corpus(corpus_root, schemas_dir):
    report, loaded = validate_corpus(
        vocabulary_dir=corpus_root / "data" / "vocabulary",
        sources_path=corpus_root / "data" / "sources.yml",
        schema_dir=schemas_dir,
    )
    assert report.ok, "\n".join(i.format() for i in report.errors)
    return loaded


def build(corpus, tmp_path: Path, config: BuildConfig = SMALL):
    return build_site(
        corpus=corpus,
        output_dir=tmp_path / "site",
        build_config=config,
        selection_config=SELECTION,
        dataset_version="test+abc123",
        sources_summary=[{"id": "demo", "name": "Demo", "licence": "CC0-1.0", "version": "1"}],
        commit_sha="abc123",
        today=TODAY,
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc),
    )


class TestDisplaySizing:
    def make(self, surface, segments):
        return VocabularyEntry(
            id="demo:x", surface=surface, reading="x",
            ruby_segments=[RubySegment(b, r) for b, r in segments],
            glosses=["x"], display_gloss="x",
            jlpt=JlptAssignment(level="N5", source_id="demo"),
            source_refs=[], status="active",
        )

    def test_short_word(self):
        assert word_size_class(self.make("本", [("本", "ほん")])) == "short"

    def test_medium_word(self):
        assert word_size_class(self.make("取り除く", [("取", "と"), ("り", None),
                                                   ("除", "のぞ"), ("く", None)])) == "medium"

    def test_xlong_word(self):
        entry = self.make("デモンストレーション", [("デモンストレーション", None)])
        assert word_size_class(entry) == "xlong"

    def test_wide_ruby_counts_towards_width(self):
        """A long reading over one kanji is wider than the kanji alone."""
        narrow = self.make("承", [("承", "う")])
        wide = self.make("承", [("承", "うけたまわりましょう")])
        assert estimated_word_width(wide) > estimated_word_width(narrow)

    def test_example_size_classes(self):
        def with_example(text):
            return VocabularyEntry(
                id="demo:x", surface="本", reading="ほん",
                ruby_segments=[RubySegment("本", "ほん")], glosses=["x"],
                display_gloss="x",
                jlpt=JlptAssignment(level="N5", source_id="demo"),
                source_refs=[], status="active", example=Example(ja=text),
            )

        assert example_size_class(with_example("短い文。")) == "normal"
        assert example_size_class(with_example("あ" * 30)) == "compact"
        assert example_size_class(with_example("あ" * 40)) == "tiny"


class TestBuild:
    def test_generates_the_expected_paths(self, corpus, tmp_path):
        build(corpus, tmp_path)
        site = tmp_path / "site"
        assert (site / "index.html").is_file()
        assert (site / "health.json").is_file()
        assert (site / ".nojekyll").is_file()
        assert (site / "api" / "v1" / "manifest.json").is_file()
        for level in ("n5", "n4", "n3", "n2", "n1"):
            level_dir = site / "api" / "v1" / "daily" / level
            assert (level_dir / "latest.json").is_file()
            assert (level_dir / "sample.json").is_file()
            assert (level_dir / f"{TODAY.isoformat()}.json").is_file()

    def test_covers_exactly_the_requested_date_range(self, corpus, tmp_path):
        result = build(corpus, tmp_path)
        assert result.start_date == TODAY - timedelta(days=3)
        assert result.end_date == TODAY + timedelta(days=6)
        expected = 10  # 3 past + today + 6 future
        level_dir = tmp_path / "site" / "api" / "v1" / "daily" / "n3"
        dated = [p for p in level_dir.glob("*.json") if p.stem not in ("latest", "sample")]
        assert len(dated) == expected
        assert result.file_counts["n3"] == expected

    def test_manifest_is_accurate(self, corpus, tmp_path):
        build(corpus, tmp_path)
        manifest = json.loads(
            (tmp_path / "site" / "api" / "v1" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["dataset_version"] == "test+abc123"
        assert manifest["commit_sha"] == "abc123"
        assert manifest["status"] == "demo"
        assert manifest["active_entries"] == {k: 5 for k in ("n5", "n4", "n3", "n2", "n1")}
        assert manifest["deck_pool"] == {"n5": 5, "n4": 10, "n3": 15, "n2": 20, "n1": 25}
        assert manifest["generated_files"] == {k: 10 for k in ("n5", "n4", "n3", "n2", "n1")}
        assert manifest["earliest_date"] == "2026-08-06"
        assert manifest["latest_date"] == "2026-08-15"

    def test_payloads_are_minified_utf8_with_readable_japanese(self, corpus, tmp_path):
        build(corpus, tmp_path)
        path = tmp_path / "site" / "api" / "v1" / "daily" / "n3" / f"{TODAY}.json"
        text = path.read_text(encoding="utf-8")
        assert "\\u" not in text, "Japanese must not be escaped"
        assert ", " not in text and ": " not in text, "payload should be minified"

    def test_a_deck_is_cumulative_over_easier_levels(self, corpus, tmp_path):
        """Choosing N3 must draw on N5 and N4 as well."""
        build(corpus, tmp_path)
        path = tmp_path / "site" / "api" / "v1" / "daily" / "n3" / f"{TODAY}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["deck"]["pool"] == 15  # 5 each of N5, N4, N3
        n5 = json.loads(
            (tmp_path / "site" / "api" / "v1" / "daily" / "n5" / f"{TODAY}.json")
            .read_text(encoding="utf-8")
        )
        assert n5["deck"]["pool"] == 5
        n1 = json.loads(
            (tmp_path / "site" / "api" / "v1" / "daily" / "n1" / f"{TODAY}.json")
            .read_text(encoding="utf-8")
        )
        assert n1["deck"]["pool"] == 25  # every level

    def test_each_card_declares_its_own_level(self, corpus, tmp_path):
        build(corpus, tmp_path)
        payload = json.loads(
            (tmp_path / "site" / "api" / "v1" / "daily" / "n3" / f"{TODAY}.json")
            .read_text(encoding="utf-8")
        )
        levels = {w["level"] for w in payload["words"]}
        assert levels <= {"N5", "N4", "N3"}
        assert "N2" not in levels and "N1" not in levels

    def test_deck_metadata_matches_the_build_config(self, corpus, tmp_path):
        build(corpus, tmp_path)
        payload = json.loads(
            (tmp_path / "site" / "api" / "v1" / "daily" / "n3" / f"{TODAY}.json")
            .read_text(encoding="utf-8")
        )
        assert payload["deck"]["size"] == SMALL.deck_size
        assert payload["deck"]["slot_seconds"] == SMALL.slot_seconds
        assert len(payload["words"]) == SMALL.deck_size

    def test_consecutive_days_draw_different_cards(self, corpus, tmp_path):
        """A deck moves on; it does not replay yesterday."""
        build(corpus, tmp_path)
        level_dir = tmp_path / "site" / "api" / "v1" / "daily" / "n1"
        today = json.loads((level_dir / f"{TODAY}.json").read_text(encoding="utf-8"))
        tomorrow = json.loads(
            (level_dir / f"{TODAY + timedelta(days=1)}.json").read_text(encoding="utf-8")
        )
        assert {w["id"] for w in today["words"]} != {
            w["id"] for w in tomorrow["words"]
        }

    def test_payloads_are_small(self, corpus, tmp_path):
        result = build(corpus, tmp_path)
        assert result.largest_payload < SMALL.recommended_bytes
        assert result.oversized == []

    def test_generated_site_validates(self, corpus, tmp_path, schemas_dir):
        build(corpus, tmp_path)
        report = validate_site(
            site_dir=tmp_path / "site",
            schema_dir=schemas_dir,
            hard_size_limit=SMALL.hard_limit_bytes,
        )
        assert report.ok, "\n".join(i.format() for i in report.errors)
        assert report.counts["payloads_checked"] == 50

    def test_the_same_date_rebuilds_identically(self, corpus, tmp_path):
        build(corpus, tmp_path / "a")
        build(corpus, tmp_path / "b")
        for level in ("n5", "n3", "n1"):
            a = (tmp_path / "a" / "site" / "api" / "v1" / "daily" / level / f"{TODAY}.json")
            b = (tmp_path / "b" / "site" / "api" / "v1" / "daily" / level / f"{TODAY}.json")
            assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")

    def test_latest_matches_the_newest_payload(self, corpus, tmp_path):
        build(corpus, tmp_path)
        level_dir = tmp_path / "site" / "api" / "v1" / "daily" / "n3"
        latest = json.loads((level_dir / "latest.json").read_text(encoding="utf-8"))
        assert latest["date"] == "2026-08-15"

    def test_payload_date_and_level_match_their_path(self, corpus, tmp_path):
        build(corpus, tmp_path)
        path = tmp_path / "site" / "api" / "v1" / "daily" / "n2" / "2026-08-11.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["date"] == "2026-08-11"
        assert payload["level"] == "n2"
        assert payload["level_display"] == "N2"
        assert payload["schema_version"] == "2.0"

    def test_index_links_resolve_to_real_files(self, corpus, tmp_path):
        import re

        build(corpus, tmp_path)
        site = tmp_path / "site"
        html = (site / "index.html").read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"#:]+)"', html):
            assert (site / href).exists(), href

    def test_empty_level_is_refused(self, corpus, tmp_path):
        """N5 has nothing easier to fall back on, so emptying it is fatal."""
        corpus["n5"] = []
        with pytest.raises(ValueError, match="no active entries"):
            build(corpus, tmp_path)

    def test_minimum_entries_is_enforced(self, corpus, tmp_path):
        config = BuildConfig(**{**SMALL.__dict__, "minimum_entries_per_level": 50})
        with pytest.raises(ValueError, match="minimum is 50"):
            build(corpus, tmp_path, config)

    def test_oversized_payload_is_refused(self, corpus, tmp_path):
        config = BuildConfig(**{**SMALL.__dict__, "hard_limit_bytes": 50})
        with pytest.raises(ValueError, match="hard size limit"):
            build(corpus, tmp_path, config)


def test_dump_payload_minification():
    payload = {"a": 1, "ja": "日本語"}
    assert dump_payload(payload, True) == '{"a":1,"ja":"日本語"}'
    assert "\n" in dump_payload(payload, False)

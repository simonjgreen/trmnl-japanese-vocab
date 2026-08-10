"""Static site generation: paths, payloads, manifest and reproducibility."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
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
    status="demo",
    minimum_entries_per_level=1,
    slot_seconds=600,
    slot_count=12,
    recommended_bytes=2048,
    hard_limit_bytes=8192,
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


def build_at(corpus, tmp_path: Path, day):
    """Build for a given date and return the n3 slot-0 card id."""
    build(corpus, tmp_path, SMALL, day)
    payload = json.loads(
        (tmp_path / "site" / "api" / "v1" / "card" / "n3" / "0.json")
        .read_text(encoding="utf-8")
    )
    return payload["word"]["id"]


def build(corpus, tmp_path: Path, config: BuildConfig = SMALL, day=TODAY):
    return build_site(
        corpus=corpus,
        output_dir=tmp_path / "site",
        build_config=config,
        selection_config=SELECTION,
        dataset_version="test+abc123",
        sources_summary=[{"id": "demo", "name": "Demo", "licence": "CC0-1.0", "version": "1"}],
        commit_sha="abc123",
        today=day,
        generated_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
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
            level_dir = site / "api" / "v1" / "card" / level
            assert (level_dir / "sample.json").is_file()
            assert (level_dir / "0.json").is_file()

    def test_every_slot_the_url_can_request_exists(self, corpus, tmp_path):
        """A missing slot is a 404 and a blank screen, not a stale card."""
        build(corpus, tmp_path)
        level_dir = tmp_path / "site" / "api" / "v1" / "card" / "n3"
        for slot in range(SMALL.slot_count):
            assert (level_dir / f"{slot}.json").is_file(), slot
        assert not (level_dir / f"{SMALL.slot_count}.json").exists()

    def test_consecutive_slots_hold_different_cards(self, corpus, tmp_path):
        """The whole point: the payload must change so TRMNL re-renders."""
        build(corpus, tmp_path)
        level_dir = tmp_path / "site" / "api" / "v1" / "card" / "n1"
        texts = [
            (level_dir / f"{slot}.json").read_text(encoding="utf-8")
            for slot in range(5)
        ]
        assert len(set(texts)) == len(texts), "identical payloads would be skipped"

    def test_slot_index_matches_the_filename(self, corpus, tmp_path):
        build(corpus, tmp_path)
        level_dir = tmp_path / "site" / "api" / "v1" / "card" / "n2"
        for slot in (0, 3, SMALL.slot_count - 1):
            payload = json.loads((level_dir / f"{slot}.json").read_text(encoding="utf-8"))
            assert payload["slot"]["index"] == slot
            assert payload["slot"]["count"] == SMALL.slot_count
            assert payload["slot"]["seconds"] == SMALL.slot_seconds

    def test_manifest_is_accurate(self, corpus, tmp_path):
        build(corpus, tmp_path)
        manifest = json.loads(
            (tmp_path / "site" / "api" / "v1" / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["dataset_version"] == "test+abc123"
        assert manifest["commit_sha"] == "abc123"
        assert manifest["status"] == "demo"
        assert manifest["active_entries"] == dict.fromkeys(("n5", "n4", "n3", "n2", "n1"), 5)
        assert manifest["deck_pool"] == {"n5": 5, "n4": 10, "n3": 15, "n2": 20, "n1": 25}
        assert manifest["generated_files"] == dict.fromkeys(
            ("n5", "n4", "n3", "n2", "n1"), SMALL.slot_count
        )
        assert manifest["slots"]["cumulative_levels"] is True

    def test_payloads_are_minified_utf8_with_readable_japanese(self, corpus, tmp_path):
        build(corpus, tmp_path)
        path = tmp_path / "site" / "api" / "v1" / "card" / "n3" / "0.json"
        text = path.read_text(encoding="utf-8")
        assert "\\u" not in text, "Japanese must not be escaped"
        assert ", " not in text and ": " not in text, "payload should be minified"

    def test_a_pool_is_cumulative_over_easier_levels(self, corpus, tmp_path):
        """Choosing N3 must draw on N5 and N4 as well."""
        build(corpus, tmp_path)
        api = tmp_path / "site" / "api" / "v1" / "card"
        pools = {
            level: json.loads((api / level / "0.json").read_text(encoding="utf-8"))[
                "sequence"
            ]["pool"]
            for level in ("n5", "n3", "n1")
        }
        assert pools == {"n5": 5, "n3": 15, "n1": 25}

    def test_no_card_comes_from_a_harder_level(self, corpus, tmp_path):
        build(corpus, tmp_path)
        level_dir = tmp_path / "site" / "api" / "v1" / "card" / "n3"
        levels = {
            json.loads((level_dir / f"{s}.json").read_text(encoding="utf-8"))["word"]["level"]
            for s in range(SMALL.slot_count)
        }
        assert levels <= {"N5", "N4", "N3"}

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
        assert report.counts["payloads_checked"] == 5 * SMALL.slot_count

    def test_rebuilding_the_same_day_is_identical(self, corpus, tmp_path):
        build(corpus, tmp_path / "a")
        build(corpus, tmp_path / "b")
        for level in ("n5", "n3", "n1"):
            a = tmp_path / "a" / "site" / "api" / "v1" / "card" / level / "0.json"
            b = tmp_path / "b" / "site" / "api" / "v1" / "card" / level / "0.json"
            assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")

    def test_the_rotation_advances_with_the_build_date(self, corpus, tmp_path):
        """Successive builds carry on through the corpus, not replay it."""
        today = build_at(corpus, tmp_path / "today", TODAY)
        later = build_at(corpus, tmp_path / "later", TODAY + timedelta(days=1))
        assert today != later

    def test_index_links_resolve_to_real_files(self, corpus, tmp_path):
        import re

        build(corpus, tmp_path)
        site = tmp_path / "site"
        html = (site / "index.html").read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"#:]+)"', html):
            assert (site / href).exists(), href

    def test_index_interpolates_every_placeholder(self, corpus, tmp_path):
        """The landing page is public, so an unsubstituted expression is a bug.

        A leftover string-concatenation fragment once shipped to the live site
        and rendered as `" + str(manifest["slots"]["seconds"]) + "` in prose.
        Nothing checked the page's *text*, only that its links resolved.
        """
        build(corpus, tmp_path)
        html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
        for artefact in (' + str(', '{manifest', '{html.escape', '%s', '{}'):
            assert artefact not in html, f"unsubstituted {artefact!r} in index.html"

    def test_index_reports_the_real_slot_duration(self, corpus, tmp_path):
        build(corpus, tmp_path)
        html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
        assert f"<code>{SMALL.slot_seconds}</code> seconds" in html

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

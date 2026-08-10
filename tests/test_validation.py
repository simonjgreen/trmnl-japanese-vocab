"""Corpus validation: schema errors, semantic errors and their locations."""

from __future__ import annotations

import json
from pathlib import Path

from kotoba.validation import validate_corpus


def load(vocabulary_dir: Path, level: str) -> list[dict]:
    return json.loads((vocabulary_dir / f"{level}.json").read_text(encoding="utf-8"))


def save(vocabulary_dir: Path, level: str, entries: list[dict]) -> None:
    (vocabulary_dir / f"{level}.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def mutate(vocabulary_dir: Path, level: str, index: int, **changes):
    entries = load(vocabulary_dir, level)
    entries[index].update(changes)
    save(vocabulary_dir, level, entries)


def run(corpus_root: Path, schemas_dir: Path, minimum: int = 1):
    return validate_corpus(
        vocabulary_dir=corpus_root / "data" / "vocabulary",
        sources_path=corpus_root / "data" / "sources.yml",
        schema_dir=schemas_dir,
        minimum_per_level=minimum,
    )


def messages(report) -> str:
    return "\n".join(i.format() for i in report.issues)


def test_a_valid_corpus_passes(corpus_root, schemas_dir):
    report, corpus = run(corpus_root, schemas_dir)
    assert report.ok, messages(report)
    assert report.counts["total_active"] == 25
    assert set(corpus) == {"n5", "n4", "n3", "n2", "n1"}


def test_counts_only_active_entries(corpus_root, schemas_dir, vocabulary_dir):
    mutate(vocabulary_dir, "n3", 0, status="disabled")
    report, _ = run(corpus_root, schemas_dir)
    assert report.ok, messages(report)
    assert report.counts["n3"] == 4


def test_missing_level_file_is_an_error(corpus_root, schemas_dir, vocabulary_dir):
    (vocabulary_dir / "n1.json").unlink()
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "missing level file" in messages(report)


def test_invalid_json_is_reported(corpus_root, schemas_dir, vocabulary_dir):
    (vocabulary_dir / "n2.json").write_text("{not json", encoding="utf-8")
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "invalid JSON" in messages(report)


def test_duplicate_ids_are_reported_with_both_files(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    n3 = load(vocabulary_dir, "n3")
    n3[0]["id"] = entries[0]["id"]
    save(vocabulary_dir, "n3", sorted(n3, key=lambda e: e["id"]))
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "duplicate entry ID" in messages(report)


def test_level_must_match_its_file(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    entries[0]["jlpt"]["level"] = "N1"
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "does not match its file" in messages(report)


def test_invalid_level_enum_is_rejected(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    entries[0]["jlpt"]["level"] = "N9"
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok


def test_unknown_source_id_is_rejected(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    entries[0]["source_refs"] = [{"source_id": "nowhere"}]
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "unknown source ID" in messages(report)


def test_missing_provenance_is_rejected(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    entries[0]["source_refs"] = []
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok


def test_base_concatenation_mismatch_is_reported(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n3")
    entries[0]["ruby_segments"] = [{"base": "取", "reading": "と"}]
    save(vocabulary_dir, "n3", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "concatenate to surface" in messages(report)


def test_reading_mismatch_is_reported(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    entries[0]["ruby_segments"] = [
        {"base": "食", "reading": "ぬ"},
        {"base": "べる", "reading": None},
    ]
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "reconstruct reading" in messages(report)


def test_overlong_gloss_is_an_error_beyond_the_hard_limit(
    corpus_root, schemas_dir, vocabulary_dir
):
    mutate(vocabulary_dir, "n5", 0, display_gloss="x" * 120)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok


def test_overlong_gloss_is_a_warning_beyond_the_recommendation(
    corpus_root, schemas_dir, vocabulary_dir
):
    mutate(vocabulary_dir, "n5", 0, display_gloss="x" * 70)
    report, _ = run(corpus_root, schemas_dir)
    assert report.ok, messages(report)
    assert any("recommended maximum" in i.message for i in report.warnings)


def test_overlong_example_is_rejected(corpus_root, schemas_dir, vocabulary_dir):
    mutate(vocabulary_dir, "n5", 0, example={"ja": "あ" * 100})
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok


def test_html_in_data_is_rejected(corpus_root, schemas_dir, vocabulary_dir):
    mutate(vocabulary_dir, "n5", 0, display_gloss="<b>eat</b>")
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "HTML markup is not permitted" in messages(report)


def test_untrimmed_text_is_rejected(corpus_root, schemas_dir, vocabulary_dir):
    mutate(vocabulary_dir, "n5", 0, display_gloss="  eat  ")
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok


def test_unsorted_entries_are_reported(corpus_root, schemas_dir, vocabulary_dir):
    entries = load(vocabulary_dir, "n5")
    save(vocabulary_dir, "n5", list(reversed(entries)))
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "stable-sorted" in messages(report)


def test_duplicate_surface_reading_gloss_is_reported(
    corpus_root, schemas_dir, vocabulary_dir
):
    entries = load(vocabulary_dir, "n5")
    entries[1]["surface"] = entries[0]["surface"]
    entries[1]["reading"] = entries[0]["reading"]
    entries[1]["display_gloss"] = entries[0]["display_gloss"]
    entries[1]["ruby_segments"] = entries[0]["ruby_segments"]
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "duplicate surface/reading/gloss" in messages(report)


def test_minimum_entries_per_level_is_enforced(corpus_root, schemas_dir):
    report, _ = run(corpus_root, schemas_dir, minimum=10)
    assert not report.ok
    assert "minimum is 10" in messages(report)


def test_issues_carry_file_entry_and_field_path(corpus_root, schemas_dir, vocabulary_dir):
    mutate(vocabulary_dir, "n5", 0, display_gloss="<b>x</b>")
    report, _ = run(corpus_root, schemas_dir)
    issue = next(i for i in report.errors if "HTML" in i.message)
    assert issue.file and issue.file.endswith("n5.json")
    assert issue.entry_id == "demo:n5-000"
    assert issue.path == "display_gloss"


def test_missing_sources_register_is_reported(corpus_root, schemas_dir):
    (corpus_root / "data" / "sources.yml").unlink()
    report, _ = run(corpus_root, schemas_dir)
    assert not report.ok
    assert "missing provenance register" in messages(report)


def test_disabled_entry_with_bad_furigana_is_only_a_warning(
    corpus_root, schemas_dir, vocabulary_dir
):
    entries = load(vocabulary_dir, "n5")
    entries[0]["status"] = "disabled"
    entries[0]["ruby_segments"] = [{"base": "食", "reading": "ぬ"},
                                   {"base": "べる", "reading": None}]
    save(vocabulary_dir, "n5", entries)
    report, _ = run(corpus_root, schemas_dir)
    assert report.ok, messages(report)
    assert report.warnings

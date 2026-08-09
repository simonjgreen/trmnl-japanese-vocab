"""Shared fixtures: a tiny, wholly synthetic corpus on disk.

The words are real, but the level assignments here are arbitrary and exist
only to give each level a handful of distinct, valid entries to schedule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent

SOURCES = {
    "sources": [
        {
            "id": "demo",
            "name": "Demo source",
            "homepage": "https://example.com/",
            "retrieved": "2026-08-09",
            "licence": "CC0-1.0",
            "licence_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "attribution": "Synthetic test data.",
            "fields_used": ["surface", "reading"],
        }
    ]
}

#: Five distinct words per level: (surface, reading, segments, gloss).
WORDS: dict[str, list[tuple[str, str, list[tuple[str, str | None]], str]]] = {
    "N5": [
        ("食べる", "たべる", [("食", "た"), ("べる", None)], "to eat"),
        ("本", "ほん", [("本", "ほん")], "book"),
        ("学校", "がっこう", [("学校", "がっこう")], "school"),
        ("ありがとう", "ありがとう", [("ありがとう", None)], "thank you"),
        ("お茶", "おちゃ", [("お", None), ("茶", "ちゃ")], "tea"),
    ],
    "N4": [
        ("今日", "きょう", [("今日", "きょう")], "today"),
        ("砂", "すな", [("砂", "すな")], "sand"),
        ("時々", "ときどき", [("時々", "ときどき")], "sometimes"),
        ("消しゴム", "けしごむ", [("消", "け"), ("しゴム", None)], "eraser"),
        ("大人", "おとな", [("大人", "おとな")], "adult"),
    ],
    "N3": [
        ("取り除く", "とりのぞく",
         [("取", "と"), ("り", None), ("除", "のぞ"), ("く", None)], "eliminate"),
        ("混雑", "こんざつ", [("混", "こん"), ("雑", "ざつ")], "congestion"),
        ("花瓶", "かびん", [("花", "か"), ("瓶", "びん")], "vase"),
        ("引っ越す", "ひっこす",
         [("引", "ひ"), ("っ", None), ("越", "こ"), ("す", None)], "to move house"),
        ("コーヒー", "コーヒー", [("コーヒー", None)], "coffee"),
    ],
    "N2": [
        ("申し込む", "もうしこむ",
         [("申", "もう"), ("し", None), ("込", "こ"), ("む", None)], "to apply"),
        ("飢饉", "ききん", [("飢", "き"), ("饉", "きん")], "famine"),
        ("国際", "こくさい", [("国際", "こくさい")], "international"),
        ("経済", "けいざい", [("経済", "けいざい")], "economy"),
        ("明白", "あからさま", [("明白", "あからさま")], "plain"),
    ],
    "N1": [
        ("承る", "うけたまわる", [("承", "うけたまわ"), ("る", None)], "to hear"),
        ("勧告", "かんこく", [("勧", "かん"), ("告", "こく")], "advice"),
        ("阿吽の呼吸", "あうんのこきゅう",
         [("阿", "あ"), ("吽", "うん"), ("の", None), ("呼", "こ"), ("吸", "きゅう")],
         "perfect timing"),
        ("ヶ月", "かげつ", [("ヶ", "か"), ("月", "げつ")], "counter for months"),
        ("一つ一つ", "ひとつひとつ",
         [("一", "ひと"), ("つ", None), ("一", "ひと"), ("つ", None)], "one by one"),
    ],
}


def make_entry(
    index: int,
    level: str,
    surface: str,
    reading: str,
    segments: list[tuple[str, str | None]],
    gloss: str,
    example: bool = True,
) -> dict:
    doc: dict = {
        "id": f"demo:{level.lower()}-{index:03d}",
        "surface": surface,
        "reading": reading,
        "ruby_segments": [{"base": b, "reading": r} for b, r in segments],
        "glosses": [gloss],
        "display_gloss": gloss,
        "jlpt": {"level": level, "source_id": "demo", "confidence": "test"},
        "source_refs": [{"source_id": "demo", "source_entry_id": str(index)}],
        "status": "active",
        "notes": None,
    }
    if example:
        doc["example"] = {"ja": "これはテストです。", "en": "This is a test."}
    return doc


def write_corpus(root: Path, words: dict = WORDS) -> Path:
    """Write a full five-level corpus under *root* and return the data dir."""
    vocab = root / "data" / "vocabulary"
    vocab.mkdir(parents=True, exist_ok=True)
    for level, items in words.items():
        entries = [
            make_entry(index, level, *item) for index, item in enumerate(items)
        ]
        entries.sort(key=lambda e: e["id"])
        (vocab / f"{level.lower()}.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (root / "data" / "sources.yml").write_text(
        yaml.safe_dump(SOURCES, allow_unicode=True), encoding="utf-8"
    )
    return vocab


@pytest.fixture
def corpus_root(tmp_path: Path) -> Path:
    """A temporary project root containing a valid corpus."""
    write_corpus(tmp_path)
    return tmp_path


@pytest.fixture
def vocabulary_dir(corpus_root: Path) -> Path:
    return corpus_root / "data" / "vocabulary"


@pytest.fixture
def sources_path(corpus_root: Path) -> Path:
    return corpus_root / "data" / "sources.yml"


@pytest.fixture
def schemas_dir() -> Path:
    return REPO / "schemas"

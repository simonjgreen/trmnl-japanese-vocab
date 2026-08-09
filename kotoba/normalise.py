"""Unicode, whitespace and kana normalisation helpers.

Every string that enters the canonical corpus passes through this module so
that comparisons elsewhere (furigana alignment, duplicate detection, stable
identifier derivation) operate on a single predictable representation.
"""

from __future__ import annotations

import unicodedata

# Kana block boundaries. Katakana is folded onto hiragana for comparison only;
# the canonical corpus preserves whatever script the source supplied.
HIRAGANA_START = 0x3041
HIRAGANA_END = 0x3096
KATAKANA_START = 0x30A1
KATAKANA_END = 0x30F6
KATAKANA_HIRAGANA_OFFSET = KATAKANA_START - HIRAGANA_START

#: Prolonged sound mark, iteration marks and the nakaguro. These behave as
#: phonetic material rather than as ruby-bearing characters.
PROLONGED_SOUND_MARK = "ー"
KANA_ITERATION_MARKS = "ゝゞヽヾ"
KANJI_ITERATION_MARK = "々"

#: Characters that never carry furigana and never appear in a kana reading.
#: The prolonged sound mark is deliberately absent: it is pronounced material
#: and must survive into the reading comparison.
NON_RUBY_PUNCTUATION = set(
    "、。！？「」『』・…‥〜～：；，．　 　()（）[]［］/／-–—"
)

CONTROL_CHARACTERS = {
    chr(c) for c in range(0x20) if chr(c) not in "\t\n"
} | {chr(0x7F)}


def nfc(text: str) -> str:
    """Return *text* in Unicode NFC form."""
    return unicodedata.normalize("NFC", text)


def clean_text(text: str) -> str:
    """NFC-normalise, collapse internal whitespace and strip the ends.

    Ideographic spaces are treated as whitespace so that a source cannot
    smuggle an invisible full-width space into a gloss or example sentence.
    """
    if text is None:
        return ""
    normalised = nfc(str(text)).replace("　", " ")
    normalised = "".join(
        ch for ch in normalised if ch not in CONTROL_CHARACTERS
    )
    return " ".join(normalised.split())


def has_control_characters(text: str) -> bool:
    """True when *text* contains C0/C1 control characters."""
    return any(ch in CONTROL_CHARACTERS for ch in text)


def is_hiragana(ch: str) -> bool:
    return HIRAGANA_START <= ord(ch) <= HIRAGANA_END


def is_katakana(ch: str) -> bool:
    return KATAKANA_START <= ord(ch) <= KATAKANA_END


#: Small ka/ke. These sit in the katakana block but are abbreviations of 箇
#: and are read "ka"/"ko", never "ka"/"ke" as their shape suggests — 一ヶ月 is
#: いっかげつ. They therefore need ruby and must not count as readable kana.
SMALL_KA_KE = "ヵヶ"


def is_kana(ch: str) -> bool:
    """True for hiragana, katakana, the prolonged sound mark and kana repeats.

    Small ka/ke are excluded: see :data:`SMALL_KA_KE`.
    """
    if ch in SMALL_KA_KE:
        return False
    return (
        is_hiragana(ch)
        or is_katakana(ch)
        or ch == PROLONGED_SOUND_MARK
        or ch in KANA_ITERATION_MARKS
    )


def is_kanji(ch: str) -> bool:
    """True for CJK ideographs and the kanji iteration mark 々."""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= code <= 0x4DBF  # Extension A
        or 0xF900 <= code <= 0xFAFF  # Compatibility Ideographs
        or 0x20000 <= code <= 0x2FA1F  # Extensions B-F and supplement
        or ch == KANJI_ITERATION_MARK
    )


def to_hiragana(text: str) -> str:
    """Fold katakana onto hiragana for comparison purposes.

    The prolonged sound mark is deliberately left intact; resolving it to a
    vowel requires context the aligner does not have, and treating it as
    opaque keeps the comparison conservative.
    """
    out = []
    for ch in nfc(text):
        if is_katakana(ch):
            out.append(chr(ord(ch) - KATAKANA_HIRAGANA_OFFSET))
        else:
            out.append(ch)
    return "".join(out)


def comparison_reading(text: str) -> str:
    """Normalise a reading so two spellings of the same sound compare equal."""
    return to_hiragana(clean_text(text)).replace(" ", "")


def display_width(text: str) -> float:
    """Estimate rendered width in full-width character units.

    East Asian Wide and Fullwidth characters count as one unit; everything
    else counts as roughly half a unit. This is a deliberately cheap
    approximation used only to choose a CSS size class at build time.
    """
    total = 0.0
    for ch in nfc(text):
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 1.0
        elif ch == " ":
            total += 0.35
        else:
            total += 0.5
    return total

# Data sourcing

## What the corpus is

8,289 words across N5–N1, each with a kana reading, ruby segmentation, a
concise English gloss, and — for about 89% of entries — a natural Japanese
example sentence with an English translation.

| Level | Active words | With an example |
| ----- | ------------ | --------------- |
| N5    | 684          | 668             |
| N4    | 640          | 629             |
| N3    | 1,730        | 1,673           |
| N2    | 1,812        | 1,609           |
| N1    | 3,423        | 2,788           |

Run `kotoba manifest` after a build for the live numbers.

## What "JLPT level" means here

**These are community estimates, not an official specification.** The Japan
Foundation and JEES stopped publishing JLPT vocabulary lists in 2010. Every
level list in circulation — including the one used here, and the one behind
jisho.org — traces back to Jonathan Waller's lists, compiled over a decade ago
and described by their own maintainers as "essentially an educated guess."

Consequences, stated plainly:

- Never describe this corpus as an official JLPT vocabulary list.
- Never imply endorsement by the Japan Foundation or JEES.
- "This word is really N2, not N3" is a matter of judgement. Corrections to
  readings, glosses and furigana are far more clear-cut.

Selecting a level gives words assigned to **that exact level only**. N3 does
not mix in N5 and N4 material, which would otherwise dominate the rotation.
The data model would support a future `target_and_easier` setting without
changes, but no such control exists today.

## Sources

| Purpose | Source | Licence |
| ------- | ------ | ------- |
| JLPT levels, joined on JMdict entry id | [stephenmk/yomitan-jlpt-vocab](https://github.com/stephenmk/yomitan-jlpt-vocab) | CC BY-SA 4.0 |
| Readings, glosses, parts of speech, examples | [scriptin/jmdict-simplified](https://github.com/scriptin/jmdict-simplified) (`jmdict-examples-eng`) | CC BY-SA 4.0 |
| Ruby segmentation | [Doublevil/JmdictFurigana](https://github.com/Doublevil/JmdictFurigana) | CC BY-SA 4.0 |
| Example sentences | [Tatoeba](https://tatoeba.org/), via the JMdict examples build | CC BY 2.0 FR |

The join works because `yomitan-jlpt-vocab` carries a `jmdict_seq` column, so
levels attach to JMdict on the canonical entry identifier rather than on fuzzy
surface matching.

Full attribution is generated into [`NOTICE.md`](../NOTICE.md) from
[`data/sources.yml`](../data/sources.yml); CI fails if the committed copy is
stale.

**Licensing, in one line:** the code is MIT, the data is CC BY-SA 4.0. A
permissive code licence does not relicense the data, and no copyright is
claimed over JMdict-derived content.

Note that several popular JLPT word lists on GitHub are stamped MIT while
their own READMEs admit the data came from Waller's CC BY lists. They cannot
relicense it, so the MIT stamp buys nothing and the provenance chain is
unclear. This project uses the one source that states its provenance honestly.

## Rebuilding the corpus

```sh
make fetch-sources   # ~26 MB compressed, into data/raw (gitignored)
make import          # writes data/vocabulary/*.json
make validate
git diff --stat data/vocabulary   # review before committing
```

`data/raw` is deliberately not committed: it is large, and the canonical
corpus is what this repository redistributes. CI never downloads it, so an
upstream change can only reach the corpus through a reviewed commit.

There is also a 25-word committed demo corpus for exercising the pipeline
without any download — see [`data/demo/README.md`](../data/demo/README.md).

## The canonical model

One pretty-printed JSON array per level, NFC-normalised, stable-sorted by ID.

```json
{
  "id": "jlpt-waller:1290390-ba0a50",
  "surface": "混雑",
  "reading": "こんざつ",
  "ruby_segments": [
    { "base": "混", "reading": "こん" },
    { "base": "雑", "reading": "ざつ" }
  ],
  "glosses": ["confusion", "congestion", "jam", "crowding"],
  "display_gloss": "crush",
  "part_of_speech": ["noun", "suru verb"],
  "jlpt": { "level": "N3", "source_id": "jlpt-waller", "confidence": "community-estimated" },
  "example": {
    "ja": "その道は車で混雑している。",
    "en": "The roads are jammed with cars.",
    "focus_form": "混雑",
    "source_ref": "tatoeba:82333"
  },
  "source_refs": [
    { "source_id": "jlpt-waller", "source_entry_id": "1290390" },
    { "source_id": "jmdict", "source_entry_id": "1290390" },
    { "source_id": "jmdict-furigana", "source_entry_id": "1290390" }
  ],
  "status": "active",
  "notes": null
}
```

`glosses` stays faithful to the source; `display_gloss` is the one concise
phrase that goes on screen. Limits are 60 characters recommended, 90 hard.
Example sentences: 50 / 80 for Japanese, 100 / 160 for English.

### Identifiers

`<source>:<source entry id>-<6 hex digits of sha256(surface \0 reading)>`

A source key is not one-to-one with a learnable word: JMdict files 会う and
遭う under entry 1198180, and the level lists place them at N5 and N2. They are
two words to a learner and must be two records. The digest disambiguates them
without making the identifier volatile — it is computed from surface and
reading alone, so glosses, examples and level changes never renumber the
corpus and therefore never reshuffle the daily rotation.

## Adding a source

The generic adapters take their column mapping from configuration, so a new
CSV or JSON source usually needs no code:

```yaml
sources:
  - id: my-source
    type: csv
    path: data/raw/vocabulary.csv
    encoding: utf-8-sig
    mapping:
      source_entry_id: id
      surface: word
      reading: kana
      level: jlpt_level
      gloss: meaning
      example_ja: example_japanese
      example_en: example_english
```

See `config/sources.example.yml`. JSON sources use dotted paths
(`sense.0.gloss.0.text`). A source needing real logic gets a Python adapter in
`kotoba/sources/` that yields `RawRecord`s — `jlpt_jmdict.py` is the worked
example.

Whatever the source, add it to `data/sources.yml` first: validation rejects any
entry whose `source_refs` point at an undeclared source.

## Furigana review

Entries the aligner cannot resolve are written with `status: disabled` and
listed in `data/review/furigana-review.md`. Disabled entries never reach a
device and never enter the generated site. To fix one, add its segmentation to
`data/overrides/furigana.yml`:

```yaml
overrides:
  jlpt-waller:1234567-abc123:
    - base: 明白
      reading: あからさま
```

Re-run `make import`. The override takes precedence over both the source
segmentation and the aligner, the ID does not change, and the entry becomes
active again.

The current corpus has no unresolved entries: JmdictFurigana covers 7,231 of
them directly and the aligner resolves the rest unambiguously.

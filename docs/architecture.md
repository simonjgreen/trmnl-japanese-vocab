# Architecture

## Components

```mermaid
flowchart LR
    A[Licensed source files<br/>data/raw, gitignored] --> B[Import adapters]
    B --> C[Canonical vocabulary JSON<br/>data/vocabulary]
    C --> D[Validation and furigana checks]
    D --> E[Deterministic daily schedule]
    E --> F[Static date-specific JSON]
    F --> G[GitHub Pages]

    H[Liquid views and settings.yml<br/>src/] --> I[trmnlp lint / build]
    I --> J[GitHub Actions: trmnlp push]
    J --> K[TRMNL private plugin]

    K -->|polling URL: level + local date| G
    K --> L[TRMNL render service]
    L --> M[TRMNL device]
```

Two independent pipelines meet only at the device:

- **Data** is imported locally, reviewed, committed, then built and deployed
  to GitHub Pages by `pages.yml`.
- **Plugin code** is linted and pushed to TRMNL by `trmnl.yml`.

A failure in one leaves the other's last good state intact.

## Why the plugin is not "Liquid executed from GitHub"

TRMNL does not fetch Liquid from a repository at render time. The private
plugin holds its own copy of the templates and settings, which is why they have
to be *pushed*. GitHub is the source of truth (see
[ADR 4](adr/0004-github-source-of-truth.md)); `trmnlp push` is how that truth
reaches TRMNL.

## Data flow, stage by stage

1. **Fetch** — `scripts/fetch_sources.py` downloads three upstream files into
   `data/raw`. This is the only network step and it never runs in CI.
2. **Import** — `kotoba import` reads them through an adapter, normalises,
   deduplicates, resolves furigana, applies overrides, and writes
   `data/vocabulary/n{5..1}.json` stable-sorted by ID.
3. **Review** — the canonical diff is inspected by a human and committed.
   Anything the aligner could not resolve is written `disabled` and listed in
   `data/review/furigana-review.md`.
4. **Validate** — `kotoba validate` checks schemas, provenance, furigana
   consistency and length limits.
5. **Build** — `kotoba build-site` writes one payload per level per date, plus
   a manifest, a health file and an index page.
6. **Deploy** — `pages.yml` uploads the site; `trmnl.yml` pushes the plugin.

CI never reaches out to a vocabulary source, so a build is reproducible and an
upstream change can never alter the corpus without a reviewed commit.

## The static API contract

```
https://<owner>.github.io/<repo>/api/v1/daily/<level>/<YYYY-MM-DD>.json
```

The plugin composes this from the `data_base_url` and `jlpt_level` fields and
the device's offset-adjusted local date:

```liquid
{{ data_base_url }}/daily/{{ jlpt_level }}/{{ "now" | date: "%s" | plus: trmnl.user.utc_offset | date: "%Y-%m-%d" }}.json
```

`"now" | date: "%s"` gives a UTC epoch; adding `trmnl.user.utc_offset` shifts it
to the device's wall clock before the date is formatted. The word therefore
turns over at local midnight, and it changes only once per day, so a forced
refresh returns the same word.

This matters more than it looks. Without the offset, a device in the UK would
show the previous day's word from 23:00 to midnight every night through
British Summer Time. `tests/test_local_date.py` reproduces the Liquid
arithmetic against a real timezone database and sweeps every hour across both
2026 UK daylight-saving transitions, plus a half-hour-offset zone
(Asia/Kathmandu) to catch integer-hour assumptions.

A payload is a **deck** — the day's cards for that level and every easier one:

```json
{
  "schema_version": "2.0",
  "date": "2026-08-09",
  "level": "n3",
  "level_display": "N3",
  "dataset_version": "2026.08.1+1a2b3c4d",
  "selection_version": "1",
  "deck": { "size": 50, "slot_seconds": 600, "pool": 3054 },
  "words": [
    {
      "id": "jlpt-waller:1361140-4a1b2c",
      "surface": "拾う",
      "reading": "ひろう",
      "ruby_segments": [
        { "base": "拾", "reading": "ひろ" },
        { "base": "う", "reading": null }
      ],
      "display_gloss": "to pick up",
      "level": "N4",
      "example": {
        "ja": "床からペンを拾って下さい。",
        "en": "Please pick up the pen from the floor."
      },
      "display": { "word_size": "short", "example_size": "normal" },
      "sequence": { "position": 1840, "total": 3054 }
    }
  ]
}
```

The template picks one card from `words` using the clock:

```liquid
{% assign index = "now" | date: "%s" | divided_by: deck.slot_seconds | modulo: deck_size %}
```

so the file for a date is immutable and cacheable while the screen still
changes every `slot_seconds`. See
[ADR 6](adr/0006-flash-cards-from-a-daily-deck.md).

Note `level` on each card: a deck is cumulative, so an N3 learner sees N5 and
N4 words too, and the title bar shows which.

Constraints: UTF-8, Japanese left unescaped so a human can read the file,
minified in the deployed site, no HTML anywhere, and a hard 32 KB ceiling per
payload. Real payloads are around 20 KB. That ceiling is ours, not TRMNL's —
the payload is fetched by TRMNL's render service, never by the device.

Also served, for inspection and monitoring only:

| Path | Purpose |
| ---- | ------- |
| `api/v1/manifest.json` | dataset version, commit, counts, date coverage |
| `health.json` | small operational summary |
| `api/v1/daily/<level>/latest.json` | the newest generated payload |
| `api/v1/daily/<level>/sample.json` | today's payload, pretty-printed |
| `index.html` | landing page and public attribution surface |

The plugin must always request a date-specific path. `latest.json` is the end
of the ten-year horizon, not today.

## Sizing decided at build time

`word_size` and `example_size` are computed during the build from an estimated
display width, not from byte length: kana and kanji count as one full-width
unit, Latin characters as roughly half. A segment contributes whichever of its
base or its ruby is wider, so a single kanji carrying a five-kana reading
(承る / うけたまわる) is correctly treated as wide. The renderer then only has to
map a class name to a size.

## Failure modes

| What breaks | What happens |
| ----------- | ------------ |
| Pages build fails | The previous deployment stays live; existing dates keep working. |
| Weekly schedule stops | Nothing, for years. The horizon shortens; `health.json` shows how far it reaches. |
| TRMNL push fails | The installed plugin is unchanged. Data is unaffected. |
| A bad vocabulary entry | Validation fails the build. A partial site is never published. |
| The current date is missing | A deployment incident. See the troubleshooting section of the README. |

The plugin deliberately does not fall back to a different date. A wrong word
presented as today's word is worse than a visible failure.

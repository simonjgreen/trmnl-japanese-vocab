# 6. Flash cards as one file per time slot

**Status:** accepted (2026-08-09), supersedes the date-based API in
[ADR 1](0001-static-pages-data-api.md)

## Context

The plugin shipped as a word of the day. Feedback from the person using it was
that vocabulary practice does not work that way: she wanted a new word on
**every** refresh, and wanted a level to include everything below it rather
than one narrow band.

## The constraint that decided the design

A first attempt shipped a *deck* of fifty cards in each per-date payload and
picked one in the template from the current timestamp. It was elegant, it
tested green, and it did not work. TRMNL's own activity log said why:

```
16:58:15  Render  —  Render skipped — no change in data
16:43:27  Render  —  Render skipped — no change in data
```

**TRMNL hashes the polled payload and skips rendering when it is unchanged.**
The template never runs again, so a card chosen in Liquid can never change. A
per-date payload renders exactly once a day no matter how clever the markup.

This is the sort of thing no amount of local testing surfaces: `trmnlp` renders
whenever asked, so the deck rotated perfectly in preview and froze on the
device.

## Decision

Put the slot in the **URL** so the payload itself differs:

```
/api/v1/card/<level>/<slot>.json

slot = floor(now / 600) mod 4096
```

Each file holds exactly one card. Consecutive slots are different bytes, so
TRMNL sees changed data and re-renders. 4096 slots of ten minutes is a
28-day cycle, 20,480 files, 12 MB.

The slot length is ten minutes against TRMNL's fifteen-minute maximum refresh
rate. Slot ≤ render interval is the invariant that matters: if a slot outlasted
the interval, two renders could fall inside one slot, the payload would repeat,
and the screen would freeze again. A test asserts it.

Levels are **cumulative** — N3 means N5 + N4 + N3. Each card carries its own
level, and the title bar lists the range with the current one underlined.

## Consequences

- **No dates in the URL, so the API cannot run out of coverage.** The rolling
  horizon, the weekly build that kept it moving, and the whole class of "the
  device asked for a date that was never generated" failures are gone. The
  weekly rebuild now only advances the rotation.
- Payloads are back to ~700 bytes.
- The template got simpler: `word` arrives ready-made and nothing is chosen at
  render time.
- The two constants in the polling URL are duplicated from `config/build.yml`
  because a Liquid modulo needs literals. A test asserts they agree; if they
  drift, the plugin requests slots that were never generated.
- Within one 28-day cycle a level shows at most 4096 distinct cards. For N5
  through N2 that is the whole pool and more; for N1 (8289 words) it is about
  half, and the rotation offset advances with the build date so later builds
  cover the rest.

## Alternatives considered

**A deck in the payload, card chosen in Liquid.** What was built first. Broken
by the skip-on-unchanged-data behaviour above.

**Cache-busting query string on a per-date URL.** The URL would differ but the
returned bytes would not, and the dedupe is on content.

**TRMNL Serverless.** Would solve it directly and is the honest answer if this
ever needs per-user state such as "I know this word". Still more runtime than
this problem requires.

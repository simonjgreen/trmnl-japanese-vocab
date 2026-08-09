# 6. Flash cards from a daily deck

**Status:** accepted (2026-08-09), supersedes part of
[ADR 1](0001-static-pages-data-api.md)

## Context

The plugin shipped as a word of the day: one word per level per date, one tiny
JSON per date. Feedback from the person actually using it was that this is not
how vocabulary practice works — she wanted a new word on **every** refresh,
like flash cards, and wanted a level to include everything below it rather
than one narrow band.

Both requests break assumptions the original design was built on.

## The problem

A static file cannot vary per fetch. The polling URL is a date, GitHub Pages
returns the same bytes to every request, and there is no server to ask for
"the next one".

## Decision

Ship a **deck** in each daily payload and choose the card in the template from
the current timestamp:

```liquid
{% assign index = "now" | date: "%s" | divided_by: deck.slot_seconds | modulo: deck_size %}
{% assign word = words[index] %}
```

Fifty cards per day, one slot every ten minutes. The file for a date stays
immutable and cacheable; which card is on screen changes as the clock moves.
A refresh inside the same slot redraws the same card, so the screen is settled
rather than jittery.

Decks are drawn from the same deterministic shuffled stream as before — day
*d* takes positions `d × 50` to `d × 50 + 49` — so the no-repeat guarantee
survives intact: every word at the level appears once before any repeats. That
was verified at exactly position 3054 for an N3 pool of 3054.

Levels are now **cumulative**: N3 means N5 + N4 + N3. The spec anticipated
this as a possible `target_and_easier` setting; it is now simply the
behaviour, because a learner revises downwards and a band-limited deck throws
away everything already learned the moment the level is raised. Each card
carries its own level, and the title bar shows it — `N3 · N4` — so it is
obvious where a word sits.

## Alternatives considered

**One file per time slot.** `deck/n3/<slot>.json`, slot from the clock. Truly
one word per file, but the modulo divisor is the deck size, which differs per
level and changes with the corpus — and it has to be a literal in the polling
URL. Fixing a uniform slot count instead meant either tens of thousands of
files or starving the larger levels.

**TRMNL Serverless.** Would solve it directly, and is the honest answer if
this ever needs per-user state such as "I know this word". Still more runtime
than the problem requires.

**Random selection in Liquid.** There is no RNG in Liquid, and there should
not be: a random card per render would repeat and skip unpredictably.

## Consequences

- Payloads grow from ~600 bytes to ~20 KB. This costs the device nothing —
  TRMNL's server does the fetching — but it does trade against the date
  horizon, which drops from ten years to one. A year of missed weekly builds
  is still a wide margin.
- The site is ~37 MB across 1,900 files, down from 18,705 files.
- `refresh_interval` drops from 1440 to 10 minutes so TRMNL re-renders once
  per slot. A test asserts the two stay consistent.
- The payload schema goes to 2.0: `word` and `sequence` are replaced by
  `words[]` and `deck`.
- The manifest now reports two counts per level: `active_entries` (what the
  corpus holds at that level) and `deck_pool` (what a learner there can be
  shown).

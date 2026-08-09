# 3. Deterministic shuffled cycles

**Status:** accepted (2026-08-09)

## Context

The learner should see one word per day, the same word all day however often
the screen refreshes, and should not see repeats until they have worked
through the level.

## Decision

Sort the level's active entries by ID, split the timeline into cycles of N
days, and shuffle each cycle deterministically. Day *d* since the epoch gives
`cycle, offset = divmod(d, N)`; the answer is `permutation(cycle)[offset]`.

The shuffle is a SHA-256-derived 64-bit seed driving a SplitMix64 generator
through an explicit Fisher-Yates pass. All three are written out in full in
`kotoba/selection.py`.

## Alternatives considered

**`random.shuffle` with a seed.** Rejected. The algorithm behind it is an
implementation detail, so a Python upgrade could silently reshuffle every
future date.

**Hash the date to an index.** Rejected. It gives repeats and gaps: some words
would appear three times in a cycle and others never.

**Store a cursor and advance it.** Rejected. That is state, and state means a
database.

## Boundary repeats

The naive fix — rotate the next cycle if it opens with the previous cycle's
last word — is recursive, because whether the previous cycle was rotated
depends on the one before it, without end. Instead the first two positions are
swapped, which for three or more words leaves the final position untouched.
The last word of a cycle is therefore always the raw shuffle's last word, the
rule depends only on two adjacent shuffles, and the guarantee is exact.

Two special cases: with one word there is nothing to alternate with, and with
two words the only repeat-free sequence is a fixed alternation.

## Consequences

- Same level and date always give the same word, in any process, on any
  Python version.
- Every word appears exactly once per cycle; none repeats within a cycle or
  across a boundary.
- Levels have independent schedules.
- Changing the corpus changes future assignments. This is unavoidable — the
  cycle length is the corpus size — and is why `selection_version` exists and
  why entry IDs are derived from lexical identity rather than list position.

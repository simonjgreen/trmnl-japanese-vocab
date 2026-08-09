# 2. Precomputed ruby segments, not runtime inference

**Status:** accepted (2026-08-09)

## Context

The whole point of this plugin is furigana positioned over the kanji it
belongs to — と over 取 and のぞ over 除 in 取り除く, with nothing over り or
く. Getting that wrong is worse than showing no furigana at all, because it
teaches the learner an incorrect reading.

## Decision

Resolve the segmentation once, during import, and ship it in the payload as a
list of `{base, reading}` segments. The renderer iterates the list and does no
inference of any kind.

Segmentation comes from three sources, in order of precedence:

1. an explicit override in `data/overrides/furigana.yml`;
2. the JmdictFurigana dataset, which is hand-checked and covers jukujikun such
   as 明白 / あからさま that cannot be derived from surface and reading;
3. a conservative aligner, which refuses to guess.

## Alternatives considered

**Infer in Liquid at render time.** Rejected outright. Liquid has no facility
for this, and the failure mode is silent and wrong.

**Ship an HTML fragment in the payload.** Rejected. It would mean trusting
markup from the data file, and the templates would have to stop escaping.
Structured segments keep escaping unconditional.

**Always align automatically and accept the errors.** Rejected. The aligner
cannot know that 明白 is あからさま rather than めい+はく, and a plausible wrong
answer is the worst outcome here.

## Consequences

- The renderer cannot produce incorrect furigana from correct data.
- Every field remains escapable, so `raw` is never needed.
- An entry the aligner cannot resolve is written with `status: disabled` and
  listed in the review queue, so it never reaches a device and never silently
  disappears either.
- Fixing one is an override keyed by entry ID, which does not change the ID and
  therefore does not disturb the rotation.

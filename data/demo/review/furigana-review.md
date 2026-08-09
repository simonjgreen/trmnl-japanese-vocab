# Furigana review queue

Entries whose ruby segmentation could not be resolved automatically.
They are written to the corpus with `status: disabled` so they never
reach a device. Add a segmentation to `data/overrides/furigana.yml`
keyed by the entry ID, re-run `make import`, and the entry becomes
active again without its ID changing.

Nothing to review.

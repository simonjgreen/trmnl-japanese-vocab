# Demo corpus

**This is a demonstration dataset, not the production corpus.**

Twenty-five words, five per level, written by hand so that a fresh clone can
run the entire pipeline — import, validate, build, render — without first
downloading around 135 MB of dictionary data.

The level assignments here are illustrative only. They are *not* the
community-estimated assignments used by the real corpus, and they should not
be relied on for study.

To build it:

```sh
make import-demo
```

That writes canonical JSON to `data/demo/vocabulary/`, deliberately separate
from `data/vocabulary/` so it can never overwrite the real corpus.

The production corpus is built with `make fetch-sources && make import`; see
`docs/data-sourcing.md`.

# 5. Where source attribution lives

**Status:** accepted (2026-08-09)

## Context

The corpus derives from JMdict, whose EDRDG licence asks that usage and source
be acknowledged in documentation, publicity material and the project website,
with links to the licence. It adds that "if a WWW server is providing a
dictionary function or an on-screen display of words from the files, the
acknowledgement must be made on each screen display."

The plugin's visual brief is the opposite: one large word on a sparse screen,
explicitly no extra metadata.

## Decision

Attribution is carried in `README.md`, in the generated `NOTICE.md`, on the
GitHub Pages index — which is the public face of the data service — and in the
plugin's own description. It is not printed on the device screen.

## Reasoning

The per-screen clause is aimed at a dictionary service, where a user looks up
arbitrary words and the display *is* the product. This plugin is closer to the
app case the same licence section addresses, where acknowledgement in the
documentation and an about/source surface is what is asked for. The Pages site,
which is the thing actually serving JMdict-derived content over HTTP, carries
full attribution on its landing page.

This is a judgement call and it is recorded here so that it is a decision
rather than an oversight. Anyone uncomfortable with the reading can add a
credit line to the title bar; the cost is a small loss of sparseness.

## Consequences

- The screen stays sparse, matching the visual brief.
- Attribution is present everywhere a person or a licence audit would look.
- `NOTICE.md` is generated from `data/sources.yml`, and CI fails if the
  committed copy is stale, so attribution cannot silently drift from the data.

# 1. Date-specific static JSON on GitHub Pages

**Status:** accepted (2026-08-09)

## Context

The plugin needs one deterministic word per level per local calendar day, on a
device that polls an HTTP endpoint. The constraints ruled out an always-on
application server, a database, an account system, a paid API and any runtime
scraper.

## Decision

Generate one small JSON document per level per date at build time and serve the
result as a static site from GitHub Pages. The plugin builds its polling URL
from its selected level and the device's offset-adjusted local date.

## Alternatives considered

**Poll the whole vocabulary list and select in Liquid.** Rejected. It would
push several megabytes through the merge variables on every refresh, and
selection logic in Liquid cannot be unit-tested. Liquid also has no
deterministic RNG, so "the same word all day" would have to be faked from the
date anyway.

**TRMNL Serverless.** Rejected for version 1. It would work, but it introduces
a runtime the rest of this design does not need, and it makes the exact payload
for a given date harder to inspect. Worth revisiting if the plugin ever needs
per-user state, which is explicitly out of scope.

**A small hosted API.** Rejected. It is an always-on service to run, monitor
and pay for, in exchange for nothing this use case needs.

## Consequences

- Each payload is under 1 KB, and the whole site is around 15 MB.
- The payload changes each day, which is what gives TRMNL a reason to redraw.
- Any date's payload can be opened in a browser, which makes support easy.
- Date-specific URLs are immutable and therefore trivially cacheable.
- The build emits roughly 18,700 files. That is fine for Pages but it does
  make the deployment artefact large; the count is proportional to the date
  horizon, which is configurable.
- Coverage is finite. A ten-year future horizon plus a weekly rebuild means a
  broken schedule degrades slowly rather than taking devices offline.

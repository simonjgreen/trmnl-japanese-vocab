# 4. GitHub is the source of truth

**Status:** accepted (2026-08-09)

## Context

TRMNL private plugins can be edited in the browser. This repository also holds
the plugin definition. Two editable copies of the same thing will diverge.

## Decision

The repository is authoritative. Changes are made here, reviewed, merged to
`main`, and pushed to TRMNL by `trmnlp push` in CI.

The TRMNL browser editor is for debugging only. Anything changed there is
either pulled back with `trmnlp pull` and committed immediately, or discarded.

## Alternatives considered

**TRMNL GitHub Sync as the primary path.** Rejected as primary, documented as
optional. It commits TRMNL UI saves back to GitHub, but the GitHub-to-TRMNL
direction is surfaced for manual import rather than applied automatically, so
it cannot replace `trmnlp push` in an automated pipeline. Enabling both is a
good way to get a merge conflict between a UI save and a merge commit.

**Edit in the TRMNL UI and treat the repo as a backup.** Rejected. It gives up
review, testing and history for the sake of a text box.

## Consequences

- One place to change things, with review and CI.
- Deployment is gated on a committed plugin `id`, so CI updates the existing
  plugin instead of creating a new one on every run. Bootstrapping is a
  deliberate one-off, performed locally.
- The plugin `id` is committed and is not a secret. `TRMNL_API_KEY` is a
  repository Actions secret and is never exposed to pull-request builds.
- Pages deployment and TRMNL deployment are independent, so a failure in one
  leaves the other's last good state in place.

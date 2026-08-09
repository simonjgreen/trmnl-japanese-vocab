# Contributing

## Getting set up

```sh
make setup
make check
```

`make check` runs validation, the tests, a site build, API validation and an
HTML render of every fixture. It needs no network and no Docker.

For PNG renders you also need Docker:

```sh
make trmnlp-image
make render-fixtures
```

## Vocabulary corrections

Please open a
[vocabulary correction issue](.github/ISSUE_TEMPLATE/vocabulary-correction.yml)
rather than editing `data/vocabulary/*.json` directly — those files are
generated, and a hand edit is lost at the next import.

Corrections to **readings, glosses and furigana** are clear-cut and welcome.

**Level reassignments** are not. The lists are community estimates with no
official specification behind them, so "this is really N2" is an opinion. It
may still be a good opinion; just expect it to be discussed rather than
merged.

Anything you contribute must be redistributable. Do not paste in material from
JLPT examination papers or commercial workbooks, and if a correction comes
from another dataset, say which and under what licence.

### Fixing furigana

Add an override keyed by the entry ID:

```yaml
# data/overrides/furigana.yml
overrides:
  jlpt-waller:1234567-abc123:
    - base: 明白
      reading: あからさま
```

Then `make import && make validate`. The override beats both the source
segmentation and the automatic aligner, and the entry ID does not change.

## Code changes

- Tests come first for anything with logic in it. The furigana aligner and the
  selection algorithm have thorough suites; follow their lead.
- British English in comments and documentation.
- Comments should explain *why*. The code already says what.

### Changing Liquid or CSS

Two things to know.

`trmnlp lint` caps the total occurrences of `font-size`, `margin`, `padding`,
`text-align`, `justify-content` and a few other properties at **six across all
markup**, and forbids `opacity`. That is why sizes are custom properties,
spacing is flex `row-gap`, and greys use `text--gray-*`. Run `make lint-plugin`
before pushing.

Visual changes need a human to look at them. Run `make render-fixtures`,
check the output against the checklist in
[docs/visual-design.md](docs/visual-design.md), and say in the pull request
what you looked at. Golden-image comparison is deliberately not a gate,
because CJK font fallback varies between machines.

### Changing the corpus or the selection algorithm

Both change which word appears on which future date. That is expected and
unavoidable — the rotation length is the corpus size — but it should be
deliberate. If you are changing the *algorithm* rather than the data, bump
`selection_version` in `config/selection.yml` so the change is visible in
every payload.

Never change an entry ID to fix a gloss. IDs are derived from surface and
reading precisely so that editorial improvements do not reshuffle the
rotation.

## Adding a vocabulary source

The generic CSV and JSON adapters are configuration-driven, so most sources
need no code — see `config/sources.example.yml` and
[docs/data-sourcing.md](docs/data-sourcing.md). A source needing real logic
gets a Python adapter in `kotoba/sources/` that yields `RawRecord`s.

Whichever it is, declare the source in `data/sources.yml` first with its
licence and attribution, and regenerate `NOTICE.md` with `make notice`. CI
fails if the committed `NOTICE.md` is stale, and validation rejects entries
referencing an undeclared source.

## Pull requests

CI must be green: validation, tests, site build and validation, `trmnlp lint`,
and a successful render of every fixture in every layout. Renders and the
build manifest are uploaded as artefacts.

CI runs without any secrets, so pull requests from forks work normally and
cannot reach the deployment credentials.

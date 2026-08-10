# Security

## Reporting a vulnerability

Please report privately through GitHub's
[private vulnerability reporting](https://github.com/simonjgreen/trmnl-japanese-vocab/security/advisories/new)
rather than opening a public issue.

Include what you found, how to reproduce it, and what you think the impact is.
You should get an acknowledgement within a week. This is a hobby project
maintained in spare time, so please be patient with fixes; genuinely serious
issues will be prioritised.

## What this project handles

Very little, by design.

- **No personal data.** The plugin receives only TRMNL's own configuration and
  the device's current UTC offset. Neither is stored or transmitted anywhere.
- **No user identifiers on the data site.** Nothing about a name, account,
  device or time zone is written to the Pages output or its logs.
- **Identical payloads for everyone.** The file served for a given level and
  date is the same for all users, so requests reveal nothing beyond a level
  and a date.
- **No analytics, no tracking pixels, no third-party scripts.**
- **No JavaScript in the plugin**, and no runtime fetches from markup.
- **No always-on service** to compromise: the data is static files on GitHub
  Pages.

## Secrets

| Name | Where it lives | Secret? |
| ---- | -------------- | ------- |
| Plugin `id` | `src/settings.yml`, committed | No |
| `TRMNL_API_KEY` | GitHub Actions secret, or a local `trmnlp` credential | **Yes** |

`TRMNL_API_KEY` is used only by `.github/workflows/trmnl.yml`, which runs on
pushes to `main` and on manual dispatch. `ci.yml` — the workflow that runs on
untrusted pull requests — reads no secrets at all, and no workflow uses
`pull_request_target`. The key is never written to logs, artefacts or the
Pages site.

If you think the key has leaked, rotate it in your TRMNL account settings and
update the repository secret. The plugin id does not need rotating.

## Injection

Vocabulary data is treated as untrusted even though it comes from curated
dictionaries:

- Every data-derived value is passed through Liquid's `escape` filter.
- `raw` and `markdown_to_html` are not used anywhere.
- Validation rejects `<` or `>` in any text field, so markup cannot enter the
  corpus in the first place.
- Payloads carry structured ruby segments, never HTML fragments, so the
  renderer never has a reason to trust markup from the data.

Import adapters run locally, never in a job that has deployment secrets
available.

## Dependencies

Runtime dependencies are three well-known Python libraries (PyYAML,
jsonschema, and referencing, which jsonschema pulls in anyway). Dependabot
tracks GitHub Actions, pip and Docker updates weekly.
The upstream `trmnl/trmnlp` image in `Dockerfile.trmnlp` is pinned by digest,
not by tag, because the deploy job runs a container built from it with
`TRMNL_API_KEY` in scope; Dependabot proposes updates to that pin so it stays
current without being able to change under us unreviewed.

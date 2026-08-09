# Deployment

Three paths. The first is the recommended one; the others exist for people who
want less automation or a different workflow.

## 1. Repository plus `trmnlp` CI (recommended)

### Once, to set up

1. **Create the GitHub repository.** Public is easiest: the code and the
   vocabulary payloads are not sensitive, and the Pages endpoint has to be
   anonymously reachable by TRMNL. A private repository needs a paid plan for
   Pages, and the Pages site is public either way.

2. **Clone it and configure the endpoint.**

   ```sh
   git clone https://github.com/<owner>/<repo>.git
   cd <repo>
   make setup
   python scripts/configure_repo.py        # detects owner/repo from git
   ```

   This rewrites the placeholder `data_base_url` in `src/settings.yml`. It is
   idempotent, and it refuses to overwrite a custom endpoint unless you pass
   `--force`.

3. **Build the corpus** (or keep the committed one).

   ```sh
   make fetch-sources
   make import
   make validate
   ```

4. **Check it locally.**

   ```sh
   make test
   make render-fixtures     # look at dist/renders/
   make preview             # http://localhost:4567
   ```

5. **Push to GitHub.**

6. **Turn on Pages.** Settings → Pages → Source: **GitHub Actions**. Not
   "Deploy from a branch" — the site is generated, not committed.

7. **Run the Pages workflow** (Actions → Pages → Run workflow) and wait. Then
   check:

   ```sh
   curl https://<owner>.github.io/<repo>/api/v1/manifest.json
   curl https://<owner>.github.io/<repo>/api/v1/daily/n5/$(date +%F).json
   ```

   Both must return JSON. The daily URL must exist for *today*.

8. **Authenticate with TRMNL and create the plugin.**

   ```sh
   bin/trmnlp login     # opens a browser; stores a token locally
   bin/trmnlp push      # creates the private plugin, prints its id
   ```

9. **Commit the plugin id.** Add it near the top of `src/settings.yml`:

   ```yaml
   id: 123456
   ```

   The id is **not** a secret. Committing it is what stops CI creating a new
   plugin on every run — `trmnl.yml` fails with a bootstrap message if it is
   missing.

10. **Add the API key as a repository secret.** Settings → Secrets and
    variables → Actions → New repository secret, named `TRMNL_API_KEY`. Get
    the value from your TRMNL account settings. This one *is* a secret, and it
    is never exposed to pull-request builds.

11. **Merge to `main`** and confirm the TRMNL workflow updates the existing
    plugin rather than creating another.

12. **Configure the plugin in TRMNL.** Open it, pick the learner level, check
    the data endpoint, force a refresh once, and add it to a playlist.

### From then on

Edit here, open a pull request, let CI run, merge. `pages.yml` redeploys the
data when `data/`, `schemas/`, `kotoba/` or `config/` change; `trmnl.yml`
redeploys the plugin when `src/` changes. A weekly scheduled Pages build rolls
the date horizon forward.

## 2. Manual ZIP import

For anyone who does not want CI touching their TRMNL account.

```sh
make package        # writes dist/kotoba-plugin.zip
```

The archive is flat — `settings.yml` and the Liquid views at the root, no
directory prefix, which is what TRMNL's importer expects. In TRMNL: Plugins →
Private Plugin → Import, then set the learner level and confirm the data
endpoint.

You still need the data API somewhere. Either deploy Pages as above, or point
`data_base_url` at any static host serving the same layout.

## 3. TRMNL GitHub Sync (optional, and not a replacement)

GitHub Sync can connect a private plugin to this repository and commit TRMNL
UI saves back to GitHub. Useful if you like editing in the browser.

It does **not** replace `trmnlp push`: the GitHub-to-TRMNL direction is
surfaced for manual import rather than applied automatically, so it cannot
close the loop on its own.

**Do not edit both sides casually.** Pick one direction and stick to it. If
you do change something in the TRMNL editor while debugging, either
`bin/trmnlp pull` it back and commit immediately, or discard it. See
[ADR 4](adr/0004-github-source-of-truth.md).

## Secrets

| Name | Where | Secret? |
| ---- | ----- | ------- |
| Plugin `id` | `src/settings.yml`, committed | No |
| `TRMNL_API_KEY` | GitHub Actions secret, or local `trmnlp` credential | **Yes** |

The key is used only by `trmnl.yml`, which runs on `main` and on manual
dispatch. `ci.yml` reads no secrets at all, so a pull request from a fork
cannot reach it. Nothing writes the key to logs, artefacts or Pages.

## Rollback

**Plugin.** Revert the commit and merge; `trmnl.yml` pushes the previous
version. For something urgent, `bin/trmnlp push` from a known-good checkout.

**Data.** Revert the offending commit to `data/vocabulary` and let `pages.yml`
rebuild. Until it finishes, the previous deployment stays live — a failed build
does not take the old site down.

Note that reverting corpus changes also reverts future word assignments, since
the cycle length is the corpus size. That is expected; see
[ADR 3](adr/0003-deterministic-cycle-selection.md).

## Diagnostics

**The screen says "Vocabulary unavailable".** A payload was rendered but had no
word. Check the resolved URL and look at the JSON.

**The screen is blank or stale.** Usually a 404 — the plugin got no payload at
all. An HTTP error cannot be rendered as the empty state, so this is the shape
a missing date takes. Work through:

```sh
# 1. Is the site deployed and how far does it reach?
curl https://<owner>.github.io/<repo>/health.json

# 2. Does today's file exist for the selected level?
curl -i https://<owner>.github.io/<repo>/api/v1/daily/n3/$(date +%F).json

# 3. What does the plugin think it is requesting?
#    TRMNL plugin page -> the resolved polling URL is shown there.
```

Then check, in order:

- Is Pages enabled with "GitHub Actions" as the source?
- Did the last Pages run succeed? (Actions → Pages)
- Does `manifest.json` cover today's date?
- Does `data_base_url` match your Pages URL, with no trailing slash?
- Is the device's time zone right? The URL uses the device's local date, so a
  misconfigured zone asks for the wrong day.

**A word looks wrong.** `kotoba inspect --level n3 --date 2026-08-09` shows
exactly what the build would produce, including the ruby segmentation.

**The plugin deploy fails with "No plugin id committed".** Step 9 above.

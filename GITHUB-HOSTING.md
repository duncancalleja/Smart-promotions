# Hosting this dashboard on GitHub (for Bolt employees)

This repo includes a GitHub Actions workflow (`.github/workflows/publish-pages.yml`) that:

- runs **every Monday** (and on-demand),
- builds `site/` (bad orders + Smart Promotions from Databricks; calculator + Smart Promotions ROI copied from `docs/`; hub),
- deploys it to **GitHub Pages**.

## Safe-by-default behavior

When `PUBLISH_LIVE_DASHBOARD` is **not** set to `true`, the workflow publishes a **safe public landing page** that contains **no production data**.

This is the recommended mode for a **public** repo / public Pages site.

Even if `PUBLISH_LIVE_DASHBOARD=true`, the workflow includes a guard that **refuses to publish the live dashboard when the repo visibility is public**.

## Critical: GitHub Pages visibility (public vs private)

If Bolt is on **GitHub Enterprise Cloud**, you can publish the Pages site **privately** so it’s only accessible to people with **read access to the repo** ([GitHub Docs: “Changing the visibility of your GitHub Pages site”](https://docs.github.com/en/pages/getting-started-with-github-pages/changing-the-visibility-of-your-github-pages-site)).

If you **cannot** publish Pages privately, then a Pages site may be publicly reachable on the internet — in that case, **do not publish raw order-level data** via Pages. Instead, either:

- host the code in GitHub and have users run it locally, or
- deploy via an internal hosting solution (or use a self-hosted runner + internal web hosting).

## One-time setup steps (recommended)

1. **Create a new repo** in the Bolt GitHub org.
2. Push this code to the repo (make sure you are not committing any tokens).
3. Enable Pages:
   - Repo **Settings** → **Pages**
   - Set **Build and deployment** to **GitHub Actions**
4. Trigger the workflow:
   - Repo → **Actions** → “Publish dashboards to GitHub Pages” → **Run workflow**

After the first deploy, GitHub will show a **Visit site** link in Settings → Pages.

## Enabling the LIVE dashboard (only when internal/private)

Only do this once the repo/Pages site is internal/private.

1. Add a **Repository Variable**:
   - **Name**: `PUBLISH_LIVE_DASHBOARD`
   - **Value**: `true`
2. Add a **Repository Secret**:
   - **Name**: `DATABRICKS_TOKEN`
   - **Value**: a Databricks SQL Warehouse token (prefer a service account / least-privilege token)

## What gets published

After deploy, these paths exist on the Pages site (replace `<base>` with your repo’s Pages root URL):

| Path | Content |
|------|---------|
| `<base>/` | Bad orders dashboard (Malta, `--year 2026`) |
| `<base>/smart-promo.html` | Smart Promotions — **built in CI** from Databricks each run (weekly + manual); not stored as a large blob in git |
| `<base>/smart-promo-roi.html` | Smart Promotions ROI — **static snapshot** committed as `docs/smart-promo-roi.html` (same idea as the calculator; refresh by rebuilding locally and committing) |
| `<base>/campaign-cost-calculator.html` | Campaign cost calculator (static from `docs/`) |
| `<base>/dashboards.html` | Short hub page linking to the dashboards above |

**Refreshing the ROI file on Pages:** from the repo root, with Databricks available locally:

```bash
python3 build_smart_promo_roi_dashboard.py --country-code mt --lookback-days 90 --output docs/smart-promo-roi.html
git add docs/smart-promo-roi.html && git commit -m "Refresh Smart Promotions ROI snapshot" && git push
```

Then run the Pages workflow (or wait for the weekly schedule). The site URL for ROI stays the same; visitors get the new snapshot after deploy.

If you want multiple countries, years, or ROI windows, use different filenames under `docs/` and extend the workflow `cp` lines.

## Exclusivity targeting — weekly boltable (Mac-off backup)

The workflow **`.github/workflows/exclusivity-weekly-boltable.yml`** rebuilds the Malta exclusivity dashboard from **live Databricks** and pushes to **https://mt-exclusivity-targeting.boltable.eu** every **Monday ~08:30 Malta** (also **Run workflow** on demand).

This complements the Mac **LaunchAgent** (`scripts/install_exclusivity_weekly_launchagent.sh`) so data stays fresh when your laptop is off.

### One-time setup

1. **Commit** the exclusivity dashboard sources to this repo (builder, templates, deploy scripts, `config/mt_delivery_market_share.json`).
2. **Repository secrets** (Settings → Secrets and variables → Actions):
   - **`DATABRICKS_TOKEN`** — Databricks SQL PAT (`sql` scope)
   - **`MT_PORTFOLIO_GH_TOKEN`** — fine-grained PAT with **`contents: write`** on **`boltable/mt-exclusivity-targeting`** (also enables **Save for team** in the dashboard)
3. **Actions → “Exclusivity targeting — weekly boltable” → Run workflow** to verify.

Manual CI run (same as the workflow):

```bash
export DATABRICKS_TOKEN=… MT_PORTFOLIO_GH_TOKEN=…
bash scripts/exclusivity_ci_refresh.sh
```

GetPlace / brands-by-platform columns stay empty in CI until an export exists (commit snapshot under `boltable/mt-exclusivity-targeting/public/getplace-brands.json` or add `~/Documents/Bolt food/mt_brands_by_platform.json` locally before deploy). Databricks metrics refresh regardless.

## Troubleshooting

- **Databricks blocks GitHub-hosted runners**: If the warehouse is IP-allowlisted, GitHub’s hosted runners may not be able to connect. Use a **self-hosted runner** inside Bolt’s network, or adjust allowlisting.
- **Token expiry**: If builds start failing, rotate `DATABRICKS_TOKEN` in repo secrets.


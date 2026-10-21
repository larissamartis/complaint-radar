# Complaint Radar

**Early-warning and compliance-risk system for financial-services complaints.** It ingests US CFPB complaints
every day, detects issues growing unusually fast per company, explains them with real example complaints,
scores which complaints are likely to end in relief for the customer, and tests whether complaint patterns
warn of regulatory enforcement in advance.

> Status: in development. Phase 1 (foundation: ingestion, data contract, local lake, dbt, CI) and
> phase 2 (daily pipeline into BigQuery on a GitHub Actions schedule) are complete.
> See [docs/design](docs/design/2026-10-21-complaint-radar-design.md) for the full design and
> [docs/data_exploration.md](docs/data_exploration.md) for what the data looks like.

## Why the design is "hybrid"

On 14 Aug 2026 the CFPB stopped publishing complaint narratives. The daily feed is now structured-only, and
the text survives in a frozen official archive (Dec 2011 to Aug 2026). Complaint Radar raises alerts from the
live structured feed and uses the archived text to explain them, discover topics and train text models.

## Quick start (Windows, PowerShell)

```powershell
# Python 3.13 via uv; the virtual environment lives outside the repo
$env:UV_PROJECT_ENVIRONMENT = "$env:USERPROFILE\.venvs\complaint-radar"
uv sync

# One-time: download the narratives archive (21 zips, ~1.43 GB) and load it into the local lake
uv run complaint-radar download-archive
uv run complaint-radar backfill-archive

# Build dbt models and run data tests on the local lake
$env:CR_LAKE_DIR = "$env:USERPROFILE\data\complaint-radar\lake"
$env:CR_DUCKDB_PATH = "$env:USERPROFILE\data\complaint-radar\lake\complaint_radar.duckdb"
uv run dbt build --project-dir dbt --profiles-dir dbt

# Unit tests
uv run pytest
```

Data lives in `%USERPROFILE%\data\complaint-radar` (override with `CR_DATA_DIR`) and never in the repo.

## Daily pipeline

`.github/workflows/daily.yml` runs every day at 11:30 UTC:

1. **Pre-check:** has the CFPB API's newest complaint date moved since the last good run? If not, record `no_new_data` and stop.
2. **Download** the official bulk snapshot (about 18.5M complaints, structured fields only).
3. **Normalise and contract-check** it. A schema change or rule violation stops the run before anything is loaded.
4. **Change capture:** keep only complaints in the 60-day hot window whose `(complaint_id, row_hash)` is not already in BigQuery. This captures both new complaints and status changes (e.g. "In progress" to "Closed").
5. **Append** those versions to BigQuery with a load job. The sandbox has no MERGE/UPDATE, so dbt views pick the latest version per complaint.
6. **dbt build** on BigQuery (views and tests), then record the run in `pipeline_runs`.

Re-running a day appends nothing. See [docs/runbook.md](docs/runbook.md) for what to do when a run fails and
[docs/results/phase2.md](docs/results/phase2.md) for the first runs.

```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = "$env:USERPROFILE\.secrets\complaint-radar-sa.json"
uv run complaint-radar run-daily              # normal daily run
uv run complaint-radar backfill --since 2026-10-01
```

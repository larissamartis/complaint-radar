# Complaint Radar

**Early-warning and compliance-risk system for financial-services complaints.** It ingests US CFPB complaints
every day, detects issues growing unusually fast per company, explains them with real example complaints,
scores which complaints are likely to end in relief for the customer, and tests whether complaint patterns
warn of regulatory enforcement in advance.

> Status: in development. Phase 1 (foundation: ingestion, data contract, local lake, dbt, CI) is complete.
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

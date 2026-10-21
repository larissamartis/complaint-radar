# Runbook — daily pipeline

The daily job (`.github/workflows/daily.yml`) runs at 11:30 UTC (17:00 IST). Every run, including skipped and
failed ones, writes a row to BigQuery `complaint_radar.pipeline_runs`. Start every investigation there:

```sql
SELECT run_id, as_of, status, step, rows_loaded, snapshot_rows, api_latest_date, message
FROM `complaint-radar-512308.complaint_radar.pipeline_runs`
ORDER BY started_at DESC
LIMIT 10;
```

| `status` | Meaning |
|---|---|
| `success` | Snapshot loaded, new or changed complaint versions appended, dbt views rebuilt. |
| `no_new_data` | The CFPB API's newest complaint date had not moved since the last good run, so nothing was downloaded. Normal on some days. |
| `failed` | `step` says where it failed and `message` says why. GitHub also emails the repo owner. |

---

## 1. The daily job failed

**Symptom:** a red run in the Actions tab, a GitHub email, or `status = 'failed'`.

**Check:**
1. Look at `step` and `message` in `pipeline_runs`, then open the job log in GitHub Actions.
2. Find the `step` below:

| `step` | Typical cause | Fix |
|---|---|---|
| `precheck` | CFPB API down or slow; BigQuery auth problem. | Re-run the workflow later (Actions, Daily pipeline, Run workflow). For auth errors, see section 6. |
| `fetch` | CFPB file server slow; size mismatch after 3 retries. | Re-run. If it keeps failing, check `https://files.consumerfinance.gov/ccdb/complaints.csv.zip` in a browser. |
| `normalize` | **The source file's columns changed** (message: `Unknown columns ...`). | Section 2. |
| `contract` | **The data broke a rule** (message lists each rule). | Section 2. |
| `change_capture` / `load` | BigQuery quota, permissions or storage. | Section 4. |
| `dbt` | A dbt test failed on the warehouse views. | Run `dbt build --target bigquery` locally and read the failing test. Fix the model or the data issue, then re-run. |

Re-running is always safe: the load only appends `(complaint_id, row_hash)` pairs that are not already
loaded, so a second run of the same day appends 0 rows.

## 2. Contract failed or the source schema changed

This is the scenario of 14 Aug 2026, when CFPB removed the narrative column without notice.

1. Download the snapshot and compare the header with `src/complaint_radar/schema.py` (`COLUMN_MAP`).
2. Decide whether the change is **expected** (a documented CFPB change) or a **bad file** (truncated, duplicated IDs, values that make no sense).
3. **Bad file:** do nothing and let tomorrow's run pick up the corrected file. If it persists, raise it with the source.
4. **Expected change:** update `COLUMN_MAP` / the contract in a pull request, with a test fixture showing the new format, and get CI green before merging. Never loosen a contract rule just to make the run pass.
5. Re-run the workflow.

## 3. No new data for 3 or more days

`no_new_data` once in a while is normal. Three or more in a row means CFPB has stopped updating, or the API is
returning stale results.

1. Compare the API's newest date with the bulk file's `Last-Modified` header.
2. If the bulk file is fresh but the API is stale, run the workflow with **force = true**, which skips the pre-check.
3. Check the CFPB website for announcements of publication changes.

## 4. BigQuery quota or storage

The project uses the **BigQuery sandbox**:
- 10 GiB of storage for the project's *lifetime*, not refunded when data is deleted;
- 1 TiB of queries per month;
- tables and partitions expire after 60 days;
- no DML.

- **Storage:** the daily load is about 20–40k rows. Check the volume with:
  ```sql
  SELECT SUM(rows_loaded) FROM `complaint-radar-512308.complaint_radar.pipeline_runs`
  ```
  If storage is close to the limit, shorten `HOT_WINDOW_DAYS` in `pipeline/daily.py`.
- **Query quota:** the daily job reads about 50 MB (the existing keys). It can only hit the quota through ad-hoc queries.
- **Table expiry:** sandbox tables expire 60 days after creation. Every run pushes both tables' expiry 59 days ahead (`refresh_expiry`), so they only disappear if the job has not run for about two months. In that case the next run recreates them and reloads the whole window automatically (about 400 MB of the lifetime allowance). No manual backfill is needed.

## 5. Backfill after an outage

If the job was down for several days, or a table expired:

- **From GitHub:** Actions, then Daily pipeline, then Run workflow, with `backfill_since = YYYY-MM-DD`.
- **Locally:**
  ```powershell
  $env:GOOGLE_APPLICATION_CREDENTIALS = "$env:USERPROFILE\.secrets\complaint-radar-sa.json"
  uv run complaint-radar backfill --since 2026-10-01
  ```

The backfill re-captures every complaint received since that date from today's full snapshot. It is
idempotent and capped at the 60-day window, because older data would expire immediately in the sandbox.

## 6. Rotating the service-account key

Rotate the key if it may have leaked, or as routine hygiene.

1. In Google Cloud: IAM & Admin, Service accounts, `complaint-radar-pipeline`, Keys, **Add key** (JSON).
2. In GitHub: Settings, Secrets and variables, Actions, update `GCP_SA_KEY` with the new file's contents.
3. Run the workflow manually and confirm it succeeds.
4. Delete the old key in Google Cloud.
5. Replace the local copy at `%USERPROFILE%\.secrets\complaint-radar-sa.json`.

The key must never be committed: `.gitignore` blocks `gcp-*.json` and `*.json.key`, and the key lives
outside the repo.

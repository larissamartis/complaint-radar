# Phase 2 results — daily pipeline (2026-10-21)

## First real runs (local machine, BigQuery sandbox `complaint-radar-512308`)

| Run | Status | Snapshot rows | Rows appended | Notes |
|---|---|---|---|---|
| 1 | failed (`load`) | 18,560,908 | 0 | BigQuery rejected the load: Parquet columns are nullable, the table had REQUIRED fields. Nothing partial was loaded. Fixed by making warehouse columns nullable (not-null is enforced by the data contract before loading). |
| 2 | success | 18,560,908 | **1,248,457** | First load of the 60-day hot window (6.7% of all complaints). dbt on BigQuery: 8/8 passed. About 6 minutes end to end. |
| 3 | no_new_data | (carried) | 0 | The pre-check saw the API's newest date unchanged, so nothing was downloaded. |
| 4 | success (`--force`) | 18,560,908 | **0** | Full re-run of the same snapshot appends nothing: idempotent by `(complaint_id, row_hash)`. |

Current-state view (`wh_complaints_current`): 1,139,434 bureau complaints and 109,023 others in the window.

## Storage budget (honest projection)

The sandbox allows 10 GiB of storage for the project's lifetime, and deleting data does not give it back.

- The first window load was 413 MB (about 330 bytes per row).
- Steady state is new complaints (about 20k/day) plus status changes on in-progress complaints. That is estimated at 40–60k rows/day, or about 15–20 MB/day, which uses up the remaining allowance in roughly 1.3–1.6 years.
- **Mitigations if needed** (see `docs/runbook.md` section 4): drop long free-text columns such as `company_public_response` from the warehouse copy, shorten the hot window, or exclude the bureau segment from the cloud copy.
- Table expiry does not add reloads: every run extends both tables' expiry by 59 days (verified live: `update_table(expires)` is allowed in the sandbox). Only old *partitions* expire, which is the intended rolling window.
- The real daily growth will be measured from `pipeline_runs.rows_loaded` after a week of scheduled runs.

## What the pipeline guarantees

- **Idempotent:** re-running a day appends 0 rows (proven above and by `test_second_run_same_day_loads_zero`).
- **Fails before loading** on a schema change (`test_schema_change_fails_before_load`) or a contract violation (`test_contract_failure_records_failed_run`), and records the failure with its step and message.
- **No DML, no streaming, no scratch tables:** every write is an append load job, which is compatible with the sandbox.
- **Backfill** after an outage: `complaint-radar backfill --since YYYY-MM-DD`, capped at the 60-day window.

## Independent review fixes

A fresh reviewer found 5 important edge cases. Each is fixed with a test that failed first:

| Finding | Fix | Test |
|---|---|---|
| A same-day re-run could leave the older version "current" (the tie-break was on a random run id) | Run ids now sort by start time | `test_run_ids_sort_in_time_order` |
| A status that reverts (A to B to A) was never re-captured | Compare against each complaint's *latest* version only | `test_existing_keys_are_latest_version_only` |
| The current view kept only *changed* old complaints, beyond 60 days | The view keeps only complaints received inside the window | dbt unit test `current_view_keeps_latest_version_inside_window` |
| A past `--as-of` cannot work (CFPB only publishes today's file) | Option removed; runs always use today's UTC date | `test_default_today_is_utc` |
| Whole sandbox tables expire after 60 days, forcing a silent full reload | Expiry is extended on every run | `test_ensure_schema_refreshes_table_expiry` |

Also: the no-new-data baseline never moves backwards (`test_no_new_data_never_lowers_api_baseline`); the key
file is written with `umask 077`; checkout no longer keeps git credentials.

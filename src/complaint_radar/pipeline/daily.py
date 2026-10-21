"""Daily pipeline run: pre-check -> fetch -> normalise -> contract -> change capture -> load -> dbt -> record.

Every run, including skipped and failed ones, is written to the warehouse's `pipeline_runs` table so the
run history is queryable. External systems are injected through `Deps`, which keeps this module testable
without network or BigQuery access.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from complaint_radar.contracts.checker import check_parquet, default_contract_path, load_contract
from complaint_radar.detect.live import detect_current, target_week, weekly_vintage
from complaint_radar.ingest.snapshot import snapshot_to_parquet
from complaint_radar.pipeline.change_capture import select_changes

log = logging.getLogger(__name__)

HOT_WINDOW_DAYS = 60


def _now() -> datetime:
    return datetime.now(UTC)


def utc_today() -> date:
    return _now().date()


@dataclass(frozen=True)
class Deps:
    api_latest_date: Callable[[], date]
    fetch_snapshot: Callable[[Path, date], Path]
    warehouse: object
    run_dbt: Callable[[], None]
    workdir: Path
    today: Callable[[], date] = utc_today


def run_daily(deps: Deps, as_of: date | None = None, window_days: int = HOT_WINDOW_DAYS, force: bool = False) -> dict:
    as_of = as_of or deps.today()
    wh = deps.warehouse
    started = _now()
    run = {
        # Sortable by start time: the current-state view breaks same-day ties on run_id.
        "run_id": f"{started:%Y%m%dT%H%M%S%f}-{uuid.uuid4().hex[:6]}",
        "as_of": as_of,
        "started_at": started,
        "finished_at": None,
        "status": "running",
        "step": "precheck",
        "rows_loaded": 0,
        "snapshot_rows": None,
        "api_latest_date": None,
        "message": None,
    }
    try:
        wh.ensure_schema()
        last = wh.last_successful_run()
        run["api_latest_date"] = deps.api_latest_date()
        if not force and last and last.get("api_latest_date") and run["api_latest_date"] <= last["api_latest_date"]:
            run.update(status="no_new_data", step="done", snapshot_rows=last.get("snapshot_rows"))
            run["api_latest_date"] = max(run["api_latest_date"], last["api_latest_date"])  # never lower the baseline
            run["message"] = f"API newest date {run['api_latest_date']} has not advanced since the last run"
            log.info(run["message"])
            return _finish(wh, run)

        work = deps.workdir / run["run_id"]
        work.mkdir(parents=True, exist_ok=True)

        run["step"] = "fetch"
        zip_path = deps.fetch_snapshot(deps.workdir / "snapshots", as_of)

        run["step"] = "normalize"
        snapshot = work / "snapshot.parquet"
        run["snapshot_rows"] = snapshot_to_parquet(zip_path, snapshot)
        log.info("snapshot rows: %d", run["snapshot_rows"])

        run["step"] = "contract"
        result = check_parquet(
            snapshot,
            load_contract(default_contract_path()),
            as_of=as_of,
            previous_row_count=(last or {}).get("snapshot_rows"),
        )
        if not result.passed:
            raise RuntimeError("data contract failed: " + "; ".join(result.violations))

        run["step"] = "change_capture"
        keys = wh.export_existing_keys(work / "existing_keys.parquet")
        changes = work / "changes.parquet"
        n_changes = select_changes(snapshot, keys, as_of, run["run_id"], changes, window_days)
        log.info("new or changed complaint versions: %d", n_changes)

        run["step"] = "load"
        run["rows_loaded"] = wh.load_parquet(changes, "raw_complaint_versions") if n_changes else 0

        run["step"] = "dbt"
        deps.run_dbt()

        run["step"] = "vintage"
        if not wh.has_vintage(as_of):
            wh.load_vintage(weekly_vintage(snapshot, as_of))

        run["step"] = "detect"
        week = target_week(as_of)
        found = detect_current(snapshot, as_of)
        scored_weeks = sorted({w for w in found["week_start"]} | {week})
        known = set().union(*(wh.existing_alert_ids(w) for w in scored_weeks))
        new = found[~found["alert_id"].isin(known)]
        if len(new):
            wh.load_alerts(new, as_of, run["run_id"], _now())
        run["message"] = f"alerts for week {week}: {len(new)} new, {len(found)} total"
        log.info(run["message"])

        run.update(status="success", step="done")
        return _finish(wh, run)
    except Exception as exc:
        run.update(status="failed", message=f"{type(exc).__name__}: {exc}"[:1000])
        log.error("run %s failed at step %s: %s", run["run_id"], run["step"], exc)
        try:
            _finish(wh, run)
        except Exception:  # recording must never hide the original failure
            log.exception("could not record failed run")
        raise


def backfill(deps: Deps, since: date) -> dict:
    """Re-capture every complaint received since `since` (bounded by the hot window). Idempotent."""
    days = (deps.today() - since).days
    if days > HOT_WINDOW_DAYS:
        log.warning("backfill window of %d days capped to %d (BigQuery sandbox expiry)", days, HOT_WINDOW_DAYS)
        days = HOT_WINDOW_DAYS
    return run_daily(deps, window_days=days, force=True)


def _finish(wh, run: dict) -> dict:
    run["finished_at"] = _now()
    wh.record_run(run)
    return run

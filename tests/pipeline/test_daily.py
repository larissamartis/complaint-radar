import zipfile
from dataclasses import replace
from datetime import date
from pathlib import Path

import duckdb
import pytest

from complaint_radar.pipeline.daily import Deps, backfill, run_daily

FIX = Path(__file__).parents[1] / "fixtures"
AS_OF = date(2025, 2, 22)  # fixture's newest complaint is 2025-02-20


class FakeWarehouse:
    def __init__(self):
        self.loaded: list[Path] = []
        self.runs: list[dict] = []
        self.schema_calls = 0
        self.alerts: list[dict] = []
        self.vintages: list[dict] = []

    def ensure_schema(self):
        self.schema_calls += 1

    def export_existing_keys(self, out_path: Path) -> Path:
        if not self.loaded:
            duckdb.sql(
                f"COPY (SELECT NULL::BIGINT complaint_id, NULL::VARCHAR row_hash WHERE false) "
                f"TO '{out_path.as_posix()}' (FORMAT parquet)"
            )
        else:
            files = ", ".join(f"'{p.as_posix()}'" for p in self.loaded)
            duckdb.sql(
                f"COPY (SELECT complaint_id, row_hash FROM read_parquet([{files}])) "
                f"TO '{out_path.as_posix()}' (FORMAT parquet)"
            )
        return out_path

    def load_parquet(self, path: Path, table: str) -> int:
        keep = path.with_name(f"loaded_{len(self.loaded)}.parquet")
        keep.write_bytes(path.read_bytes())
        self.loaded.append(keep)
        return duckdb.sql(f"select count(*) from read_parquet('{keep.as_posix()}')").fetchone()[0]

    def record_run(self, run: dict) -> None:
        self.runs.append(run)

    def has_vintage(self, as_of):
        return any(v["as_of"] == as_of for v in self.vintages)

    def load_vintage(self, df):
        self.vintages.extend(df.to_dict("records"))
        return len(df)

    def existing_alert_ids(self, week):
        return {a["alert_id"] for a in self.alerts if a["week_start"] == week}

    def load_alerts(self, df, as_of, run_id, created_at):
        self.alerts.extend(df.to_dict("records"))
        return len(df)

    def last_successful_run(self):
        ok = [r for r in self.runs if r["status"] in ("success", "no_new_data")]
        return ok[-1] if ok else None


def zip_fetcher(csv_path: Path, calls: list):
    def fetch(dest: Path, as_of: date) -> Path:
        calls.append(as_of)
        dest.mkdir(parents=True, exist_ok=True)
        z = dest / f"complaints_{as_of.isoformat()}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(csv_path, "complaints.csv")
        return z

    return fetch


def make_deps(tmp_path, csv=FIX / "live_sample.csv", api_latest=date(2025, 2, 20)):
    calls, dbt_calls = [], []
    deps = Deps(
        api_latest_date=lambda: api_latest,
        fetch_snapshot=zip_fetcher(csv, calls),
        warehouse=FakeWarehouse(),
        run_dbt=lambda: dbt_calls.append(1),
        workdir=tmp_path / "work",
        today=lambda: AS_OF,
    )
    return deps, calls, dbt_calls


def test_success_records_rows_loaded(tmp_path):
    deps, calls, dbt_calls = make_deps(tmp_path)
    run = run_daily(deps)
    assert run["status"] == "success" and run["step"] == "done"
    assert run["rows_loaded"] == 1  # only the 2025-02-20 complaint is inside the 60-day window
    assert run["snapshot_rows"] == 4 and run["api_latest_date"] == date(2025, 2, 20)
    assert calls == [AS_OF] and dbt_calls == [1]
    assert deps.warehouse.runs[-1] is run


def test_no_new_data_skips_download(tmp_path):
    deps, calls, _ = make_deps(tmp_path)
    run_daily(deps)
    second = run_daily(deps)
    assert second["status"] == "no_new_data" and second["rows_loaded"] == 0
    assert second["snapshot_rows"] == 4  # carried forward for tomorrow's row-count check
    assert calls == [AS_OF]  # downloaded once only


def test_second_run_same_day_loads_zero(tmp_path):
    deps, _, _ = make_deps(tmp_path)
    run_daily(deps)
    again = run_daily(deps, force=True)
    assert again["status"] == "success" and again["rows_loaded"] == 0


def test_schema_change_fails_before_load(tmp_path):
    bad = tmp_path / "bad.csv"
    lines = (FIX / "live_sample.csv").read_text(encoding="utf-8").splitlines()
    bad.write_text("\n".join([lines[0] + ",New column"] + [ln + ",x" for ln in lines[1:]]), encoding="utf-8")
    deps, _, dbt_calls = make_deps(tmp_path, csv=bad)
    with pytest.raises(ValueError, match="New column"):
        run_daily(deps)
    run = deps.warehouse.runs[-1]
    assert run["status"] == "failed" and run["step"] == "normalize" and "New column" in run["message"]
    assert deps.warehouse.loaded == [] and dbt_calls == []


def test_contract_failure_records_failed_run(tmp_path):
    deps, _, _ = make_deps(tmp_path)
    deps = replace(deps, today=lambda: date(2025, 3, 30))  # newest complaint 38 days old -> freshness fails
    with pytest.raises(RuntimeError, match="freshness"):
        run_daily(deps, force=True)
    run = deps.warehouse.runs[-1]
    assert run["status"] == "failed" and run["step"] == "contract"
    assert deps.warehouse.loaded == []


def test_backfill_caps_window_at_60(tmp_path, caplog):
    deps, _, _ = make_deps(tmp_path)
    run = backfill(deps, since=date(2024, 1, 1))
    assert run["status"] == "success"
    assert "capped" in caplog.text


def test_run_ids_sort_in_time_order(tmp_path):
    deps, _, _ = make_deps(tmp_path)
    first = run_daily(deps)
    second = run_daily(deps, force=True)
    assert first["run_id"] < second["run_id"]


def test_no_new_data_never_lowers_api_baseline(tmp_path):
    deps, _, _ = make_deps(tmp_path)
    run_daily(deps)
    stale = replace(deps, api_latest_date=lambda: date(2025, 2, 18))  # API briefly returns an older date
    run = run_daily(stale)
    assert run["status"] == "no_new_data" and run["api_latest_date"] == date(2025, 2, 20)


def test_default_today_is_utc():
    from datetime import UTC, datetime

    from complaint_radar.pipeline.daily import utc_today

    assert utc_today() == datetime.now(UTC).date()


def test_alerts_are_recorded_once_per_week(tmp_path, monkeypatch):
    import pandas as pd

    import complaint_radar.pipeline.daily as daily
    from complaint_radar.detect.live import ALERT_COLUMNS, target_week

    week = target_week(AS_OF)
    fake = pd.DataFrame([dict.fromkeys(ALERT_COLUMNS, None) | {"alert_id": "a1", "week_start": week, "n": 60}])
    monkeypatch.setattr(daily, "detect_current", lambda snapshot, as_of: fake)
    deps, _, _ = make_deps(tmp_path)
    first = run_daily(deps)
    second = run_daily(deps, force=True)
    assert [a["alert_id"] for a in deps.warehouse.alerts] == ["a1"]
    assert "1 new" in first["message"] and "0 new" in second["message"]


def test_vintage_recorded_once_per_day(tmp_path):
    deps, _, _ = make_deps(tmp_path)
    run_daily(deps)
    n = len(deps.warehouse.vintages)
    run_daily(deps, force=True)
    assert n > 0 and len(deps.warehouse.vintages) == n
    assert {"as_of", "segment", "week_start", "age", "n_published"} <= set(deps.warehouse.vintages[0])

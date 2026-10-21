"""Command-line entry point: `complaint-radar <command>`."""

import logging
import os
import shutil
import subprocess
import time
from datetime import date
from pathlib import Path

import typer

from complaint_radar import config
from complaint_radar.contracts.checker import default_contract_path
from complaint_radar.ingest.archive import backfill_archive, download_archive

app = typer.Typer(help="Complaint Radar pipeline commands.", no_args_is_help=True)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@app.command("download-archive")
def download_archive_cmd() -> None:
    """Download the CFPB narratives archive (21 zips, ~1.43 GB) into the raw data folder."""
    paths = download_archive(config.raw_archive_dir())
    typer.echo(f"{len(paths)} archive files present in {config.raw_archive_dir()}")


@app.command("backfill-archive")
def backfill_archive_cmd() -> None:
    """Normalise archive zips into contract-checked Parquet in the local lake."""
    start = time.time()
    report = backfill_archive(config.raw_archive_dir(), config.archive_parquet_dir(), default_contract_path())
    typer.echo(
        f"processed {len(report.processed)}, skipped {len(report.skipped)}, "
        f"rows {report.rows:,} in {time.time() - start:.0f}s"
    )


def _deps():
    from google.cloud import bigquery

    from complaint_radar.ingest.snapshot import api_latest_date, fetch_snapshot
    from complaint_radar.pipeline.daily import Deps
    from complaint_radar.storage.bigquery import BigQueryWarehouse

    project = os.environ.get("CR_BQ_PROJECT", "complaint-radar-512308")
    dbt_dir = Path(os.environ.get("CR_DBT_DIR", Path(__file__).resolve().parents[2] / "dbt"))

    def run_dbt() -> None:
        cmd = ["dbt", "build", "--project-dir", str(dbt_dir), "--profiles-dir", str(dbt_dir), "--target", "bigquery"]
        subprocess.run(cmd, check=True)

    return Deps(
        api_latest_date=api_latest_date,
        fetch_snapshot=fetch_snapshot,
        warehouse=BigQueryWarehouse(bigquery.Client(project=project), project),
        run_dbt=run_dbt,
        workdir=config.data_root() / "work",
    )


def _cleanup(workdir: Path, run: dict, keep_snapshots: int = 2) -> None:
    """Delete this run's scratch files on success and keep only the newest snapshot zips."""
    if run["status"] == "success":
        shutil.rmtree(workdir / run["run_id"], ignore_errors=True)
    for old in sorted((workdir / "snapshots").glob("complaints_*.zip"))[:-keep_snapshots]:
        old.unlink(missing_ok=True)


def _report(run: dict) -> None:
    typer.echo(
        f"run {run['run_id']}: {run['status']} (step {run['step']}), rows loaded {run['rows_loaded']:,}, "
        f"snapshot rows {run['snapshot_rows'] or 0:,}, API newest {run['api_latest_date']}"
    )


@app.command("run-daily")
def run_daily_cmd(force: bool = typer.Option(False, help="Run even if the API shows no new data")) -> None:
    """Daily pipeline: pre-check, snapshot, contract, change capture, BigQuery load, dbt."""
    from complaint_radar.pipeline.daily import run_daily

    deps = _deps()
    # Always today's (UTC) snapshot: CFPB only publishes the current file, so a past date cannot be replayed.
    run = run_daily(deps, force=force)
    _cleanup(deps.workdir, run)
    _report(run)


@app.command("backfill")
def backfill_cmd(since: str = typer.Option(..., help="Re-capture complaints received since YYYY-MM-DD")) -> None:
    """Re-capture recent complaints after an outage (idempotent; capped at the 60-day hot window)."""
    from complaint_radar.pipeline.daily import backfill

    deps = _deps()
    run = backfill(deps, since=date.fromisoformat(since))
    _cleanup(deps.workdir, run)
    _report(run)


@app.command("backtest")
def backtest_cmd(out: Path = typer.Option(Path("docs/results/backtest.json"), help="Where to write results")) -> None:
    """Backtest emerging-issue detectors on real past incidents in the local lake."""
    import duckdb

    from complaint_radar.detect.run_backtest import run_backtest

    con = duckdb.connect(str(config.duckdb_path()), read_only=True)
    res = run_backtest(con, out)
    for seg, body in res["segments"].items():
        typer.echo(f"\n[{seg}] incidents labelled: {body['n_incidents_total']}")
        for det, r in body["detectors"].items():
            t = r["test"]
            typer.echo(
                f"  {det:12} thr={r['threshold']:<5} test: recall {t['recall']:.0%} ({t['caught']}/{t['incidents']}), "
                f"median lead {t['median_lead_days']} d, "
                f"FA/100 series-months {t['false_alarms_per_100_series_months']:.2f}, "
                f"precision {t['precision']:.0%}"
            )

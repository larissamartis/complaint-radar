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

    from complaint_radar.summarize.ollama import DEFAULT_MODEL, DEFAULT_URL, OllamaClient

    llm = OllamaClient(
        os.environ.get("CR_OLLAMA_URL", DEFAULT_URL),
        os.environ.get("CR_LLM_MODEL", DEFAULT_MODEL),
        timeout=float(os.environ.get("CR_LLM_TIMEOUT", "120")),
    )
    if not llm.available():
        logging.getLogger(__name__).warning("summary model not available; alerts will use template summaries")
        llm = None

    return Deps(
        api_latest_date=api_latest_date,
        fetch_snapshot=fetch_snapshot,
        warehouse=BigQueryWarehouse(bigquery.Client(project=project), project),
        run_dbt=run_dbt,
        workdir=config.data_root() / "work",
        llm=llm,
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


@app.command("campaigns")
def campaigns_cmd(out: Path = typer.Option(Path("docs/results/campaigns.json"), help="Where to write results")) -> None:
    """Score every non-bureau incident (2016+) for template / campaign amplification using archived text."""
    import json

    import duckdb

    from complaint_radar.detect.backtest import label_incidents
    from complaint_radar.detect.patterns import score_incident_campaigns
    from complaint_radar.detect.series import weekly_series

    con = duckdb.connect(str(config.duckdb_path()), read_only=True)
    weekly = weekly_series(con, "fct_complaints_daily", date(2015, 1, 1), date(2026, 5, 31), min_peak=10)
    incidents = label_incidents(weekly[weekly["segment"] == "other"].reset_index(drop=True))
    incidents = incidents[pd_ts(incidents["start_month"]) >= pd_ts("2016-01-01")]
    scored = score_incident_campaigns(con, incidents)
    summary = {
        "incidents_scored": int(len(scored)),
        "template_amplified": int((scored["label"] == "template_amplified").sum()),
        "share_template_amplified": float((scored["label"] == "template_amplified").mean()),
        "median_near_dup_share": float(scored["near_dup_share"].median()),
        "median_near_dup_share_before": float(scored["near_dup_share_before"].dropna().median()),
    }
    out.write_text(json.dumps({"summary": summary, "incidents": scored.to_dict("records")}, indent=2), encoding="utf-8")
    typer.echo(json.dumps(summary, indent=2))


def pd_ts(x):
    import pandas as pd

    return pd.to_datetime(x)


@app.command("build-topics")
def build_topics_cmd() -> None:
    """Fit topics on the embedded sample, name them, label the full corpus and write the topic lookup."""
    from complaint_radar.summarize.ollama import OllamaClient
    from complaint_radar.text.build import run_build

    llm = OllamaClient(timeout=180)
    res = run_build(
        config.lake_dir() / "text",
        Path(__file__).resolve().parent / "data" / "topic_lookup.json",
        Path("docs/results/topics.json"),
        llm=llm if llm.available() else None,
    )
    typer.echo({k: v for k, v in res.items() if k != "topic_list"})


@app.command("embed-sample")
def embed_sample_cmd(n: int = typer.Option(40_000, help="Sample size (stratified by product and year)")) -> None:
    """Load the non-bureau narrative corpus, draw a stratified sample and cache its sentence embeddings."""
    import duckdb

    from complaint_radar.text.corpus import embed, load_corpus, stratified_sample

    out = config.lake_dir() / "text"
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.duckdb_path()), read_only=True)
    corpus = load_corpus(con)
    sample = stratified_sample(corpus, n, seed=0)
    corpus.to_parquet(out / "corpus.parquet")
    sample.to_parquet(out / "sample.parquet")
    emb = embed(sample["text"].tolist(), cache=out / "sample_embeddings.npy")
    typer.echo(f"corpus {len(corpus):,} unique narratives, sample {len(sample):,}, embeddings {emb.shape}")


@app.command("train-triage")
def train_triage_cmd() -> None:
    """Train and evaluate the escalation-triage models (2019-2023 train, 2024 calibrate, 2025 test)."""
    import duckdb

    from complaint_radar.triage.train import load_training_frame, train_and_evaluate

    con = duckdb.connect(str(config.duckdb_path()), read_only=True)
    df = load_training_frame(con)
    res = train_and_evaluate(
        df,
        Path(__file__).resolve().parent / "data" / "triage_model.joblib",
        Path("docs/results/triage.json"),
    )
    for name, m in res["test_all_rows"].items():
        typer.echo(
            f"{name:30} ROC-AUC {m['roc_auc']:.3f}  PR-AUC {m['pr_auc']:.3f}  "
            f"lift@10% {m['lift_top10']:.2f}  Brier {m['brier']:.4f}"
        )

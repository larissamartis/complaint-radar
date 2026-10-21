"""Command-line entry point: `complaint-radar <command>`."""

import logging
import time

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

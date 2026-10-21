"""One-time backfill from the CFPB FOIA narratives archive (frozen at 2026-08-14)."""

import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from complaint_radar.contracts.checker import check_parquet, load_contract
from complaint_radar.ingest.http import download
from complaint_radar.ingest.normalize import normalize_csv

log = logging.getLogger(__name__)

ARCHIVE_BASE_URL = "https://files.consumerfinance.gov/f/documents/"
ARCHIVE_FILES: tuple[str, ...] = (
    "CCDB_Export_1_December_2011_through_April_2018",
    "CCDB_Export_2_May_2018_through_April_2021",
    "CCDB_Export_3_May_2021_through_October_2022",
    "CCDB_Export_4_November_2022_through_August_2023",
    "CCDB_Export_5_September_2023_through_March_2024",
    "CCDB_Export_6_April_2024_through_July_2024",
    "CCDB_Export_7_August_2024_through_October_2024",
    "CCDB_Export_8_November_2024_through_December_2024",
    "CCDB_Export_9_January_2025_through_February_2025",
    "CCDB_Export_10_March_2025_through_April_2025",
    "CCDB_Export_11_May_2025_through_June_2025",
    "CCDB_Export_12_July_2025_through_August_2025",
    "CCDB_Export_13_September_2025_through_October_2025",
    "CCDB_Export_14_November_2025_through_December_2025",
    "CCDB_Export_15_January_2026_through_February_2026",
    "CCDB_Export_16_March_2026",
    "CCDB_Export_17_April_2026",
    "CCDB_Export_18_May_2026",
    "CCDB_Export_19_June_2026",
    "CCDB_Export_20_July_2026",
    "CCDB_Export_21_August_2026",
)


class ContractViolation(Exception):
    def __init__(self, name: str, violations: list[str]):
        self.name, self.violations = name, violations
        super().__init__(f"{name} failed the data contract: " + "; ".join(violations))


@dataclass
class BackfillReport:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    rows: int = 0


def download_archive(
    dest: Path,
    names: tuple[str, ...] = ARCHIVE_FILES,
    session=None,
    retries: int = 3,
    backoff: float = 5.0,
) -> list[Path]:
    """Download archive zips into `dest`, skipping files already complete. Returns local paths."""
    return [
        download(f"{ARCHIVE_BASE_URL}{name}.zip", dest / f"{name}.zip", session, retries, backoff) for name in names
    ]


def backfill_archive(raw_dir: Path, out_dir: Path, contract_path: Path) -> BackfillReport:
    """Normalise every archive zip in `raw_dir` to `out_dir/<name>.parquet`, contract-checked."""
    contract = load_contract(contract_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = out_dir.parent / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    report = BackfillReport()
    for zpath in sorted(raw_dir.glob("*.zip")):
        name = zpath.stem
        final = out_dir / f"{name}.parquet"
        if final.exists():
            report.skipped.append(name)
            continue
        # Staging lives outside out_dir so dbt (which globs out_dir/*.parquet) never sees unchecked rows.
        staging = staging_dir / f"{name}.parquet"
        with tempfile.TemporaryDirectory(dir=out_dir.parent) as tmp:
            with zipfile.ZipFile(zpath) as zf:
                member = next((m for m in zf.namelist() if m.lower().endswith(".csv")), None)
                if member is None:
                    raise ValueError(f"{zpath.name} contains no CSV file")
                csv_path = Path(zf.extract(member, tmp))
            try:
                rows = normalize_csv(csv_path, staging, source_file=name)
                result = check_parquet(staging, contract)
            except BaseException:
                staging.unlink(missing_ok=True)
                raise
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if not result.passed:
            staging.unlink(missing_ok=True)
            raise ContractViolation(name, result.violations)
        staging.replace(final)
        report.processed.append(name)
        report.rows += rows
        log.info("%s: %d rows", name, rows)
    return report

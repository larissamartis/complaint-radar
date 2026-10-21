"""BigQuery warehouse adapter designed for the free sandbox.

Sandbox rules this module respects: no DML (no MERGE/UPDATE/DELETE), no streaming inserts,
tables and partitions expire after 60 days, and storage is capped for the project's lifetime.
So every write is an append load job, and nothing creates scratch tables.
"""

import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import bigquery

DATASET = "complaint_radar"
LOCATION = "US"

_STRING_COLUMNS = (
    "product",
    "sub_product",
    "issue",
    "sub_issue",
    "company_public_response",
    "company",
    "state",
    "zip_code",
    "tags",
    "submitted_via",
    "company_response",
    "timely_response",
    "row_hash",
)

RAW_VERSIONS_SCHEMA = [
    bigquery.SchemaField("complaint_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("date_received", "DATE", mode="REQUIRED"),
    *[bigquery.SchemaField(c, "STRING") for c in _STRING_COLUMNS[:5]],
    bigquery.SchemaField("company", "STRING", mode="REQUIRED"),
    *[bigquery.SchemaField(c, "STRING") for c in _STRING_COLUMNS[6:9]],
    bigquery.SchemaField("date_sent_to_company", "DATE"),
    *[bigquery.SchemaField(c, "STRING") for c in _STRING_COLUMNS[9:]],
    bigquery.SchemaField("loaded_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
]

PIPELINE_RUNS_ARROW = pa.schema(
    [
        ("run_id", pa.string()),
        ("as_of", pa.date32()),
        ("started_at", pa.timestamp("us", tz="UTC")),
        ("finished_at", pa.timestamp("us", tz="UTC")),
        ("status", pa.string()),
        ("step", pa.string()),
        ("rows_loaded", pa.int64()),
        ("snapshot_rows", pa.int64()),
        ("api_latest_date", pa.date32()),
        ("message", pa.string()),
    ]
)

PIPELINE_RUNS_SCHEMA = [
    bigquery.SchemaField("run_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("as_of", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("started_at", "TIMESTAMP"),
    bigquery.SchemaField("finished_at", "TIMESTAMP"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("step", "STRING"),
    bigquery.SchemaField("rows_loaded", "INT64"),
    bigquery.SchemaField("snapshot_rows", "INT64"),
    bigquery.SchemaField("api_latest_date", "DATE"),
    bigquery.SchemaField("message", "STRING"),
]


class BigQueryWarehouse:
    def __init__(self, client, project: str, dataset: str = DATASET):
        self.client, self.project, self.dataset = client, project, dataset

    def _table(self, name: str) -> str:
        return f"{self.project}.{self.dataset}.{name}"

    def ensure_schema(self) -> None:
        ds = bigquery.Dataset(f"{self.project}.{self.dataset}")
        ds.location = LOCATION
        self.client.create_dataset(ds, exists_ok=True)

        raw = bigquery.Table(self._table("raw_complaint_versions"), schema=RAW_VERSIONS_SCHEMA)
        raw.time_partitioning = bigquery.TimePartitioning(field="loaded_date")
        raw.clustering_fields = ["company"]
        self.client.create_table(raw, exists_ok=True)

        runs = bigquery.Table(self._table("pipeline_runs"), schema=PIPELINE_RUNS_SCHEMA)
        runs.time_partitioning = bigquery.TimePartitioning(field="as_of")
        self.client.create_table(runs, exists_ok=True)

    def export_existing_keys(self, out_path: Path) -> Path:
        sql = f"SELECT complaint_id, row_hash FROM `{self._table('raw_complaint_versions')}`"
        pq.write_table(self.client.query(sql).to_arrow(), out_path)
        return out_path

    def load_parquet(self, path: Path, table: str) -> int:
        cfg = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        with Path(path).open("rb") as f:
            job = self.client.load_table_from_file(f, self._table(table), job_config=cfg)
        return job.result().output_rows

    def record_run(self, run: dict) -> None:
        table = pa.Table.from_pylist([run], schema=PIPELINE_RUNS_ARROW)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.parquet"
            pq.write_table(table, path)
            self.load_parquet(path, "pipeline_runs")

    def last_successful_run(self) -> dict | None:
        sql = f"""
            SELECT * FROM `{self._table("pipeline_runs")}`
            WHERE status IN ('success', 'no_new_data')
            ORDER BY finished_at DESC LIMIT 1
        """
        rows = list(self.client.query(sql).result())
        return dict(rows[0].items()) if rows else None

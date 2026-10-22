"""BigQuery warehouse adapter designed for the free sandbox.

Sandbox rules this module respects: no DML (no MERGE/UPDATE/DELETE), no streaming inserts,
tables and partitions expire after 60 days, and storage is capped for the project's lifetime.
So every write is an append load job, and nothing creates scratch tables.
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import bigquery

DATASET = "complaint_radar"
LOCATION = "US"
# Sandbox tables expire 60 days after creation. Pushing expiry forward on every run keeps the tables alive;
# old *partitions* still expire after 60 days, which is exactly the rolling hot window we want.
TABLE_KEEPALIVE_DAYS = 59
TABLES = ("raw_complaint_versions", "pipeline_runs", "alerts", "snapshot_vintages")

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
    bigquery.SchemaField("complaint_id", "INT64"),
    bigquery.SchemaField("date_received", "DATE"),
    *[bigquery.SchemaField(c, "STRING") for c in _STRING_COLUMNS[:5]],
    bigquery.SchemaField("company", "STRING"),
    *[bigquery.SchemaField(c, "STRING") for c in _STRING_COLUMNS[6:9]],
    bigquery.SchemaField("date_sent_to_company", "DATE"),
    *[bigquery.SchemaField(c, "STRING") for c in _STRING_COLUMNS[9:]],
    bigquery.SchemaField("loaded_date", "DATE"),
    bigquery.SchemaField("run_id", "STRING"),
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
    bigquery.SchemaField("run_id", "STRING"),
    bigquery.SchemaField("as_of", "DATE"),
    bigquery.SchemaField("started_at", "TIMESTAMP"),
    bigquery.SchemaField("finished_at", "TIMESTAMP"),
    bigquery.SchemaField("status", "STRING"),
    bigquery.SchemaField("step", "STRING"),
    bigquery.SchemaField("rows_loaded", "INT64"),
    bigquery.SchemaField("snapshot_rows", "INT64"),
    bigquery.SchemaField("api_latest_date", "DATE"),
    bigquery.SchemaField("message", "STRING"),
]


ALERTS_ARROW = pa.schema(
    [
        ("alert_id", pa.string()),
        ("as_of", pa.date32()),
        ("week_start", pa.date32()),
        ("week_age", pa.int64()),
        ("segment", pa.string()),
        ("company", pa.string()),
        ("product", pa.string()),
        ("issue", pa.string()),
        ("detector", pa.string()),
        ("threshold", pa.float64()),
        ("n", pa.int64()),
        ("expected", pa.float64()),
        ("completeness", pa.float64()),
        ("score", pa.float64()),
        ("wave_companies", pa.int64()),
        ("pattern", pa.string()),
        ("typical_topics", pa.string()),
        ("summary", pa.string()),
        ("summary_method", pa.string()),
        ("run_id", pa.string()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)
VINTAGES_ARROW = pa.schema(
    [
        ("as_of", pa.date32()),
        ("segment", pa.string()),
        ("week_start", pa.date32()),
        ("age", pa.int64()),
        ("n_published", pa.int64()),
    ]
)
_BQ_TYPES = {pa.string(): "STRING", pa.date32(): "DATE", pa.float64(): "FLOAT64", pa.int64(): "INT64"}
ALERTS_SCHEMA = [bigquery.SchemaField(f.name, _BQ_TYPES.get(f.type, "TIMESTAMP")) for f in ALERTS_ARROW]


VINTAGES_SCHEMA = [bigquery.SchemaField(f.name, _BQ_TYPES[f.type]) for f in VINTAGES_ARROW]


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

        alerts = bigquery.Table(self._table("alerts"), schema=ALERTS_SCHEMA)
        alerts.time_partitioning = bigquery.TimePartitioning(field="week_start")
        self.client.create_table(alerts, exists_ok=True)
        self._add_missing_fields("alerts", ALERTS_SCHEMA)

        vintages = bigquery.Table(self._table("snapshot_vintages"), schema=VINTAGES_SCHEMA)
        vintages.time_partitioning = bigquery.TimePartitioning(field="as_of")
        self.client.create_table(vintages, exists_ok=True)
        self.refresh_expiry()

    def _add_missing_fields(self, name: str, schema: list) -> None:
        """Add columns introduced by a newer release (load jobs reject unknown columns)."""
        table = self.client.get_table(self._table(name))
        have = {f.name for f in table.schema}
        missing = [f for f in schema if f.name not in have]
        if missing:
            table.schema = list(table.schema) + missing
            self.client.update_table(table, ["schema"])

    def refresh_expiry(self) -> None:
        expires = datetime.now(UTC) + timedelta(days=TABLE_KEEPALIVE_DAYS)
        for name in TABLES:
            table = self.client.get_table(self._table(name))
            table.expires = expires
            self.client.update_table(table, ["expires"])

    def export_existing_keys(self, out_path: Path) -> Path:
        # Latest version per complaint only, so a status that reverts (A -> B -> A) is captured again.
        # Ordering must match dbt's wh_complaints_current.
        sql = f"""
            SELECT complaint_id, row_hash FROM `{self._table("raw_complaint_versions")}`
            QUALIFY row_number() OVER (PARTITION BY complaint_id ORDER BY loaded_date DESC, run_id DESC) = 1
        """
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

    def existing_alert_ids(self, week_start) -> set[str]:
        sql = f"SELECT alert_id FROM `{self._table('alerts')}` WHERE week_start = '{week_start.isoformat()}'"
        return {r["alert_id"] for r in self.client.query(sql).result()}

    def load_alerts(self, alerts_df, as_of, run_id: str, created_at) -> int:
        cols = [f.name for f in ALERTS_ARROW]
        rows = alerts_df.assign(as_of=as_of, run_id=run_id, created_at=created_at).reindex(columns=cols)
        rows = rows.astype(object).where(rows.notna(), None).to_dict("records")
        table = pa.Table.from_pylist(rows, schema=ALERTS_ARROW)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alerts.parquet"
            pq.write_table(table, path)
            return self.load_parquet(path, "alerts")

    def has_vintage(self, as_of) -> bool:
        sql = f"SELECT count(*) AS n FROM `{self._table('snapshot_vintages')}` WHERE as_of = '{as_of.isoformat()}'"
        return next(iter(self.client.query(sql).result()))["n"] > 0

    def load_vintage(self, vintage_df) -> int:
        table = pa.Table.from_pylist(vintage_df.to_dict("records"), schema=VINTAGES_ARROW)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vintage.parquet"
            pq.write_table(table, path)
            return self.load_parquet(path, "snapshot_vintages")

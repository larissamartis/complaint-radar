from datetime import UTC, date, datetime

import duckdb

from complaint_radar.storage.bigquery import BigQueryWarehouse


class FakeJob:
    def __init__(self, rows):
        self.output_rows = rows

    def result(self):
        return self


class FakeClient:
    """Records calls. Deliberately has no insert_rows: streaming inserts are not allowed in the sandbox."""

    def __init__(self):
        self.datasets, self.tables, self.loads = [], [], []

    def create_dataset(self, dataset, exists_ok=False):
        self.datasets.append((dataset, exists_ok))

    def create_table(self, table, exists_ok=False):
        self.tables.append((table, exists_ok))

    def load_table_from_file(self, f, destination, job_config=None):
        data = f.read()
        self.loads.append((destination, job_config, data))
        return FakeJob(rows=3)


def test_ensure_schema_creates_partitioned_tables():
    client = FakeClient()
    BigQueryWarehouse(client, "proj").ensure_schema()
    assert client.datasets[0][0].dataset_id == "complaint_radar" and client.datasets[0][1]
    tables = {t.table_id: t for t, _ in client.tables}
    assert set(tables) == {"raw_complaint_versions", "pipeline_runs"}
    raw = tables["raw_complaint_versions"]
    assert raw.time_partitioning.field == "loaded_date"
    assert raw.clustering_fields == ["company"]
    assert raw.expires is None  # sandbox default expiry applies; we never try to override it
    assert tables["pipeline_runs"].time_partitioning.field == "as_of"


def test_load_parquet_uses_append_load_job(tmp_path):
    p = tmp_path / "x.parquet"
    duckdb.sql(f"COPY (SELECT 1 AS a) TO '{p.as_posix()}' (FORMAT parquet)")
    client = FakeClient()
    rows = BigQueryWarehouse(client, "proj").load_parquet(p, "raw_complaint_versions")
    destination, cfg, _ = client.loads[0]
    assert rows == 3
    assert destination == "proj.complaint_radar.raw_complaint_versions"
    assert cfg.source_format == "PARQUET" and cfg.write_disposition == "WRITE_APPEND"


def test_record_run_uses_load_job_not_insert_rows():
    client = FakeClient()
    now = datetime(2026, 10, 21, 11, 30, tzinfo=UTC)
    BigQueryWarehouse(client, "proj").record_run(
        {
            "run_id": "r1",
            "as_of": date(2026, 10, 21),
            "started_at": now,
            "finished_at": now,
            "status": "success",
            "step": "done",
            "rows_loaded": 10,
            "snapshot_rows": 100,
            "api_latest_date": date(2026, 10, 20),
            "message": None,
        }
    )
    assert client.loads[0][0] == "proj.complaint_radar.pipeline_runs"
    assert client.loads[0][2][:4] == b"PAR1"  # parquet magic bytes


def test_schemas_have_no_required_fields():
    # Parquet columns are always nullable, and BigQuery rejects a nullable load into a REQUIRED field.
    # Not-null rules are enforced upstream by the data contract instead.
    from complaint_radar.storage.bigquery import PIPELINE_RUNS_SCHEMA, RAW_VERSIONS_SCHEMA

    assert {f.mode for f in RAW_VERSIONS_SCHEMA + PIPELINE_RUNS_SCHEMA} == {"NULLABLE"}

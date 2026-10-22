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

    def get_table(self, ref):
        return type("T", (), {"expires": None, "table_id": ref.split(".")[-1], "schema": []})()

    def update_table(self, table, fields):
        return table

    def load_table_from_file(self, f, destination, job_config=None):
        data = f.read()
        self.loads.append((destination, job_config, data))
        return FakeJob(rows=3)


def test_ensure_schema_creates_partitioned_tables():
    client = FakeClient()
    BigQueryWarehouse(client, "proj").ensure_schema()
    assert client.datasets[0][0].dataset_id == "complaint_radar" and client.datasets[0][1]
    tables = {t.table_id: t for t, _ in client.tables}
    assert set(tables) == {
        "raw_complaint_versions",
        "pipeline_runs",
        "alerts",
        "snapshot_vintages",
        "triage_scores",
        "drift_metrics",
    }
    assert tables["alerts"].time_partitioning.field == "week_start"
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


class QueryClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.sql, self.updated = [], []

    def query(self, sql):
        self.sql.append(sql)

        class R:
            def to_arrow(self_inner):
                import pyarrow as pa

                return pa.table({"complaint_id": pa.array([], pa.int64()), "row_hash": pa.array([], pa.string())})

        return R()

    def get_table(self, ref):
        class T:
            expires = None
            schema: list = []
            table_id = ref.split(".")[-1]

        return T()

    def update_table(self, table, fields):
        self.updated.append((table.table_id, fields, table.expires))
        return table


def test_ensure_schema_refreshes_table_expiry():
    # Sandbox tables expire 60 days after creation; each run pushes expiry forward so the history survives.
    client = QueryClient()
    BigQueryWarehouse(client, "proj").ensure_schema()
    expiry = [(t, e) for t, f, e in client.updated if f == ["expires"]]
    assert {t for t, _ in expiry} == {
        "raw_complaint_versions",
        "pipeline_runs",
        "alerts",
        "snapshot_vintages",
        "triage_scores",
        "drift_metrics",
    }
    assert all(e is not None for _, e in expiry)


def test_existing_keys_are_latest_version_only(tmp_path):
    # A -> B -> A must be captured as a new version, so compare against each complaint's latest version only.
    client = QueryClient()
    BigQueryWarehouse(client, "proj").export_existing_keys(tmp_path / "k.parquet")
    sql = client.sql[0].lower()
    assert "row_number()" in sql and "partition by complaint_id" in sql and "= 1" in sql


def test_ensure_schema_adds_missing_alert_columns():
    # An alerts table created by an older release lacks newer columns; they must be added (metadata change,
    # allowed in the sandbox) or the next load job would be rejected.
    from google.cloud import bigquery

    from complaint_radar.storage.bigquery import ALERTS_SCHEMA

    class OldTables(QueryClient):
        def get_table(self, ref):
            t = bigquery.Table(ref, schema=ALERTS_SCHEMA[:5] if ref.endswith(".alerts") else [])
            return t

        def update_table(self, table, fields):
            self.updated.append((table.table_id, fields, [f.name for f in table.schema]))
            return table

    client = OldTables()
    BigQueryWarehouse(client, "proj").ensure_schema()
    schema_updates = [u for u in client.updated if u[1] == ["schema"]]
    assert schema_updates and schema_updates[0][0] == "alerts"
    assert {"summary", "pattern", "typical_topics"} <= set(schema_updates[0][2])


def test_load_frame_converts_duckdb_dtypes(tmp_path):
    import pandas as pd
    import pyarrow.parquet as pq

    from complaint_radar.storage.bigquery import TRIAGE_SCORES_ARROW

    captured = {}

    class Capture(FakeClient):
        def load_table_from_file(self, f, destination, job_config=None):
            captured["table"] = pq.read_table(f)
            return FakeJob(rows=1)

    df = pd.DataFrame(
        {
            "as_of": [date(2026, 10, 21)],
            "complaint_id": [1],
            "date_received": [pd.Timestamp("2026-10-01")],
            "relief_probability": [0.3],
            "already_closed": [True],
            "company": [None],
        }
    )
    BigQueryWarehouse(Capture(), "proj").load_frame(df, "triage_scores", TRIAGE_SCORES_ARROW)
    t = captured["table"]
    assert t.schema == TRIAGE_SCORES_ARROW
    assert t.column("date_received")[0].as_py() == date(2026, 10, 1) and t.column("company")[0].as_py() is None

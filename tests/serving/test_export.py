import json
import re
from datetime import date

from complaint_radar.serving.export import QUERIES, export_serving


class Row(dict):
    pass


class Client:
    def __init__(self, fail_table=None):
        self.fail_table, self.sql = fail_table, []

    def query(self, sql):
        self.sql.append(sql)
        if self.fail_table and f".{self.fail_table}`" in sql:
            raise RuntimeError("table missing")

        class Job:
            def result(self_inner):
                return [Row({"week_start": date(2026, 10, 5), "n": 3})]

        return Job()


def test_export_writes_one_json_per_query_plus_meta(tmp_path):
    counts = export_serving(Client(), "proj", tmp_path)
    assert set(counts) == set(QUERIES)
    assert json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8")) == [{"week_start": "2026-10-05", "n": 3}]
    assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["rows"]["alerts"] == 1


def test_queries_are_read_only_and_target_the_dataset():
    for sql in QUERIES.values():
        upper = sql.upper()
        assert "{DS}" in upper and not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP)\b", upper)


def test_any_failed_query_raises_so_nothing_is_published(tmp_path):
    import pytest

    from complaint_radar.serving.export import ExportFailed

    with pytest.raises(ExportFailed, match="drift"):
        export_serving(Client(fail_table="drift_metrics"), "proj", tmp_path)
    assert not (tmp_path / "meta.json").exists()


def test_decimals_are_written_as_numbers(tmp_path):
    from decimal import Decimal

    from complaint_radar.serving.export import _json_default

    assert _json_default(Decimal("1.5")) == 1.5

"""Export small serving files for the dashboard from BigQuery (read-only queries over the hot window).

Files (JSON, a few MB at most) are written to a folder that the daily workflow publishes to the `serving-data`
branch; the dashboard reads them from there, so it needs no cloud credentials.
"""

import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

log = logging.getLogger(__name__)

QUERIES = {
    "alerts": """
        SELECT alert_id, as_of, week_start, week_age, segment, company, product, issue, n, expected, completeness,
               score, wave_companies, pattern, typical_topics, summary, summary_method, created_at
        FROM `{ds}.alerts`
        WHERE TRUE  -- QUALIFY needs a WHERE, GROUP BY or HAVING in some BigQuery versions
        QUALIFY row_number() OVER (PARTITION BY alert_id ORDER BY created_at DESC) = 1
        ORDER BY week_start DESC, score DESC
        LIMIT 2000
    """,
    "weekly_volume": """
        SELECT date_trunc(date_received, WEEK(MONDAY)) AS week_start, segment, product,
               sum(n_complaints) AS complaints, sum(n_relief) AS relief, sum(n_in_progress) AS in_progress
        FROM `{ds}.wh_complaints_daily`
        GROUP BY 1, 2, 3
        ORDER BY 1
    """,
    "top_series": """
        WITH w AS (
            SELECT company, product, issue, date_trunc(date_received, WEEK(MONDAY)) AS week_start,
                   sum(n_complaints) AS complaints
            FROM `{ds}.wh_complaints_daily` WHERE segment = 'other' GROUP BY 1, 2, 3, 4
        ), top AS (
            SELECT company, product, issue FROM w GROUP BY 1, 2, 3 ORDER BY sum(complaints) DESC LIMIT 300
        )
        SELECT w.* FROM w JOIN top USING (company, product, issue) ORDER BY week_start
    """,
    "pipeline_runs": """
        SELECT run_id, as_of, started_at, finished_at, status, step, rows_loaded, snapshot_rows,
               api_latest_date, message
        FROM `{ds}.pipeline_runs` ORDER BY started_at DESC LIMIT 200
    """,
    # `rows` is a reserved word in BigQuery and must be quoted.
    "drift": "SELECT as_of, metric, value, status, `rows` FROM `{ds}.drift_metrics` ORDER BY as_of DESC LIMIT 400",
    "triage_summary": """
        SELECT as_of, priority, count(*) AS complaints, avg(relief_probability) AS mean_probability,
               countif(already_closed) AS already_closed
        FROM `{ds}.triage_scores` GROUP BY 1, 2 ORDER BY 1 DESC
    """,
    "triage_top": """
        SELECT as_of, complaint_id, date_received, company, product, issue, relief_probability, priority,
               company_response, days_since_received
        FROM `{ds}.triage_scores`
        WHERE TRUE
        QUALIFY row_number() OVER (PARTITION BY as_of ORDER BY relief_probability DESC) <= 200
        ORDER BY as_of DESC, relief_probability DESC
    """,
    "vintages": """
        SELECT as_of, segment, week_start, age, n_published
        FROM `{ds}.snapshot_vintages` ORDER BY as_of, week_start
    """,
}


class ExportFailed(RuntimeError):
    """Raised when any query fails, so a partial or empty export is never published over good data."""


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def export_serving(client, project: str, out_dir: Path, dataset: str = "complaint_radar") -> dict[str, int]:
    """Run each query and write `<name>.json` plus `meta.json`. Raises ExportFailed if any query fails."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts, failed = {}, {}
    for name, sql in QUERIES.items():
        try:
            rows = [dict(r.items()) for r in client.query(sql.format(ds=f"{project}.{dataset}")).result()]
        except Exception as exc:
            log.error("serving export %s failed: %s", name, exc)
            failed[name] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        (out_dir / f"{name}.json").write_text(json.dumps(rows, default=_json_default), encoding="utf-8")
        counts[name] = len(rows)
    if failed:
        raise ExportFailed(f"serving export failed for {sorted(failed)}: {failed}")
    meta = {"exported_at": datetime.now(UTC).isoformat(), "rows": counts}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return counts

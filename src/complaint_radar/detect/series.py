"""Weekly complaint-count series per (segment, company, product, issue)."""

from datetime import date

import duckdb
import pandas as pd

SERIES_KEY = ["segment", "company", "product", "issue"]


def weekly_series(con: duckdb.DuckDBPyConnection, daily_table: str, start: date, end: date, min_peak: int = 0):
    """Zero-filled weekly counts (weeks start Monday) from each series' first week up to `end`.

    `min_peak` drops series whose busiest week never reaches that count. Such series can never pass
    the alert gate (n >= 20), and leaving them out keeps the grid small.
    """
    return con.execute(
        f"""
        WITH w AS (
            SELECT segment, company, product, coalesce(issue, '(none)') AS issue,
                   date_trunc('week', date_received)::DATE AS week, sum(n_complaints) AS n
            FROM {daily_table}
            WHERE date_received BETWEEN ? AND ?
            GROUP BY ALL
        ),
        s AS (
            SELECT segment, company, product, issue, min(week) AS first_week
            FROM w GROUP BY ALL HAVING max(n) >= ?
        ),
        grid AS (
            SELECT s.segment, s.company, s.product, s.issue,
                   unnest(generate_series(
                       s.first_week, date_trunc('week', ?::DATE)::DATE, INTERVAL 7 DAY
                   ))::DATE AS week
            FROM s
        )
        SELECT g.segment, g.company, g.product, g.issue, g.week::TIMESTAMP AS week, coalesce(w.n, 0)::BIGINT AS n
        FROM grid g LEFT JOIN w USING (segment, company, product, issue, week)
        ORDER BY g.segment, g.company, g.product, g.issue, g.week
        """,
        [start, end, min_peak, end],
    ).df()


def series_groups(df: pd.DataFrame):
    return df.groupby(SERIES_KEY, sort=False, observed=True)

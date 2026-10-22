"""Label alerts and incidents by the kind of pattern behind them.

- Live (structured data only): when the same product + issue spikes for many companies in the same week,
  the cause is usually shared (a credit-repair dispute wave, news, a regulation) rather than one
  company's failure. Those alerts are grouped as a `cross_company_wave`.
- Archive (text available): the share of near-duplicate narratives in an incident shows whether its
  volume was amplified by templates or a coordinated campaign.
"""

import pandas as pd

from complaint_radar.text.near_dup import campaign_share

WAVE_MIN_COMPANIES = 5
TEMPLATE_AMPLIFIED_SHARE = 0.30


def flag_cross_company_waves(alerts: pd.DataFrame, min_companies: int = WAVE_MIN_COMPANIES) -> pd.DataFrame:
    out = alerts.copy()
    if out.empty:
        return out.assign(wave_companies=pd.Series(dtype="int64"), pattern=pd.Series(dtype="object"))
    out["wave_companies"] = out.groupby(["week_start", "product", "issue"])["company"].transform("nunique")
    out["pattern"] = (out["wave_companies"] >= min_companies).map({True: "cross_company_wave", False: "single_company"})
    return out


_TEXTS_SQL = (
    "SELECT narrative FROM stg_complaints "
    "WHERE company = ? AND product = ? AND coalesce(issue, '(none)') = ? "
    "AND has_narrative AND date_received >= ? AND date_received < ?"
)


def _texts(con, company: str, product: str, issue: str, lo: pd.Timestamp, hi: pd.Timestamp) -> list[str]:
    return [r[0] for r in con.execute(_TEXTS_SQL, [company, product, issue, lo.date(), hi.date()]).fetchall()]


def score_incident_campaigns(con, incidents: pd.DataFrame, min_texts: int = 30) -> pd.DataFrame:
    """Near-duplicate share of narratives during each incident, and in the 6 months before it."""
    rows = []
    for inc in incidents.itertuples():
        start = pd.Timestamp(inc.start_month)
        end = pd.Timestamp(inc.end_month) + pd.offsets.MonthBegin(1)
        key = (inc.company, inc.product, inc.issue)
        during = _texts(con, *key, start, end)
        before = _texts(con, *key, start - pd.DateOffset(months=6), start)
        if len(during) < min_texts:
            continue
        share = campaign_share(during)
        rows.append(
            {
                "company": inc.company,
                "product": inc.product,
                "issue": inc.issue,
                "start_month": start.date().isoformat(),
                "peak_week": pd.Timestamp(inc.peak_week).date().isoformat(),
                "complaints": int(inc.n),
                "texts": len(during),
                "near_dup_share": round(share, 3),
                "near_dup_share_before": round(campaign_share(before), 3) if len(before) >= min_texts else None,
                "label": "template_amplified" if share >= TEMPLATE_AMPLIFIED_SHARE else "organic",
            }
        )
    return pd.DataFrame(rows)

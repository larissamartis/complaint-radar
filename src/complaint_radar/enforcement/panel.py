"""Company-month panel for the enforcement study.

Each row is (company, month t) as seen at the *start* of month t:
- features use complaints from months t-12 .. t-1 only;
- target = 1 if a CFPB enforcement action against the company is filed in months t .. t+11;
- rows are dropped when an action against the company was filed in the previous 12 months, because complaint
  waves often *follow* public actions (news-driven), and keeping them would let the model "predict" an action
  from its own aftermath.
"""

import numpy as np
import pandas as pd

HORIZON = 12
LOOKBACK = 12
RECENT = 3
MIN_VOLUME = 50  # complaints in the 12-month lookback for a company-month to be eligible

FEATURES = [
    "log_volume_12m",
    "growth_3m_vs_prior",
    "relief_rate_12m",
    "untimely_rate_12m",
    "issue_shift_jsd",
    "n_issues_12m",
    "top_issue_share_12m",
    "log_months_active",
    "is_bureau",
]

MONTHLY_SQL = """
    SELECT company, any_value(segment) AS segment, date_trunc('month', date_received)::DATE AS month, issue,
           sum(n_complaints) AS n, sum(n_relief) AS relief, sum(n_untimely) AS untimely
    FROM fct_complaints_daily
    GROUP BY company, month, issue
"""


def _jsd(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Row-wise Jensen-Shannon divergence (base 2, in [0, 1]) between count matrices."""
    p = p / np.maximum(p.sum(axis=1, keepdims=True), 1e-12)
    q = q / np.maximum(q.sum(axis=1, keepdims=True), 1e-12)
    m = 0.5 * (p + q)

    def kl(a, b):
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(a > 0, a * np.log2(a / np.where(b > 0, b, 1)), 0.0).sum(axis=1)

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def _window_sum(cum: np.ndarray, t: np.ndarray, lo: int, hi: int) -> np.ndarray:
    """Sum over months [t-lo, t-hi) using a cumulative array with a leading zero row."""
    a, b = np.clip(t - lo, 0, None), np.clip(t - hi, 0, None)
    return cum[b] - cum[a]


def build_panel(monthly: pd.DataFrame, actions: pd.DataFrame, start: str, end: str, min_volume: int = MIN_VOLUME):
    """monthly: company, segment, month, issue, n, relief, untimely. actions: company (complaint name), date_filed."""
    monthly = monthly.copy()
    monthly["month"] = pd.to_datetime(monthly["month"]).dt.to_period("M")
    act = actions.assign(m=pd.to_datetime(actions["date_filed"]).dt.to_period("M"))
    act_months = act.groupby("company")["m"].apply(lambda s: np.array(sorted({p.ordinal for p in s})))
    start_p, end_p = pd.Period(start, "M"), pd.Period(end, "M")
    issues = {k: i for i, k in enumerate(sorted(monthly["issue"].fillna("(none)").unique()))}

    parts = []
    for company, g in monthly.groupby("company", sort=False):
        first, last = g["month"].min(), max(g["month"].max(), end_p)
        months = pd.period_range(first, last, freq="M")
        idx = {p: i for i, p in enumerate(months)}
        n_m = len(months)
        tot = np.zeros((n_m, 3))
        iss = np.zeros((n_m, len(issues)))
        rows = g["month"].map(idx).to_numpy()
        np.add.at(tot, rows, g[["n", "relief", "untimely"]].to_numpy(dtype=float))
        np.add.at(iss, (rows, g["issue"].fillna("(none)").map(issues).to_numpy()), g["n"].to_numpy(dtype=float))
        cum = np.vstack([np.zeros((1, 3)), np.cumsum(tot, axis=0)])
        cum_i = np.vstack([np.zeros((1, len(issues))), np.cumsum(iss, axis=0)])

        t = np.arange(n_m)
        keep = (months >= start_p) & (months <= end_p)
        t = t[keep]
        if len(t) == 0:
            continue
        vol12, relief12, untimely12 = (_window_sum(cum[:, k], t, LOOKBACK, 0) for k in range(3))
        vol3 = _window_sum(cum[:, 0], t, RECENT, 0)
        prior = _window_sum(cum[:, 0], t, LOOKBACK, RECENT)
        recent_issues = cum_i[t] - cum_i[np.clip(t - RECENT, 0, None)]
        prior_issues = cum_i[np.clip(t - RECENT, 0, None)] - cum_i[np.clip(t - LOOKBACK, 0, None)]
        year_issues = cum_i[t] - cum_i[np.clip(t - LOOKBACK, 0, None)]

        ords = np.array([m.ordinal for m in months[t]])
        a = act_months.get(company, np.array([], dtype=int))
        target = np.array([((a >= o) & (a < o + HORIZON)).any() for o in ords])
        recent_action = np.array([((a >= o - LOOKBACK) & (a < o)).any() for o in ords])

        frame = pd.DataFrame(
            {
                "company": company,
                "month": months[t].to_timestamp(),
                "log_volume_12m": np.log1p(vol12),
                "growth_3m_vs_prior": np.log((vol3 / RECENT + 1) / (prior / (LOOKBACK - RECENT) + 1)),
                "relief_rate_12m": relief12 / np.maximum(vol12, 1),
                "untimely_rate_12m": untimely12 / np.maximum(vol12, 1),
                "issue_shift_jsd": _jsd(recent_issues, prior_issues),
                "n_issues_12m": (year_issues > 0).sum(axis=1),
                "top_issue_share_12m": year_issues.max(axis=1) / np.maximum(year_issues.sum(axis=1), 1),
                "log_months_active": np.log1p(t),
                "is_bureau": int((g["segment"] == "bureau").any()),
                "volume_12m": vol12,
                "target": target.astype(int),
                "recent_action": recent_action,
            }
        )
        parts.append(frame[(frame["volume_12m"] >= min_volume) & ~frame["recent_action"]])
    panel = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["company", "month", *FEATURES])
    return panel.drop(columns="recent_action", errors="ignore")

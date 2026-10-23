"""Complaint Radar dashboard (Streamlit)."""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import data  # noqa: E402
import ui  # noqa: E402

st.set_page_config(page_title="Complaint Radar", page_icon=":material/radar:", layout="wide")
ui.inject_css()

alerts = data.serving("alerts")
weekly = data.serving("weekly_volume")
series = data.serving("top_series")
runs = data.serving("pipeline_runs")
drift = data.serving("drift")
triage_summary = data.serving("triage_summary")
triage_top = data.serving("triage_top")
vintages = data.serving("vintages")
meta = data.serving_meta()

for df, cols in ((alerts, ["week_start", "as_of"]), (weekly, ["week_start"]), (series, ["week_start"]),
                 (runs, ["as_of"]), (drift, ["as_of"]), (triage_summary, ["as_of"]), (triage_top, ["as_of"]),
                 (vintages, ["as_of", "week_start"])):  # fmt: skip
    for c in cols:
        if c in df:
            df[c] = pd.to_datetime(df[c])

# Alerts saved before pattern labelling existed have no pattern: apply the same rule here so every alert has one
# (5+ companies with the same product + issue in the same week = a cross-company wave).
if not alerts.empty:
    waves = alerts.groupby(["week_start", "product", "issue"])["company"].transform("nunique")
    missing = alerts["pattern"].isna()
    alerts.loc[missing, "wave_companies"] = waves[missing]
    alerts.loc[missing, "pattern"] = (waves[missing] >= 5).map({True: "cross_company_wave", False: "single_company"})


def complete_weeks(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the first and current week: they are only partly inside the 60-day window and would dip to zero."""
    if df.empty:
        return df
    weeks = sorted(df["week_start"].unique())
    return df[df["week_start"].isin(weeks[1:-1])] if len(weeks) > 2 else df


# ---------------------------------------------------------------- header
last_run = runs.iloc[0] if not runs.empty else None
status_html = (
    ui.mapped_badge(last_run["status"], ui.RUN_BADGE) if last_run is not None else ui.badge("No runs yet", "neutral")
)
updated = meta.get("exported_at", "")[:16].replace("T", " ")
st.markdown(
    f'<div class="cr-header"><div><p class="cr-title">Complaint Radar</p>'
    f'<p class="cr-sub">Early warning for customer complaints at US banks, lenders and fintechs '
    f"(public CFPB data, updated daily)</p></div>"
    f'<div>{status_html} <span class="cr-muted">&nbsp;Data refreshed {updated or "—"} UTC</span></div></div>',
    unsafe_allow_html=True,
)

if st.button("Refresh data", icon=":material/refresh:", type="tertiary", key="refresh"):
    st.cache_data.clear()
    st.rerun()

if not meta:
    st.info(
        "Live data has not been published yet. The daily pipeline publishes it after its next run (11:30 UTC); "
        "research results below are already available.",
        icon=":material/schedule:",
    )

tabs = st.tabs([
    ":material/dashboard: Overview",
    ":material/notifications_active: Alerts",
    ":material/show_chart: Trends",
    ":material/assignment_turned_in: Triage",
    ":material/science: Research",
    ":material/monitor_heart: Data health",
    ":material/info: About",
])  # fmt: skip

latest_week = alerts["week_start"].max() if not alerts.empty else None
week_alerts = alerts[alerts["week_start"] == latest_week] if latest_week is not None else alerts

# ---------------------------------------------------------------- overview
with tabs[0]:
    window_total = weekly["complaints"].sum() if not weekly.empty else None
    waves = int((week_alerts.get("pattern") == "cross_company_wave").sum()) if not week_alerts.empty else 0
    latest_triage = (
        triage_summary[triage_summary["as_of"] == triage_summary["as_of"].max()] if not triage_summary.empty else None
    )
    high = (
        int(latest_triage.loc[latest_triage["priority"] == "high", "complaints"].sum())
        if latest_triage is not None
        else None
    )
    scored = int(latest_triage["complaints"].sum()) if latest_triage is not None else None
    ui.kpi_row([
        ui.kpi("Complaints, last 60 days", ui.fmt_int(window_total), "all companies, published so far",
               "inbox", ui.SERIES[0]),
        ui.kpi("Alerts this week", ui.fmt_int(len(week_alerts)),
               f"{waves} in a cross-company wave", "notifications_active", ui.SERIES[1]),
        ui.kpi("High-priority complaints", ui.fmt_int(high), f"of {ui.fmt_int(scored)} scored in the last run",
               "priority_high", ui.SERIES[6]),
        ui.kpi("Last pipeline run", last_run["status"].replace("_", " ").capitalize() if last_run is not None else "—",
               f"{last_run['as_of']:%d %b %Y}" if last_run is not None else "no runs recorded", "sync", ui.SERIES[2]),
    ])  # fmt: skip
    st.write("")
    left, right = st.columns([3, 2], gap="large")
    with left:
        ui.panel_head("Top alerts this week", "campaign")
        st.caption(
            "An alert means a company's complaints about one issue rose well above its usual level "
            "(at least 1.75× the expected count and 20+ complaints)."
        )
        if week_alerts.empty:
            st.info("No alerts yet. Alerts appear after the daily pipeline scores a complete week.")
        for _, a in week_alerts.sort_values("score", ascending=False).head(5).iterrows():
            with st.container(border=True):
                st.markdown(
                    f"**{a['company']}** · {a['issue']}<br><span class='cr-muted'>{ui.short_product(a['product'])}</span><br>"
                    f"{ui.mapped_badge(a.get('pattern'), ui.PATTERN_BADGE)} "
                    f"{ui.badge(f'{a["score"]:.1f}× usual', 'warning', 'trending_up')} "
                    f"{ui.badge(f'{int(a["n"])} complaints', 'neutral')}",
                    unsafe_allow_html=True,
                )
                if isinstance(a.get("summary"), str):
                    st.markdown(f"<div class='cr-summary'>{a['summary']}</div>", unsafe_allow_html=True)
    with right:
        ui.panel_head("Weekly complaints by product (non-bureau)", "stacked_line_chart")
        if weekly.empty:
            st.info("Weekly volume appears after the first pipeline run.")
        else:
            other = complete_weeks(weekly[weekly["segment"] == "other"])
            other = other.assign(product=other["product"].map(ui.short_product))
            top = other.groupby("product")["complaints"].sum().nlargest(4).index.tolist()
            other = other.assign(product=other["product"].where(other["product"].isin(top), "Other products"))
            plot = other.groupby(["week_start", "product"], as_index=False)["complaints"].sum()
            domain = [*top, "Other products"]
            st.altair_chart(
                ui.line_chart(plot, "week_start", "complaints", "product",
                              ["week_start:T", "product:N", ui.tip("complaints")], domain=domain, y_title="Complaints"),
                use_container_width=True,
            )  # fmt: skip
            st.caption(
                "The last two weeks are still filling in: the CFPB publishes most complaints only after the company "
                "responds (1–3 weeks). Credit bureaus are left out here because their volume is about ten times larger."
            )


# ---------------------------------------------------------------- alerts
with tabs[1]:
    ui.panel_head("Emerging-issue alerts", "notifications_active")
    st.caption(
        "Each row is one company × product × issue whose weekly complaints rose unusually fast. "
        "**Expected** is the usual weekly count adjusted for how much of the week is published so far; "
        "**Ratio** is complaints ÷ expected."
    )
    if alerts.empty:
        st.info("No alerts recorded yet.")
    else:
        f1, f2, f3 = st.columns([2, 1, 1])
        q = f1.text_input("Search company, product or issue", key="alert_search", placeholder="e.g. Navy Federal")
        weeks = sorted(alerts["week_start"].dt.date.unique(), reverse=True)
        week = f2.selectbox("Week starting", ["All weeks", *weeks], key="alert_week")
        pattern = f3.selectbox("Pattern", ["All", "Single company", "Cross-company wave"], key="alert_pattern")
        view = alerts.copy()
        if q:
            mask = (
                view[["company", "product", "issue"]]
                .apply(lambda s: s.str.contains(q, case=False, na=False))
                .any(axis=1)
            )
            view = view[mask]
        if week != "All weeks":
            view = view[view["week_start"].dt.date == week]
        if pattern != "All":
            view = view[view["pattern"] == ("cross_company_wave" if pattern.startswith("Cross") else "single_company")]
        view = view.sort_values(["week_start", "score"], ascending=[False, False])
        table = pd.DataFrame({
            "Week": view["week_start"].dt.date, "Company": view["company"], "Product": view["product"].map(ui.short_product),
            "Issue": view["issue"], "Complaints": view["n"].astype(int), "Expected": view["expected"].round(1),
            "Ratio": view["score"].round(1),
            "Pattern": view["pattern"].map({"cross_company_wave": "Cross-company wave", "single_company": "Single company"}),
        })  # fmt: skip
        page = ui.paginate(table.reset_index(drop=True), key="alert_page")
        st.dataframe(page, hide_index=True, use_container_width=True, column_config={
            "Ratio": st.column_config.NumberColumn(format="%.1f×"),
            "Issue": st.column_config.TextColumn(width="large"),
        })  # fmt: skip
        if not view.empty:
            ui.panel_head("Alert details", "description")
            labels = [f"{r.week_start:%d %b} · {r.company} · {r.issue}" for r in view.itertuples()]
            pick = st.selectbox(
                "Choose an alert", range(len(labels)), format_func=lambda i: labels[i], key="alert_pick"
            )
            a = view.iloc[pick]
            st.markdown(
                f"{ui.mapped_badge(a.get('pattern'), ui.PATTERN_BADGE)} "
                f"{ui.badge(f'{a["score"]:.1f}× usual', 'warning', 'trending_up')} "
                f"{ui.badge(f'week {int(a["week_age"])} ago · {a["completeness"]:.0%} published', 'neutral', 'schedule')}",
                unsafe_allow_html=True,
            )
            if isinstance(a.get("summary"), str):
                method = (
                    "written by a local language model, numbers checked"
                    if a.get("summary_method") == "llm"
                    else "template"
                )
                st.markdown(f"<div class='cr-summary'>{a['summary']}</div>", unsafe_allow_html=True)
                st.caption(f"Summary: {method}.")
            topics = json.loads(a["typical_topics"]) if isinstance(a.get("typical_topics"), str) else []
            if topics:
                st.markdown(
                    "**What customers usually describe for this product and issue** (from archived complaints):"
                )
                for t in topics:
                    st.markdown(f"- {t['label']} — {t['share']:.0%} of archived complaints")

# ---------------------------------------------------------------- trends
with tabs[2]:
    ui.panel_head("Weekly trend for one company and issue", "show_chart")
    st.caption("The 300 largest non-bureau company × issue series in the last 60 days.")
    if series.empty:
        st.info("Trend data appears after the first pipeline run.")
    else:
        c1, c2 = st.columns(2)
        company = c1.selectbox("Company", sorted(series["company"].unique()), key="trend_company")
        sub = series[series["company"] == company]
        issue = c2.selectbox("Issue", sorted(sub["issue"].unique()), key="trend_issue")
        plot = complete_weeks(sub[sub["issue"] == issue]).groupby("week_start", as_index=False)["complaints"].sum()
        st.altair_chart(
            ui.line_chart(plot, "week_start", "complaints", None, ["week_start:T", ui.tip("complaints")],
                          y_title="Complaints per week"),
            use_container_width=True,
        )  # fmt: skip
        st.caption(
            "Recent weeks are incomplete because of the CFPB's publication delay; the alert logic adjusts for this."
        )

# ---------------------------------------------------------------- triage
with tabs[3]:
    ui.panel_head("Escalation triage", "assignment_turned_in")
    st.caption(
        "The triage model estimates how likely a complaint is to end with the company giving relief (money back or "
        "another fix), using only details known when the complaint arrives. **High** = top 10% of scores, "
        "**Medium** = next 20%."
    )
    perf = data.result("triage").get("test_all_rows", {})
    if perf:
        names = {
            "baseline_product_issue_rate": "Baseline: historical rate for product × issue",
            "logistic_regression_fields": "Logistic regression",
            "lightgbm_fields_calibrated": "LightGBM (in use)",
        }
        st.dataframe(pd.DataFrame([
            {"Model (tested on 2025)": names.get(k, k), "ROC-AUC": round(m["roc_auc"], 3), "PR-AUC": round(m["pr_auc"], 3),
             "Relief rate in top 10%": f"{m['precision_top10']:.0%}", "Lift vs random": f"{m['lift_top10']:.1f}×"}
            for k, m in perf.items()
        ]), hide_index=True, use_container_width=True)  # fmt: skip
    if not triage_top.empty:
        latest = triage_top[triage_top["as_of"] == triage_top["as_of"].max()]
        q = st.text_input("Search scored complaints", key="triage_search", placeholder="company, product or issue")
        if q:
            latest = latest[latest[["company", "product", "issue"]].apply(
                lambda s: s.str.contains(q, case=False, na=False)).any(axis=1)]  # fmt: skip
        table = pd.DataFrame({
            "Complaint ID": latest["complaint_id"], "Received": pd.to_datetime(latest["date_received"]).dt.date,
            "Company": latest["company"], "Product": latest["product"].map(ui.short_product), "Issue": latest["issue"],
            "Relief probability": latest["relief_probability"], "Priority": latest["priority"].str.title(),
            "Status": latest["company_response"].fillna("—"),
        })  # fmt: skip
        st.dataframe(ui.paginate(table, key="triage_page"), hide_index=True, use_container_width=True,
                     column_config={"Relief probability": st.column_config.ProgressColumn(format="percent", min_value=0,
                                                                                          max_value=1)})  # fmt: skip
        st.caption("Public CFPB complaints are published after the company responds, so many are already closed when "
                   "scored; inside a bank this model would score at intake.")  # fmt: skip
    ui.panel_head("Score a complaint", "calculate")
    with st.form("score_form"):
        c1, c2, c3 = st.columns(3)
        product = c1.selectbox("Product", ["Credit card", "Checking or savings account", "Debt collection", "Mortgage",
                                            "Money transfer, virtual currency, or money service", "Student loan",
                                            "Vehicle loan or lease", "Credit reporting or other personal consumer reports"])  # fmt: skip
        issue = c2.text_input("Issue", "Problem with a purchase shown on your statement")
        company = c3.text_input("Company", "CAPITAL ONE FINANCIAL CORPORATION")
        c4, c5, c6 = st.columns(3)
        state = c4.text_input("State (2 letters)", "CA")
        channel = c5.selectbox("Submitted via", ["Web", "Phone", "Referral", "Postal mail", "Email", "Fax"])
        tags = c6.selectbox("Tags", ["None", "Older American", "Servicemember", "Older American, Servicemember"])
        go = st.form_submit_button("Score complaint", type="primary")
    if go:
        try:
            from complaint_radar.triage.model import priority
            from complaint_radar.triage.scoring import load_triage_model

            model = load_triage_model()
            row = pd.DataFrame([{"date_received": date.today(), "product": product, "issue": issue, "company": company,
                                 "state": state or None, "submitted_via": channel,
                                 "tags": None if tags == "None" else tags}])  # fmt: skip
            p = float(model.predict(row)[0])
            pr = priority(p, model.metadata.get("reference_score_quantiles", []))
            st.markdown(f"Relief probability **{p:.0%}** &nbsp; {ui.mapped_badge(pr, ui.PRIORITY_BADGE)}",
                        unsafe_allow_html=True)  # fmt: skip
            reasons = model.reasons(row)[0]
            st.markdown("Main factors (positive pushes the score up):")
            st.dataframe(pd.DataFrame(reasons).rename(columns={"feature": "Factor", "value": "Value", "effect": "Effect"}),
                         hide_index=True)  # fmt: skip
        except Exception as exc:  # model not packaged in this deployment
            st.warning(f"Scoring is unavailable here ({type(exc).__name__}).")

# ---------------------------------------------------------------- research
with tabs[4]:
    section = st.radio("Topic", ["Early-warning backtest", "Campaigns", "Topics", "Enforcement study"],
                       horizontal=True, key="research_section")  # fmt: skip
    if section == "Early-warning backtest":
        ui.panel_head("Would the radar have flagged past incidents?", "history")
        bt = data.result("backtest")
        dets = bt.get("segments", {}).get("other", {}).get("detectors", {})
        if dets:
            nice = {
                "volume_rule": "Volume rule (simple baseline, in use)",
                "robust_z": "Robust z-score",
                "nb_surprise": "Negative-binomial surprise",
            }
            st.dataframe(pd.DataFrame([
                {"Detector": nice.get(k, k), "Incidents caught": f"{v['test']['recall']:.0%}",
                 "Caught ≥14 days before peak": f"{v['test'].get('share_caught_14d_early', float('nan')):.0%}",
                 "Median warning (days)": v["test"]["median_lead_days"],
                 "False alarms per 100 series-months": round(v["test"]["false_alarms_per_100_series_months"], 1)}
                for k, v in dets.items()
            ]), hide_index=True, use_container_width=True)  # fmt: skip
            st.caption("Test period 2022 – May 2026, non-bureau companies. The simple volume rule was not beaten.")
        named = pd.DataFrame(bt.get("named_incidents", []))
        if not named.empty and "volume_rule_lead_days" in named:
            named = named.assign(
                peak_week=named["peak_week"].fillna("not an incident"),
                volume_rule_lead_days=named["volume_rule_lead_days"]
                .astype("object")
                .where(named["volume_rule_lead_days"].notna(), "—"),
            )
            st.markdown("**Named incidents**")
            st.dataframe(named[["company", "issue", "month", "peak_week", "volume_rule_lead_days"]].rename(columns={
                "company": "Company", "issue": "Issue", "month": "Month", "peak_week": "Peak week",
                "volume_rule_lead_days": "Alert before peak (days)"}), hide_index=True, use_container_width=True)  # fmt: skip
    elif section == "Campaigns":
        ui.panel_head("Template and campaign-driven complaint waves", "content_copy")
        camp = data.result("campaigns")
        inc = pd.DataFrame(camp.get("incidents", []))
        if not inc.empty:
            s = camp["summary"]
            st.markdown(f"**{s['template_amplified']} of {s['incidents_scored']} incidents** "
                        f"({s['share_template_amplified']:.0%}) were mostly near-identical complaint texts.")  # fmt: skip
            inc["year"] = inc["start_month"].str[:4]
            inc["Type"] = inc["label"].map({"organic": "Organic", "template_amplified": "Template-amplified"})
            by_year = inc.groupby(["year", "Type"], as_index=False).size()
            import altair as alt

            chart = alt.Chart(by_year).mark_bar(cornerRadiusEnd=4, stroke="#fcfcfb", strokeWidth=2).encode(
                x=alt.X("year:O", title=None), y=alt.Y("size:Q", title="Incidents", stack=True),
                color=alt.Color("Type:N", title=None, scale=alt.Scale(domain=["Organic", "Template-amplified"],
                                                                       range=ui.SERIES[:2])),
                tooltip=["year:O", "Type:N", "size:Q"])  # fmt: skip
            st.altair_chart(ui._style(chart, 260), use_container_width=True)
            top = inc[inc["label"] == "template_amplified"].sort_values("complaints", ascending=False)
            st.dataframe(top[["start_month", "company", "issue", "complaints", "near_dup_share"]].rename(columns={
                "start_month": "Start", "company": "Company", "issue": "Issue", "complaints": "Complaints",
                "near_dup_share": "Near-duplicate share"}), hide_index=True, use_container_width=True,
                column_config={"Near-duplicate share": st.column_config.ProgressColumn(format="percent", min_value=0,
                                                                                        max_value=1)})  # fmt: skip
    elif section == "Topics":
        ui.panel_head("What complaints are about (archived narratives)", "category")
        tp = data.result("topics")
        if tp:
            d = tp.get("distillation", {})
            st.markdown(f"**{tp.get('topics')} topics** discovered from {tp.get('sample_docs', 0):,} complaints and "
                        f"applied to {tp.get('corpus_docs', 0):,}. Text predicts a complaint's topic with "
                        f"{d.get('text_classifier', {}).get('accuracy', 0):.0%} accuracy, against "
                        f"{d.get('product_issue_baseline', {}).get('accuracy', 0):.0%} from product and issue alone.")  # fmt: skip
            topics = pd.DataFrame(tp.get("topic_list", [])).head(15)
            if not topics.empty:
                st.altair_chart(ui.bar_chart(topics, "label", "complaints_in_corpus",
                                             ["label:N", ui.tip("complaints_in_corpus")], height=420,
                                             val_title="Complaints (2019–2025)"), use_container_width=True)  # fmt: skip
    else:
        ui.panel_head("Do complaints warn of CFPB enforcement in advance?", "gavel")
        enf = data.result("enforcement")
        if not enf:
            st.info("The enforcement study results are not published yet.")
        else:
            st.dataframe(pd.DataFrame([
                {"Model (test 2020–2024)": k.replace("_", " ").capitalize(), "ROC-AUC": round(m["roc_auc"], 3),
                 "PR-AUC": round(m["pr_auc"], 3), "Lift in top 1%": round(m["lift_top1pct"], 1)}
                for k, m in enf.get("test", {}).items()
            ]), hide_index=True, use_container_width=True)  # fmt: skip
            g = enf.get("gain_over_volume_pr_auc", {})
            if g:
                lo, hi = g["ci95"]
                verdict = "a real gain" if lo > 0 else "no reliable gain"
                st.markdown(f"Gain of complaint patterns over volume alone (PR-AUC): **{g['mean_diff']:+.3f}** "
                            f"(95% interval {lo:+.3f} to {hi:+.3f}) — {verdict}.")  # fmt: skip

# ---------------------------------------------------------------- data health
with tabs[5]:
    left, right = st.columns(2, gap="large")
    with left:
        ui.panel_head("Pipeline runs", "sync")
        if runs.empty:
            st.info("No runs recorded yet.")
        else:
            st.dataframe(pd.DataFrame({
                "Date": runs["as_of"].dt.date, "Status": runs["status"].str.replace("_", " ").str.capitalize(),
                "Step": runs["step"], "Rows loaded": runs["rows_loaded"], "Message": runs["message"].fillna("—"),
            }).head(30), hide_index=True, use_container_width=True)  # fmt: skip
    with right:
        ui.panel_head("Model drift (Population Stability Index)", "monitor_heart")
        st.caption("Below 0.10 = stable, 0.10–0.25 = moderate shift, above 0.25 = significant shift.")
        valid = drift.dropna(subset=["value"]) if not drift.empty else drift
        if valid.empty:
            st.info("Drift appears once enough new complaints are scored (at least 200 a day).")
        else:
            st.altair_chart(ui.line_chart(valid, "as_of", "value", "metric", ["as_of:T", "metric:N", "value:Q"],
                                          domain=["product_mix_psi", "score_psi"], y_title="PSI"),
                            use_container_width=True)  # fmt: skip
    ui.panel_head("How complete recent weeks are", "hourglass_bottom")
    if vintages.empty:
        st.info("Completeness snapshots are recorded daily from the first run onwards.")
    else:
        v = vintages[vintages["as_of"] == vintages["as_of"].max()]
        mature = v[v["age"] >= 4].groupby("segment")["n_published"].median()
        v = v[v["age"].between(1, 4)].assign(share=lambda d: d["n_published"] / d["segment"].map(mature))
        v["Segment"] = v["segment"].map({"other": "Other companies", "bureau": "Credit bureaus"})
        v["Week"] = v["age"].map({1: "Last week", 2: "2 weeks ago", 3: "3 weeks ago", 4: "4 weeks ago"})
        import altair as alt

        chart = alt.Chart(v).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("Week:N", sort=["Last week", "2 weeks ago", "3 weeks ago", "4 weeks ago"], title=None),
            xOffset="Segment:N", y=alt.Y("share:Q", title="Share published", axis=alt.Axis(format="%")),
            color=alt.Color("Segment:N", title=None, scale=alt.Scale(domain=["Other companies", "Credit bureaus"],
                                                                      range=ui.SERIES[:2])),
            tooltip=["Week:N", "Segment:N", alt.Tooltip("share:Q", format=".0%")])  # fmt: skip
        st.altair_chart(ui._style(chart, 240), use_container_width=True)

# ---------------------------------------------------------------- about
with tabs[6]:
    ui.panel_head("What this is", "info")
    st.markdown(
        """
Complaint Radar watches the US **Consumer Financial Protection Bureau (CFPB)** complaint database — complaints about
banks, credit cards, lenders, debt collectors and payment apps — and flags problems that are growing unusually fast.

**How it works, in short**
- Every day a pipeline downloads the full public complaint file, checks it against a *data contract* (rules the data
  must follow), and loads new or changed complaints into a Google BigQuery warehouse.
- It compares each company's weekly complaints about each issue with its usual level and raises an **alert** when they
  jump. Because the CFPB publishes complaints 1–3 weeks late, recent weeks are adjusted for how complete they are.
- Alerts are labelled as a **single-company** problem or a **cross-company wave** (the same issue rising at many companies,
  which points to a shared cause), and get a short plain-English summary.
- A **triage model** estimates which complaints are likely to end with the customer getting relief.

**Words used here**
- *Expected* — the usual weekly number of complaints for that company and issue, adjusted for publication delay.
- *Ratio* — complaints this week ÷ expected.
- *Template-amplified* — most complaints in a wave are near-copies of the same text (often a shared template or campaign).
- *Relief* — the company gave the customer money back or another fix.
- *PSI* — Population Stability Index, a standard measure of how much incoming data has shifted from what a model learned on.

**Limits**: complaints are not verified by the CFPB and are not a random sample of customers. Since August 2026 the
CFPB no longer publishes complaint text, so topics and examples come from complaints published before then.
        """
    )
    st.caption("Source code: github.com/larissamartis/complaint-radar")

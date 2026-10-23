"""Complaint Radar dashboard (Streamlit)."""

import json
import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import data  # noqa: E402
import ui  # noqa: E402

st.set_page_config(
    page_title="Complaint Radar", page_icon=":material/radar:", layout="wide", initial_sidebar_state="expanded"
)
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


def complete_weeks(df: pd.DataFrame, all_weeks: pd.Series) -> pd.DataFrame:
    """Drop the window's first and current week: they are only partly inside the 60-day window and would dip.

    The weeks come from the whole dataset, not the filtered series, so a quiet series keeps its complete weeks.
    """
    weeks = sorted(all_weeks.dropna().unique())
    if df.empty or len(weeks) <= 2:
        return df
    return df[(df["week_start"] > weeks[0]) & (df["week_start"] < weeks[-1])]


def search(df: pd.DataFrame, q: str) -> pd.DataFrame:
    if not q:
        return df
    return df[df[["company", "product", "issue"]].apply(lambda s: s.str.contains(q, case=False, na=False)).any(axis=1)]


last_run = runs.iloc[0] if not runs.empty else None
updated = meta.get("exported_at", "")[:16].replace("T", " ")
latest_week = alerts["week_start"].max() if not alerts.empty else None
week_alerts = alerts[alerts["week_start"] == latest_week] if latest_week is not None else alerts
backtest, triage_res, campaigns = data.result("backtest"), data.result("triage"), data.result("campaigns")
volume_rule = backtest.get("segments", {}).get("other", {}).get("detectors", {}).get("volume_rule", {}).get("test", {})
triage_best = triage_res.get("test_all_rows", {}).get("lightgbm_fields_calibrated", {})


def not_published_notice() -> None:
    if not meta:
        st.info(
            "Live data has not been published yet. The daily pipeline publishes it after its next run (11:30 UTC); "
            "research results are already available.",
            icon=":material/schedule:",
        )


def alert_item(rank: int, a: pd.Series, with_summary: bool = True) -> str:
    summary = (
        f"<div class='cr-summary'>{ui.safe(a['summary'])}</div>"
        if with_summary and isinstance(a.get("summary"), str)
        else ""
    )
    return (
        f'<div class="cr-alert"><div class="cr-rank">{rank}</div><div class="cr-alert-body">'
        f'<div class="cr-alert-title">{ui.safe(a["company"])}</div>'
        f'<div class="cr-alert-issue">{ui.safe(a["issue"])} · {ui.safe(ui.short_product(a["product"]))}</div>'
        f'<div class="cr-badges">{ui.badge(f"{a['score']:.1f}× usual", "brand", "trending_up")}'
        f"{ui.badge(f'{ui.fmt_int(a["n"])} complaints', 'neutral')}"
        f"{ui.mapped_badge(a.get('pattern'), ui.PATTERN_BADGE)}</div>{summary}</div></div>"
    )


# ---------------------------------------------------------------- pages
def page_overview() -> None:
    week_label = f"Week of {latest_week:%d %b %Y}" if latest_week is not None else "No alerts yet"
    ui.page_header("Dashboard", "Overview", "Emerging complaint issues at US banks, lenders and fintechs",
                   ui.chip(week_label, "calendar_today"))  # fmt: skip
    not_published_notice()

    n_waves = int((week_alerts.get("pattern") == "cross_company_wave").sum()) if not week_alerts.empty else 0
    n_companies = week_alerts["company"].nunique() if not week_alerts.empty else 0
    headline = (
        f"{len(week_alerts)} alerts at {n_companies} companies this week"
        if not week_alerts.empty
        else "No alerts this week yet"
    )
    lead = volume_rule.get("median_lead_days")
    ui.html_block(
        f'<div class="cr-hero"><div><div class="cr-hero-title">{ui.safe(headline)}</div>'
        f"<p>{n_waves} of them are part of a cross-company wave (the same issue rising at 5+ companies). "
        f"Alerts are ranked by how far complaints are above their usual level.</p></div>"
        f'<div class="cr-hero-stats">'
        f'<div class="cr-hero-stat"><b>{volume_rule.get("recall", 0):.0%}</b><span>past incidents caught</span></div>'
        f'<div class="cr-hero-stat"><b>{ui.fmt_int(lead)} days</b><span>median early warning</span></div>'
        f'<div class="cr-hero-stat"><b>{triage_best.get("lift_top10", 0):.1f}×</b><span>triage lift</span></div>'
        f"</div></div>"
    )

    window_total = weekly["complaints"].sum() if not weekly.empty else None
    latest_triage = (
        triage_summary[triage_summary["as_of"] == triage_summary["as_of"].max()] if not triage_summary.empty else None
    )
    high = (
        int(latest_triage.loc[latest_triage["priority"] == "high", "complaints"].sum())
        if latest_triage is not None
        else None
    )
    scored = int(latest_triage["complaints"].sum()) if latest_triage is not None else None
    run_text = str(last_run["status"] or "—").replace("_", " ").capitalize() if last_run is not None else "—"
    run_note = (
        f"{last_run['as_of']:%d %b %Y}" if last_run is not None and pd.notna(last_run["as_of"]) else "no runs recorded"
    )
    ui.kpi_row([
        ui.kpi("Complaints, last 60 days", ui.fmt_int(window_total), "all companies, published so far", "inbox"),
        ui.kpi("Alerts this week", ui.fmt_int(len(week_alerts)), f"{n_waves} in a cross-company wave",
               "notifications_active"),
        ui.kpi("High-priority complaints", ui.fmt_int(high), f"of {ui.fmt_int(scored)} scored in the last run",
               "priority_high"),
        ui.kpi("Last pipeline run", run_text, run_note, "sync"),
    ])  # fmt: skip
    st.write("")

    left, right = st.columns([5, 4], gap="medium")
    with left, ui.card("top-alerts"):
        ui.card_head("Top alerts this week", "campaign",
                     "A company's complaints about one issue rose well above its usual level "
                     "(at least 1.75× the expected count and 20+ complaints).")  # fmt: skip
        if week_alerts.empty:
            st.info("No alerts yet. Alerts appear after the daily pipeline scores a complete week.")
        else:
            top = week_alerts.sort_values("score", ascending=False).head(5)
            ui.html_block("".join(alert_item(i, a) for i, (_, a) in enumerate(top.iterrows(), start=1)))
    with right, ui.card("weekly"):
        ui.card_head("Weekly complaints by product", "stacked_line_chart",
                     "Non-bureau companies. Credit bureaus are left out because their volume is ~10× larger.")  # fmt: skip
        if weekly.empty:
            st.info("Weekly volume appears after the first pipeline run.")
        else:
            other = complete_weeks(weekly[weekly["segment"] == "other"], weekly["week_start"])
            other = other.assign(product=other["product"].map(ui.short_product))
            top = other.groupby("product")["complaints"].sum().nlargest(4).index.tolist()
            other = other.assign(product=other["product"].where(other["product"].isin(top), "Other products"))
            plot = other.groupby(["week_start", "product"], as_index=False)["complaints"].sum()
            st.altair_chart(
                ui.line_chart(plot, "week_start", "complaints", "product",
                              [alt.Tooltip("week_start:T", title="Week", format="%d %b %Y"),
                               alt.Tooltip("product:N", title="Product"), ui.tip("complaints")],
                              domain=[*top, "Other products"], y_title="Complaints", height=300),
                use_container_width=True,
            )  # fmt: skip
            st.caption("The latest weeks are still filling in: the CFPB publishes most complaints 1–3 weeks late.")

    st.write("")
    share = campaigns.get("summary", {}).get("share_template_amplified")
    ui.kpi_row([
        ui.highlight(f"{volume_rule.get('recall', 0):.0%}", "of 161 past incidents would have been flagged, a "
                     f"median {ui.fmt_int(lead)} days before their peak (tested on 2022–26)."),
        ui.highlight(f"{triage_best.get('lift_top10', 0):.1f}×", "more relief cases in the triage model's top 10% "
                     "than at random (tested on 2025)."),
        ui.highlight(f"{share:.0%}" if share is not None else "—", "of past incidents were mostly near-identical "
                     "template complaints, not organic problems."),
    ])  # fmt: skip


def page_alerts() -> None:
    ui.page_header("Monitoring", "Alerts", "Every company × product × issue whose weekly complaints rose unusually fast",
                   ui.chip(f"{len(alerts):,} alerts in the last 60 days", "notifications_active"))  # fmt: skip
    not_published_notice()
    if alerts.empty:
        st.info("No alerts recorded yet.")
        return
    with ui.card("alert-table"):
        ui.card_head("Alert list", "table_rows",
                     "<b>Expected</b> = the usual weekly count, adjusted for how much of the week is published so "
                     "far. <b>Ratio</b> = complaints ÷ expected.")  # fmt: skip
        f1, f2, f3 = st.columns([2, 1, 1])
        q = f1.text_input("Search company, product or issue", key="alert_search", placeholder="e.g. Navy Federal")
        weeks = sorted(alerts["week_start"].dt.date.unique(), reverse=True)
        week = f2.selectbox("Week starting", ["All weeks", *weeks], key="alert_week")
        pattern = f3.selectbox("Pattern", ["All", "Single company", "Cross-company wave"], key="alert_pattern")
        view = search(alerts, q)
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
    if view.empty:
        return
    st.write("")
    with ui.card("alert-detail"):
        ui.card_head("Alert details", "description", "Choose an alert to see its summary and what customers describe.")
        labels = [f"{r.week_start:%d %b} · {r.company} · {r.issue}" for r in view.itertuples()]
        pick = st.selectbox("Alert", range(len(labels)), format_func=lambda i: labels[i], key="alert_pick")
        a = view.iloc[pick]
        published = a["completeness"] if pd.notna(a["completeness"]) else 1
        ui.html_block(
            alert_item(1, a, with_summary=False).replace('<div class="cr-rank">1</div>', "")
            + f'<div class="cr-badges">{ui.badge(f"week {ui.fmt_int(a["week_age"])} ago · {published:.0%} published", "neutral", "schedule")}</div>'
        )  # fmt: skip
        if isinstance(a.get("summary"), str):
            method = (
                "written by a local language model, numbers checked" if a.get("summary_method") == "llm" else "template"
            )
            ui.html_block(f"<div class='cr-summary'>{ui.safe(a['summary'])}</div>")
            st.caption(f"Summary: {method}.")
        topics = json.loads(a["typical_topics"]) if isinstance(a.get("typical_topics"), str) else []
        if topics:
            st.markdown("**What customers usually describe for this product and issue** (archived complaints)")
            st.dataframe(
                pd.DataFrame([{"Topic": t["label"], "Share": t["share"]} for t in topics]),
                hide_index=True, use_container_width=True,
                column_config={"Share": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)},
            )  # fmt: skip


def page_trends() -> None:
    ui.page_header("Monitoring", "Trends", "Weekly complaints for one company and issue",
                   ui.chip("300 largest series, last 60 days", "show_chart"))  # fmt: skip
    not_published_notice()
    if series.empty:
        st.info("Trend data appears after the first pipeline run.")
        return
    with ui.card("trend"):
        c1, c2 = st.columns(2)
        company = c1.selectbox("Company", sorted(series["company"].unique()), key="trend_company")
        sub = series[series["company"] == company]
        issue = c2.selectbox("Issue", sorted(sub["issue"].unique()), key="trend_issue")
        plot = (
            complete_weeks(sub[sub["issue"] == issue], series["week_start"])
            .groupby("week_start", as_index=False)["complaints"]
            .sum()
        )
        if not plot.empty:
            peak = plot.loc[plot["complaints"].idxmax()]
            ui.kpi_row([
                ui.kpi("Complaints in window", ui.fmt_int(plot["complaints"].sum()), "complete weeks only", "inbox"),
                ui.kpi("Latest complete week", ui.fmt_int(plot["complaints"].iloc[-1]),
                       f"week of {plot['week_start'].iloc[-1]:%d %b}", "event"),
                ui.kpi("Peak week", ui.fmt_int(peak["complaints"]), f"week of {peak['week_start']:%d %b}", "north_east"),
            ])  # fmt: skip
        st.write("")
        st.altair_chart(
            ui.line_chart(plot, "week_start", "complaints", None,
                          [alt.Tooltip("week_start:T", title="Week", format="%d %b %Y"), ui.tip("complaints")],
                          y_title="Complaints per week", area=True, height=320),
            use_container_width=True,
        )  # fmt: skip
        st.caption(
            "Recent weeks are incomplete because of the CFPB's publication delay; the alert logic adjusts for this."
        )


def page_triage() -> None:
    ui.page_header("Operations", "Escalation triage",
                   "Which complaints are likely to end with the company giving relief (money back or another fix)",
                   ui.chip("LightGBM · tested on 2025", "model_training"))  # fmt: skip
    not_published_notice()
    perf = triage_res.get("test_all_rows", {})
    if triage_best:
        ui.kpi_row([
            ui.kpi("Lift in top 10%", f"{triage_best['lift_top10']:.1f}×", "vs reviewing at random", "trending_up"),
            ui.kpi("Relief rate in top 10%", f"{triage_best['precision_top10']:.0%}", "of complaints the model ranks first",
                   "verified"),
            ui.kpi("ROC-AUC", f"{triage_best['roc_auc']:.2f}", "ranking quality (0.5 = random)", "insights"),
        ])  # fmt: skip
        st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, ui.card("scored"):
        ui.card_head("Latest scored complaints", "assignment_turned_in",
                     "<b>High</b> = top 10% of scores, <b>Medium</b> = next 20%. Public complaints are published after the "
                     "company responds, so many are already closed; inside a bank this would score at intake.")  # fmt: skip
        if triage_top.empty:
            st.info("Scores appear after the daily pipeline runs.")
        else:
            latest = triage_top[triage_top["as_of"] == triage_top["as_of"].max()]
            q = st.text_input("Search scored complaints", key="triage_search", placeholder="company, product or issue")
            latest = search(latest, q)
            table = pd.DataFrame({
                "Complaint ID": latest["complaint_id"], "Received": pd.to_datetime(latest["date_received"]).dt.date,
                "Company": latest["company"], "Product": latest["product"].map(ui.short_product), "Issue": latest["issue"],
                "Relief probability": latest["relief_probability"], "Priority": latest["priority"].str.title(),
                "Status": latest["company_response"].fillna("—"),
            })  # fmt: skip
            st.dataframe(ui.paginate(table, key="triage_page"), hide_index=True, use_container_width=True,
                         column_config={"Relief probability": st.column_config.ProgressColumn(
                             format="percent", min_value=0, max_value=1)})  # fmt: skip
    with right, ui.card("score"):
        ui.card_head("Score a complaint", "calculate", "Try the model on a new complaint.")
        with st.form("score_form", border=False):
            product = st.selectbox("Product", ["Credit card", "Checking or savings account", "Debt collection",
                                               "Mortgage", "Money transfer, virtual currency, or money service",
                                               "Student loan", "Vehicle loan or lease",
                                               "Credit reporting or other personal consumer reports"])  # fmt: skip
            issue = st.text_input("Issue", "Problem with a purchase shown on your statement")
            company = st.text_input("Company", "CAPITAL ONE FINANCIAL CORPORATION")
            c1, c2 = st.columns(2)
            state = c1.text_input("State (2 letters)", "CA")
            channel = c2.selectbox("Submitted via", ["Web", "Phone", "Referral", "Postal mail", "Email", "Fax"])
            tags = st.selectbox("Tags", ["None", "Older American", "Servicemember", "Older American, Servicemember"])
            go = st.form_submit_button("Score complaint", type="primary", use_container_width=True)
        if go:
            try:
                from complaint_radar.triage.model import priority
                from complaint_radar.triage.scoring import load_triage_model

                model = load_triage_model()
                row = pd.DataFrame([{"date_received": date.today(), "product": product, "issue": issue,
                                     "company": company, "state": state or None, "submitted_via": channel,
                                     "tags": None if tags == "None" else tags}])  # fmt: skip
                p = float(model.predict(row)[0])
                pr = priority(p, model.metadata.get("reference_score_quantiles", []))
                ui.html_block(f'<p class="cr-muted" style="margin:6px 0 4px 0">Relief probability</p>'
                              f'<div class="cr-big">{p:.0%} &nbsp;{ui.mapped_badge(pr, ui.PRIORITY_BADGE)}</div>')  # fmt: skip
                reasons = model.reasons(row)[0]
                st.markdown("Main factors (positive pushes the score up):")
                st.dataframe(
                    pd.DataFrame(reasons).rename(columns={"feature": "Factor", "value": "Value", "effect": "Effect"}),
                    hide_index=True, use_container_width=True,
                )  # fmt: skip
            except Exception as exc:  # model not packaged in this deployment
                st.warning(f"Scoring is unavailable here ({type(exc).__name__}).")
    if perf:
        st.write("")
        with ui.card("models"):
            ui.card_head("Model comparison", "leaderboard", "All models tested on 2025 complaints they never saw.")
            names = {
                "baseline_product_issue_rate": "Baseline: historical rate for product × issue",
                "logistic_regression_fields": "Logistic regression",
                "lightgbm_fields_calibrated": "LightGBM (in use)",
            }
            st.dataframe(pd.DataFrame([
                {"Model": names.get(k, k), "ROC-AUC": round(m["roc_auc"], 3), "PR-AUC": round(m["pr_auc"], 3),
                 "Relief rate in top 10%": f"{m['precision_top10']:.0%}", "Lift vs random": f"{m['lift_top10']:.1f}×"}
                for k, m in perf.items()
            ]), hide_index=True, use_container_width=True)  # fmt: skip


def page_research() -> None:
    ui.page_header("Insights", "Research", "How the radar was validated on past data, and what we learned",
                   ui.chip("Strict time splits · baselines", "science"))  # fmt: skip
    section = st.radio("Topic", ["Early-warning backtest", "Campaigns", "Topics", "Enforcement study"],
                       horizontal=True, key="research_section", label_visibility="collapsed")  # fmt: skip
    if section == "Early-warning backtest":
        with ui.card("backtest"):
            ui.card_head("Would the radar have flagged past incidents?", "history",
                         "Test period 2022 – May 2026, non-bureau companies. The simple volume rule was not beaten.")  # fmt: skip
            dets = backtest.get("segments", {}).get("other", {}).get("detectors", {})
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
            named = pd.DataFrame(backtest.get("named_incidents", []))
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
        with ui.card("campaigns"):
            ui.card_head("Template and campaign-driven complaint waves", "content_copy")
            inc = pd.DataFrame(campaigns.get("incidents", []))
            if not inc.empty:
                s = campaigns["summary"]
                st.markdown(f"**{s['template_amplified']} of {s['incidents_scored']} incidents** "
                            f"({s['share_template_amplified']:.0%}) were mostly near-identical complaint texts.")  # fmt: skip
                inc["year"] = inc["start_month"].str[:4]
                inc["Type"] = inc["label"].map({"organic": "Organic", "template_amplified": "Template-amplified"})
                by_year = inc.groupby(["year", "Type"], as_index=False).size()
                chart = alt.Chart(by_year).mark_bar(cornerRadiusEnd=4, stroke="#ffffff", strokeWidth=2).encode(
                    x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("size:Q", title="Incidents", stack=True),
                    color=alt.Color("Type:N", title=None, scale=alt.Scale(domain=["Organic", "Template-amplified"],
                                                                           range=ui.SERIES[:2])),
                    tooltip=[alt.Tooltip("year:O", title="Year"), "Type:N", alt.Tooltip("size:Q", title="Incidents")])  # fmt: skip
                st.altair_chart(ui._style(chart, 260), use_container_width=True)
                top = inc[inc["label"] == "template_amplified"].sort_values("complaints", ascending=False)
                st.dataframe(top[["start_month", "company", "issue", "complaints", "near_dup_share"]].rename(columns={
                    "start_month": "Start", "company": "Company", "issue": "Issue", "complaints": "Complaints",
                    "near_dup_share": "Near-duplicate share"}), hide_index=True, use_container_width=True,
                    column_config={"Near-duplicate share": st.column_config.ProgressColumn(
                        format="percent", min_value=0, max_value=1)})  # fmt: skip
    elif section == "Topics":
        with ui.card("topics"):
            ui.card_head("What complaints are about (archived narratives)", "category")
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
                                                 [alt.Tooltip("label:N", title="Topic"), ui.tip("complaints_in_corpus")],
                                                 height=440, val_title="Complaints (2019–2025)"),
                                    use_container_width=True)  # fmt: skip
    else:
        with ui.card("enforcement"):
            ui.card_head("Do complaints warn of CFPB enforcement in advance?", "gavel",
                         "Company-months 2020–2024; features from the previous 12 months only; months right after "
                         "an action are excluded.")  # fmt: skip
            enf = data.result("enforcement")
            if not enf:
                st.info("The enforcement study results are not published yet.")
            else:
                names = {"baseline_volume_only": "Complaint volume only (baseline)",
                         "logistic_all_features": "Logistic regression, all patterns",
                         "lightgbm_all_features": "LightGBM, all patterns"}  # fmt: skip
                st.dataframe(pd.DataFrame([
                    {"Model": names.get(k, k), "ROC-AUC": round(m["roc_auc"], 3),
                     "PR-AUC": round(m["pr_auc"], 3), "Lift in top 1%": f"{m['lift_top1pct']:.1f}×"}
                    for k, m in enf.get("test", {}).items()
                ]), hide_index=True, use_container_width=True)  # fmt: skip
                g = enf.get("gain_over_volume_pr_auc", {})
                if g:
                    lo, hi = g["ci95"]
                    verdict = "a real gain" if lo > 0 else "no reliable gain"
                    st.markdown(f"Gain of complaint patterns over volume alone (PR-AUC): **{g['mean_diff']:+.3f}** "
                                f"(95% interval {lo:+.3f} to {hi:+.3f}) — {verdict}. Complaint volume tells you who "
                                "gets sanctioned; complaint patterns add nothing on top.")  # fmt: skip


def page_health() -> None:
    ui.page_header("Operations", "Data health", "Pipeline runs, model drift and how complete recent weeks are",
                   ui.chip(f"Refreshed {updated or '—'} UTC", "update"))  # fmt: skip
    not_published_notice()
    left, right = st.columns(2, gap="medium")
    with left, ui.card("runs"):
        ui.card_head("Pipeline runs", "sync", "Every daily run is logged, including runs with no new data.")
        if runs.empty:
            st.info("No runs recorded yet.")
        else:
            st.dataframe(pd.DataFrame({
                "Date": runs["as_of"].dt.date, "Status": runs["status"].str.replace("_", " ").str.capitalize(),
                "Step": runs["step"], "Rows loaded": runs["rows_loaded"], "Message": runs["message"].fillna("—"),
            }).head(30), hide_index=True, use_container_width=True)  # fmt: skip
    with right, ui.card("drift"):
        ui.card_head("Model drift (Population Stability Index)", "monitor_heart",
                     "Below 0.10 = stable, 0.10–0.25 = moderate shift, above 0.25 = significant shift.")  # fmt: skip
        valid = drift.dropna(subset=["value"]) if not drift.empty else drift
        if valid.empty:
            st.info("Drift appears once enough new complaints are scored (at least 200 a day).")
        else:
            valid = valid.assign(metric=valid["metric"].map({"product_mix_psi": "Product mix",
                                                             "score_psi": "Score distribution"}))  # fmt: skip
            st.altair_chart(ui.line_chart(valid, "as_of", "value", "metric",
                                          [alt.Tooltip("as_of:T", title="Date", format="%d %b %Y"), "metric:N",
                                           alt.Tooltip("value:Q", title="PSI", format=".3f")],
                                          domain=["Product mix", "Score distribution"], y_title="PSI"),
                            use_container_width=True)  # fmt: skip
    st.write("")
    with ui.card("completeness"):
        ui.card_head("How complete recent weeks are", "hourglass_bottom",
                     "Share of a typical week's complaints already published, by how old the week is.")  # fmt: skip
        if vintages.empty:
            st.info("Completeness snapshots are recorded daily from the first run onwards.")
        else:
            v = vintages[vintages["as_of"] == vintages["as_of"].max()]
            mature = v[v["age"] >= 4].groupby("segment")["n_published"].median()
            v = v[v["age"].between(1, 4)].assign(share=lambda d: d["n_published"] / d["segment"].map(mature))
            v["Segment"] = v["segment"].map({"other": "Other companies", "bureau": "Credit bureaus"})
            v["Week"] = v["age"].map({1: "Last week", 2: "2 weeks ago", 3: "3 weeks ago", 4: "4 weeks ago"})
            chart = alt.Chart(v).mark_bar(cornerRadiusEnd=4, stroke="#ffffff", strokeWidth=2).encode(
                x=alt.X("Week:N", sort=["Last week", "2 weeks ago", "3 weeks ago", "4 weeks ago"], title=None,
                        axis=alt.Axis(labelAngle=0)),
                xOffset="Segment:N", y=alt.Y("share:Q", title="Share published", axis=alt.Axis(format="%")),
                color=alt.Color("Segment:N", title=None, scale=alt.Scale(domain=["Other companies", "Credit bureaus"],
                                                                          range=ui.SERIES[:2])),
                tooltip=["Week:N", "Segment:N", alt.Tooltip("share:Q", format=".0%", title="Published")])  # fmt: skip
            st.altair_chart(ui._style(chart, 240), use_container_width=True)


def page_about() -> None:
    ui.page_header("Help", "About Complaint Radar", "What this platform does and the words it uses")
    left, right = st.columns([3, 2], gap="medium")
    with left, ui.card("about"):
        ui.card_head("What this is", "info")
        st.markdown(
            """
Complaint Radar watches the US **Consumer Financial Protection Bureau (CFPB)** complaint database (complaints about
banks, credit cards, lenders, debt collectors and payment apps) and flags problems that are growing unusually fast.

- Every day a pipeline downloads the full public complaint file, checks it against a *data contract* (rules the
  data must follow), and loads new or changed complaints into a Google BigQuery warehouse.
- It compares each company's weekly complaints about each issue with its usual level and raises an **alert** when
  they jump. Because the CFPB publishes complaints 1–3 weeks late, recent weeks are adjusted for how complete they are.
- Alerts are labelled as a **single-company** problem or a **cross-company wave** (the same issue rising at many
  companies, which points to a shared cause), and get a short plain-English summary.
- A **triage model** estimates which complaints are likely to end with the customer getting relief.

**Limits:** complaints are not verified by the CFPB and are not a random sample of customers. Since August 2026 the
CFPB no longer publishes complaint text, so topics and examples come from complaints published before then.
            """
        )
    with right, ui.card("glossary"):
        ui.card_head("Words used here", "menu_book")
        st.markdown(
            """
- **Expected**: the usual weekly number of complaints for that company and issue, adjusted for publication delay.
- **Ratio**: complaints this week ÷ expected.
- **Cross-company wave**: the same product and issue alerting at 5 or more companies in one week.
- **Template-amplified**: most complaints in a wave are near-copies of the same text.
- **Relief**: the company gave the customer money back or another fix.
- **PSI**: Population Stability Index, how much incoming data has shifted from what a model learned on.
            """
        )
        st.caption("Source code: github.com/larissamartis/complaint-radar")


PAGES = {
    "overview": ("Overview", "space_dashboard", page_overview),
    "alerts": ("Alerts", "notifications_active", page_alerts),
    "trends": ("Trends", "show_chart", page_trends),
    "triage": ("Triage", "assignment_turned_in", page_triage),
    "research": ("Research", "science", page_research),
    "health": ("Data health", "monitor_heart", page_health),
    "about": ("About", "info", page_about),
}


def go_to(slug: str) -> None:
    st.session_state["page"] = slug
    st.session_state["scroll_top"] = True
    st.query_params["page"] = slug


if "page" not in st.session_state:
    requested = st.query_params.get("page")
    st.session_state["page"] = requested if requested in PAGES else "overview"

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
for slug, (label, icon_name, _) in PAGES.items():
    st.sidebar.button(
        label, key=f"nav_{slug}", icon=f":material/{icon_name}:", use_container_width=True,
        type="primary" if st.session_state["page"] == slug else "tertiary", on_click=go_to, args=(slug,),
    )  # fmt: skip
ui.sidebar_status(last_run["status"] if last_run is not None else None, updated)
if st.sidebar.button("Refresh data", icon=":material/refresh:", type="tertiary", key="refresh"):
    st.cache_data.clear()
    st.rerun()

PAGES[st.session_state["page"]][2]()

if st.session_state.pop("scroll_top", False):
    # A new page opens at the top, not at the previous page's scroll position.
    components.html(
        "<script>const d = window.parent.document;"
        'd.querySelectorAll(\'[data-testid="stMain"], [data-testid="stAppViewContainer"], section.main\')'
        ".forEach(e => e.scrollTo(0, 0)); window.parent.scrollTo(0, 0);</script>",
        height=0,
    )

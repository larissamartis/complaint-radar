"""Visual building blocks: one brand colour, icon tiles, white panels, status badges, consistent charts."""

import html

import altair as alt
import pandas as pd
import streamlit as st

BRAND = "#2a78d6"
# Categorical slots in fixed order (validated palette); text never uses these colours.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b", "neutral": "#898781"}
INK, INK_2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"

CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0" rel="stylesheet">
<style>
  .block-container {{ padding-top: 3.4rem; max-width: 1280px; }}
  .cr-header {{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
               margin-bottom: 0.8rem; }}
  .cr-title {{ font-size: 1.35rem; font-weight: 650; color: {INK}; margin:0; }}
  .cr-sub {{ color: {INK_2}; font-size: 0.9rem; margin: 2px 0 0 0; }}
  .cr-card {{ background:#fff; border:1px solid rgba(11,11,11,0.10); border-radius:10px; padding:14px 16px;
              display:flex; gap:12px; align-items:flex-start; height:100%; }}
  .cr-tile {{ width:40px; height:40px; border-radius:9px; display:flex; align-items:center; justify-content:center;
              flex:0 0 40px; }}
  .cr-tile .material-symbols-rounded {{ font-size:22px; }}
  .cr-label {{ color:{INK_2}; font-size:0.8rem; margin:0; line-height:1.25; }}
  .cr-value {{ color:{INK}; font-size:1.45rem; font-weight:650; margin:2px 0 0 0; line-height:1.2;
               font-variant-numeric: tabular-nums; }}
  .cr-note {{ color:{MUTED}; font-size:0.76rem; margin:2px 0 0 0; line-height:1.25; }}
  .cr-panel-head {{ display:flex; align-items:center; gap:8px; margin: 0.2rem 0 0.4rem 0; }}
  .cr-panel-head .material-symbols-rounded {{ color:{BRAND}; font-size:20px; }}
  .cr-panel-head h4 {{ margin:0; font-size:1.0rem; font-weight:620; color:{INK}; }}
  .cr-badge {{ display:inline-flex; align-items:center; gap:4px; padding:2px 8px; border-radius:999px;
               font-size:0.76rem; font-weight:560; white-space:nowrap; border:1px solid; }}
  .cr-badge .material-symbols-rounded {{ font-size:14px; }}
  .cr-summary {{ background:#f9f9f7; border-left:3px solid {BRAND}; padding:10px 12px; border-radius:6px;
                 color:{INK}; font-size:0.92rem; }}
  .cr-muted {{ color:{MUTED}; font-size:0.8rem; }}
  div[data-testid="stTabs"] button p {{ font-size: 0.92rem; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def icon(name: str) -> str:
    return f'<span class="material-symbols-rounded">{html.escape(name)}</span>'


def kpi(label: str, value: str, note: str, icon_name: str, color: str) -> str:
    return (
        f'<div class="cr-card"><div class="cr-tile" style="background:{color}1f;color:{color}">{icon(icon_name)}</div>'
        f'<div><p class="cr-label">{html.escape(label)}</p><p class="cr-value">{html.escape(value)}</p>'
        f'<p class="cr-note">{html.escape(note)}</p></div></div>'
    )


def kpi_row(cards: list[str]) -> None:
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards, strict=True):
        col.markdown(card, unsafe_allow_html=True)


def panel_head(title: str, icon_name: str) -> None:
    st.markdown(
        f'<div class="cr-panel-head">{icon(icon_name)}<h4>{html.escape(title)}</h4></div>', unsafe_allow_html=True
    )


def badge(text: str, kind: str, icon_name: str | None = None) -> str:
    c = STATUS.get(kind, BRAND)
    ic = icon(icon_name) if icon_name else ""
    return (
        f'<span class="cr-badge" style="color:{INK};border-color:{c};background:{c}1a">{ic}{html.escape(text)}</span>'
    )


RUN_BADGE = {
    "success": ("Success", "good", "check_circle"),
    "no_new_data": ("No new data", "neutral", "schedule"),
    "failed": ("Failed", "critical", "error"),
}
PATTERN_BADGE = {
    "cross_company_wave": ("Cross-company wave", "serious", "hub"),
    "single_company": ("Single company", "neutral", "business"),
}
PRIORITY_BADGE = {
    "high": ("High", "critical", "priority_high"),
    "medium": ("Medium", "warning", "remove"),
    "low": ("Low", "good", "south"),
}


def mapped_badge(value, mapping: dict) -> str:
    if not isinstance(value, str) or not value:
        return ""
    text, kind, ic = mapping.get(value, (value.replace("_", " ").capitalize(), "neutral", None))
    return badge(text, kind, ic)


def _style(chart: alt.Chart, height: int) -> alt.Chart:
    return (
        chart.properties(height=height)
        .configure_view(strokeWidth=0)
        .configure_axis(
            gridColor=GRID, domainColor=AXIS, tickColor=AXIS, labelColor=MUTED, titleColor=INK_2,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
        )
        .configure_legend(labelColor=INK_2, titleColor=INK_2, orient="bottom", columns=2, labelLimit=240, symbolType="stroke")
    )  # fmt: skip


def line_chart(df: pd.DataFrame, x: str, y: str, color: str | None, tooltip: list, height: int = 280,
               y_title: str = "", domain: list | None = None) -> alt.Chart:  # fmt: skip
    enc = {
        "x": alt.X(f"{x}:T", title=None),
        "y": alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(zero=True)),
        "tooltip": tooltip,
    }
    if color:
        enc["color"] = alt.Color(
            f"{color}:N", title=None, scale=alt.Scale(domain=domain, range=SERIES[: len(domain or SERIES)])
        )
    base = alt.Chart(df).encode(**enc)
    lines = base.mark_line(strokeWidth=2) if color else base.mark_line(strokeWidth=2, color=BRAND)
    points = base.mark_circle(size=120, opacity=0)  # invisible, larger hover targets for the tooltip
    return _style(alt.layer(lines, points), height)


def tip(field: str) -> alt.Tooltip:
    return alt.Tooltip(f"{field}:Q", format=",")


def bar_chart(df: pd.DataFrame, cat: str, val: str, tooltip: list, height: int = 300, val_title: str = "",
              color: str = BRAND, sort: str = "-x") -> alt.Chart:  # fmt: skip
    chart = (
        alt.Chart(df)
        .mark_bar(color=color, cornerRadiusEnd=4, height={"band": 0.7})
        .encode(
            y=alt.Y(f"{cat}:N", sort=sort, title=None, axis=alt.Axis(labelLimit=320)),
            x=alt.X(f"{val}:Q", title=val_title),
            tooltip=tooltip,
        )
    )
    return _style(chart, height)


SHORT_PRODUCT = {
    "Credit reporting or other personal consumer reports": "Credit reporting",
    "Credit reporting, credit repair services, or other personal consumer reports": "Credit reporting",
    "Checking or savings account": "Checking or savings",
    "Money transfer, virtual currency, or money service": "Money transfer / payment apps",
    "Payday loan, title loan, personal loan, or advance loan": "Payday / personal loan",
    "Payday loan, title loan, or personal loan": "Payday / personal loan",
    "Vehicle loan or lease": "Vehicle loan",
    "Credit card or prepaid card": "Credit or prepaid card",
    "Debt or credit management": "Debt management",
}


def short_product(name) -> str:
    return SHORT_PRODUCT.get(name, name) if isinstance(name, str) else "—"


def fmt_int(x) -> str:
    try:
        return f"{int(x):,}"
    except (TypeError, ValueError):
        return "—"


def paginate(df: pd.DataFrame, key: str, page_size: int = 25) -> pd.DataFrame:
    """Simple pager below long tables."""
    pages = max(1, -(-len(df) // page_size))
    c1, c2 = st.columns([1, 3])
    page = c1.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=key)
    c2.markdown(f'<p class="cr-muted" style="margin-top:2.1rem">{len(df):,} rows · page {page} of {pages}</p>',
                unsafe_allow_html=True)  # fmt: skip
    return df.iloc[(page - 1) * page_size : page * page_size]

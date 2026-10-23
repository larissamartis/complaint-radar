"""Visual building blocks: one brand colour (indigo), a dark sidebar, white cards, status badges, consistent charts."""

import html

import altair as alt
import pandas as pd
import streamlit as st

BRAND = "#4f46e5"
BRAND_DARK = "#3730a3"
BRAND_SOFT = "#eef2ff"
SIDEBAR = "#1e1b4b"
# Categorical slots in fixed order, led by the brand colour (validated: adjacent CVD ΔE >= 9.1 on white).
SERIES = ["#4f46e5", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b", "neutral": "#98a2b3"}
INK, INK_2, MUTED, GRID, AXIS, LINE = "#101828", "#475467", "#667085", "#eaecf0", "#d0d5dd", "#e4e7ec"
FONT = "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"

CSS = f"""
<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,500,0,0" rel="stylesheet">
<style>
  :root {{ --brand:{BRAND}; --brand-dark:{BRAND_DARK}; --brand-soft:{BRAND_SOFT}; --ink:{INK}; --ink-2:{INK_2};
           --muted:{MUTED}; --line:{LINE}; }}
  html, body, [class*="css"] {{ font-family:{FONT}; }}
  header[data-testid="stHeader"] {{ background: transparent; }}
  .block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1320px; }}

  /* ---- sidebar ---- */
  section[data-testid="stSidebar"] {{ background:{SIDEBAR}; }}
  section[data-testid="stSidebar"] > div {{ padding-top: 0.6rem; }}
  section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] span,
  section[data-testid="stSidebar"] label {{ color:#c7d2fe; }}
  .cr-brand {{ display:flex; align-items:center; gap:10px; padding:4px 4px 18px 4px; }}
  .cr-brand-tile {{ width:38px; height:38px; border-radius:10px; background:{BRAND}; display:flex;
                    align-items:center; justify-content:center; }}
  .cr-brand-tile .material-symbols-rounded {{ color:#fff !important; font-size:22px; }}
  .cr-brand-name {{ color:#fff !important; font-weight:700; font-size:1.02rem; margin:0; line-height:1.15; }}
  .cr-brand-sub {{ color:#a5b4fc !important; font-size:0.74rem; margin:0; }}
  .cr-nav-label {{ color:#818cf8 !important; font-size:0.68rem; font-weight:650; letter-spacing:0.08em;
                   margin:6px 6px 4px 6px; }}
  section[data-testid="stSidebar"] .stButton {{ margin-bottom:-10px; }}
  section[data-testid="stSidebar"] .stButton button {{ justify-content:flex-start; border:none; border-radius:9px;
      padding:8px 12px; min-height:40px; width:100%; box-shadow:none; }}
  section[data-testid="stSidebar"] .stButton button > div {{ justify-content:flex-start; width:100%; gap:10px; }}
  section[data-testid="stSidebar"] .stButton button p {{ font-size:0.9rem; font-weight:520; text-align:left; }}
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] {{ background:transparent; }}
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] p,
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"] span {{ color:#c7d2fe !important; }}
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-tertiary"]:hover {{
      background:rgba(255,255,255,0.07); }}
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {{ background:{BRAND}; }}
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] p,
  section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] span {{ color:#fff !important; }}
  .cr-side-card {{ background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.10); border-radius:12px;
                   padding:12px; margin-top:22px; }}
  .cr-side-card p {{ margin:0; font-size:0.78rem; line-height:1.45; }}
  .cr-side-card .cr-side-strong {{ color:#fff !important; font-weight:600; font-size:0.84rem; }}
  .cr-dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; }}

  /* ---- page ---- */
  .cr-page-head {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap;
                   margin-bottom:1.1rem; }}
  .cr-crumb {{ color:{BRAND}; font-size:0.78rem; font-weight:600; margin:0 0 2px 0; letter-spacing:0.02em; }}
  .cr-title {{ font-size:1.6rem; font-weight:700; color:{INK}; margin:0; line-height:1.2; }}
  .cr-sub {{ color:{INK_2}; font-size:0.92rem; margin:4px 0 0 0; }}
  .cr-chip {{ display:inline-flex; align-items:center; gap:6px; background:#fff; border:1px solid {LINE};
              border-radius:999px; padding:5px 12px; font-size:0.8rem; color:{INK_2}; white-space:nowrap; }}
  .cr-chip .material-symbols-rounded {{ font-size:16px; color:{BRAND}; }}

  div[class*="st-key-card"] {{ background:#fff; border:1px solid {LINE}; border-radius:14px; padding:18px 20px 14px 20px;
      box-shadow:0 1px 2px rgba(16,24,40,0.05); }}
  .cr-card-head {{ display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:2px; }}
  .cr-card-title {{ display:flex; align-items:center; gap:8px; }}
  .cr-card-title .material-symbols-rounded {{ color:{BRAND}; font-size:20px; background:{BRAND_SOFT};
      border-radius:8px; padding:5px; }}
  .cr-card-title h4 {{ margin:0; font-size:1.0rem; font-weight:650; color:{INK}; }}
  .cr-card-sub {{ color:{MUTED}; font-size:0.82rem; margin:2px 0 10px 0; line-height:1.4; }}

  .cr-kpi {{ background:#fff; border:1px solid {LINE}; border-radius:14px; padding:16px 18px; height:100%;
             box-shadow:0 1px 2px rgba(16,24,40,0.05); }}
  .cr-kpi-top {{ display:flex; align-items:center; justify-content:space-between; }}
  .cr-kpi-label {{ color:{INK_2}; font-size:0.82rem; font-weight:550; margin:0; }}
  .cr-tile {{ width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center;
              background:{BRAND_SOFT}; }}
  .cr-tile .material-symbols-rounded {{ font-size:20px; color:{BRAND}; }}
  .cr-kpi-value {{ color:{INK}; font-size:1.75rem; font-weight:700; margin:8px 0 0 0; line-height:1.1; }}
  .cr-kpi-note {{ color:{MUTED}; font-size:0.78rem; margin:4px 0 0 0; line-height:1.3; }}

  .cr-hero {{ background:{BRAND}; border-radius:16px; padding:20px 24px; color:#fff; display:flex;
              align-items:center; justify-content:space-between; gap:18px; flex-wrap:wrap; margin-bottom:1rem; }}
  .cr-hero h3 {{ color:#fff; margin:0; font-size:1.2rem; font-weight:700; }}
  .cr-hero p {{ color:#e0e7ff; margin:4px 0 0 0; font-size:0.9rem; }}
  .cr-hero-stats {{ display:flex; gap:28px; }}
  .cr-hero-stat b {{ display:block; font-size:1.5rem; font-weight:700; color:#fff; line-height:1.1; }}
  .cr-hero-stat span {{ font-size:0.76rem; color:#c7d2fe; }}

  .cr-alert {{ display:flex; gap:12px; padding:12px 0; border-top:1px solid {GRID}; }}
  .cr-alert:first-of-type {{ border-top:none; }}
  .cr-rank {{ flex:0 0 28px; height:28px; border-radius:8px; background:{BRAND_SOFT}; color:{BRAND_DARK};
              font-weight:700; font-size:0.82rem; display:flex; align-items:center; justify-content:center; }}
  .cr-alert-body {{ flex:1; min-width:0; }}
  .cr-alert-title {{ color:{INK}; font-weight:650; font-size:0.93rem; margin:0; }}
  .cr-alert-issue {{ color:{INK_2}; font-size:0.86rem; margin:1px 0 6px 0; }}
  .cr-badges {{ display:flex; gap:6px; flex-wrap:wrap; }}
  .cr-summary {{ background:#f9fafb; border-left:3px solid {BRAND}; padding:9px 12px; border-radius:8px;
                 color:{INK_2}; font-size:0.86rem; margin-top:8px; line-height:1.45; }}

  .cr-badge {{ display:inline-flex; align-items:center; gap:4px; padding:2px 9px; border-radius:999px;
               font-size:0.75rem; font-weight:560; white-space:nowrap; color:{INK}; }}
  .cr-badge .material-symbols-rounded {{ font-size:14px; }}
  .cr-badge-brand {{ background:{BRAND_SOFT}; color:{BRAND_DARK}; }}

  .cr-highlight {{ background:#fff; border:1px solid {LINE}; border-radius:14px; padding:16px 18px; height:100%; }}
  .cr-highlight b {{ color:{BRAND}; font-size:1.5rem; font-weight:700; display:block; line-height:1.1; }}
  .cr-highlight p {{ margin:6px 0 0 0; color:{INK_2}; font-size:0.84rem; line-height:1.4; }}
  .cr-muted {{ color:{MUTED}; font-size:0.8rem; }}
  .cr-big {{ color:{INK}; font-size:2.2rem; font-weight:700; line-height:1; margin:0; }}
  div[data-testid="stRadio"] > div {{ gap: 0.4rem; }}
</style>
"""


def safe(text) -> str:
    """Escape text for st.markdown(unsafe_allow_html=True): no HTML from data (company names, LLM summaries),
    and '$' escaped so Streamlit does not render it as a maths formula."""
    return html.escape("" if text is None or (isinstance(text, float) and text != text) else str(text)).replace(
        "$", "\\$"
    )


def inject_css() -> None:
    # A blank line would end the HTML block in Streamlit's markdown and print the rest of the CSS as text.
    st.markdown("\n".join(line for line in CSS.splitlines() if line.strip()), unsafe_allow_html=True)


def icon(name: str) -> str:
    return f'<span class="material-symbols-rounded">{html.escape(name)}</span>'


def html_block(markup: str, where=st) -> None:
    where.markdown(markup, unsafe_allow_html=True)


# ---------------------------------------------------------------- sidebar
def sidebar_brand() -> None:
    html_block(
        f'<div class="cr-brand"><div class="cr-brand-tile">{icon("radar")}</div><div>'
        f'<p class="cr-brand-name">Complaint Radar</p><p class="cr-brand-sub">Complaint risk monitoring</p></div></div>'
        '<p class="cr-nav-label">MENU</p>',
        st.sidebar,
    )


def sidebar_status(status: str | None, updated: str) -> None:
    text, kind, _ = RUN_BADGE.get(
        status, (str(status or "No runs yet").replace("_", " ").capitalize(), "neutral", None)
    )
    html_block(
        f'<div class="cr-side-card"><p class="cr-side-strong"><span class="cr-dot" style="background:{STATUS[kind]}">'
        f"</span>Pipeline: {html.escape(text)}</p><p>Data refreshed {html.escape(updated or '—')} UTC</p>"
        "<p>Runs daily at 11:30 UTC on public CFPB data</p></div>",
        st.sidebar,
    )


# ---------------------------------------------------------------- page structure
def page_header(crumb: str, title: str, sub: str, right: str = "") -> None:
    html_block(
        f'<div class="cr-page-head"><div><p class="cr-crumb">{html.escape(crumb)}</p>'
        f'<p class="cr-title">{html.escape(title)}</p><p class="cr-sub">{html.escape(sub)}</p></div>'
        f"<div>{right}</div></div>"
    )


def chip(text: str, icon_name: str) -> str:
    return f'<span class="cr-chip">{icon(icon_name)}{html.escape(text)}</span>'


def card(key: str):
    """A white card: any Streamlit elements placed inside `with ui.card(...)` render on it."""
    return st.container(key=f"card-{key}")


def card_head(title: str, icon_name: str, sub: str = "") -> None:
    sub_html = f'<p class="cr-card-sub">{sub}</p>' if sub else '<div style="height:8px"></div>'
    html_block(
        f'<div class="cr-card-head"><div class="cr-card-title">{icon(icon_name)}<h4>{html.escape(title)}</h4></div>'
        f"</div>{sub_html}"
    )


def kpi(label: str, value: str, note: str, icon_name: str) -> str:
    return (
        f'<div class="cr-kpi"><div class="cr-kpi-top"><p class="cr-kpi-label">{html.escape(label)}</p>'
        f'<div class="cr-tile">{icon(icon_name)}</div></div>'
        f'<p class="cr-kpi-value">{html.escape(value)}</p><p class="cr-kpi-note">{html.escape(note)}</p></div>'
    )


def kpi_row(cards: list[str]) -> None:
    cols = st.columns(len(cards))
    for col, c in zip(cols, cards, strict=True):
        col.markdown(c, unsafe_allow_html=True)


def highlight(value: str, text: str) -> str:
    return f'<div class="cr-highlight"><b>{html.escape(value)}</b><p>{html.escape(text)}</p></div>'


# ---------------------------------------------------------------- badges
def badge(text: str, kind: str, icon_name: str | None = None) -> str:
    if kind == "brand":
        return f'<span class="cr-badge cr-badge-brand">{icon(icon_name) if icon_name else ""}{html.escape(text)}</span>'
    c = STATUS.get(kind, BRAND)
    ic = icon(icon_name) if icon_name else ""
    return f'<span class="cr-badge" style="background:{c}1f;box-shadow:inset 0 0 0 1px {c}66">{ic}{html.escape(text)}</span>'


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


# ---------------------------------------------------------------- charts
def _style(chart: alt.Chart, height: int) -> alt.Chart:
    return (
        chart.properties(height=height, background="transparent")
        .configure(font="Inter")
        .configure_view(strokeWidth=0)
        .configure_axis(
            gridColor=GRID, domainColor=AXIS, tickColor=AXIS, labelColor=MUTED, titleColor=INK_2,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal", labelPadding=6,
        )
        .configure_axisX(grid=False)
        .configure_legend(labelColor=INK_2, titleColor=INK_2, orient="bottom", columns=3, labelLimit=240,
                          symbolType="circle", symbolSize=80, labelFontSize=11)
    )  # fmt: skip


def line_chart(df: pd.DataFrame, x: str, y: str, color: str | None, tooltip: list, height: int = 280,
               y_title: str = "", domain: list | None = None, area: bool = False) -> alt.Chart:  # fmt: skip
    enc = {
        "x": alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%d %b", tickCount=6)),
        "y": alt.Y(f"{y}:Q", title=y_title, scale=alt.Scale(zero=True)),
        "tooltip": tooltip,
    }
    if color:
        enc["color"] = alt.Color(
            f"{color}:N", title=None, scale=alt.Scale(domain=domain, range=SERIES[: len(domain or SERIES)])
        )
    base = alt.Chart(df).encode(**enc)
    layers = []
    if area and not color:
        layers.append(base.mark_area(color=BRAND, opacity=0.10))  # a light wash under the line
    layers.append(base.mark_line(strokeWidth=2) if color else base.mark_line(strokeWidth=2.5, color=BRAND))
    layers.append(base.mark_circle(size=140, opacity=0))  # invisible, larger hover targets for the tooltip
    return _style(alt.layer(*layers), height)


def tip(field: str) -> alt.Tooltip:
    return alt.Tooltip(f"{field}:Q", format=",")


def bar_chart(df: pd.DataFrame, cat: str, val: str, tooltip: list, height: int = 300, val_title: str = "",
              color: str = BRAND, sort: str = "-x") -> alt.Chart:  # fmt: skip
    chart = (
        alt.Chart(df)
        .mark_bar(color=color, cornerRadiusEnd=4, height={"band": 0.68})
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

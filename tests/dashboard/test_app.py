"""Headless run of the Streamlit dashboard on fixture data (no network, no browser)."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).parents[2]


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("CR_SERVING_DIR", str(ROOT / "tests" / "fixtures" / "serving"))
    monkeypatch.setenv("CR_RESULTS_DIR", str(ROOT / "docs" / "results"))
    monkeypatch.setenv("CR_OFFLINE", "1")
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=120)
    at.run()
    return at


def test_dashboard_renders_without_errors(app):
    assert not app.exception, app.exception
    assert len(app.tabs) == 7
    text = " ".join(m.value for m in app.markdown)
    assert "Complaint Radar" in text and "AMERICAN HONDA FINANCE CORP" in text


def test_alert_search_filters_rows(app):
    app.text_input(key="alert_search").input("MOHELA").run()
    assert not app.exception
    table = app.dataframe[0].value
    assert list(table["Company"]) == ["MOHELA"]


def test_research_sections_render(app):
    for section in ["Early-warning backtest", "Campaigns", "Topics", "Enforcement study"]:
        app.radio(key="research_section").set_value(section).run()
        assert not app.exception, (section, app.exception)


def test_score_form_returns_probability(app):
    next(b for b in app.button if b.label == "Score complaint").click().run()
    assert not app.exception
    text = " ".join(m.value for m in app.markdown)
    assert "Relief probability" in text or any("unavailable" in w.value for w in app.warning)


def test_dashboard_renders_with_no_live_data(monkeypatch, tmp_path):
    """Before the first serving export exists, every tab must still render (empty states, no errors)."""
    import streamlit as st

    st.cache_data.clear()  # the data cache is shared by every app run in this test process
    monkeypatch.setenv("CR_SERVING_DIR", str(tmp_path))  # empty folder
    monkeypatch.setenv("CR_RESULTS_DIR", str(ROOT / "docs" / "results"))
    monkeypatch.setenv("CR_OFFLINE", "1")
    at = AppTest.from_file(str(ROOT / "dashboard" / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    assert any("not been published yet" in i.value for i in at.info)
    for section in ["Early-warning backtest", "Campaigns", "Topics", "Enforcement study"]:
        at.radio(key="research_section").set_value(section).run()
        assert not at.exception, (section, at.exception)

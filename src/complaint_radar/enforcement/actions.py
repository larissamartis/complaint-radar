"""Scrape the CFPB's public list of enforcement actions (company, date filed, link, description)."""

import html
import logging
import re
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

LIST_URL = "https://www.consumerfinance.gov/enforcement/actions/"
BASE = "https://www.consumerfinance.gov"

_ARTICLE = re.compile(r'<article class="o-post-preview".*?</article>', re.S)
_DATE = re.compile(r'<time datetime="(\d{4}-\d{2}-\d{2})')
_TITLE = re.compile(r'<h3 class="o-post-preview__title">\s*<a href="([^"]+)">(.*?)</a>', re.S)
_DESC = re.compile(r'<div class="o-post-preview__description">(.*?)</div>', re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def parse_list_page(page_html: str) -> list[dict]:
    rows = []
    for block in _ARTICLE.findall(page_html):
        date, title = _DATE.search(block), _TITLE.search(block)
        if not (date and title):
            continue
        desc = _DESC.search(block)
        rows.append(
            {
                "company": _text(title.group(2)),
                "date_filed": date.group(1),
                "url": BASE + title.group(1),
                "description": _text(desc.group(1)) if desc else "",
            }
        )
    return rows


def scrape_actions(session=None, max_pages: int = 60, pause: float = 1.0) -> pd.DataFrame:
    """Walk the paginated list until a page adds no new actions (the site repeats its last page)."""
    session = session or requests.Session()
    seen: dict[str, dict] = {}
    for page in range(1, max_pages + 1):
        resp = session.get(LIST_URL, params={"page": page}, timeout=60)
        resp.raise_for_status()
        new = [r for r in parse_list_page(resp.text) if r["url"] not in seen]
        if not new:
            break
        seen.update({r["url"]: r for r in new})
        log.info("page %d: %d new actions (%d total)", page, len(new), len(seen))
        time.sleep(pause)
    df = pd.DataFrame(seen.values(), columns=["company", "date_filed", "url", "description"])
    return df.sort_values("date_filed").reset_index(drop=True)

"""Draws the HTML and CSS parts in this folder.

These are the parts that are only shown, never clicked (the hero, a trip day, the theme):
they're written as HTML and CSS so the page structure and styling can be changed without
touching Python. Values are escaped before they go into the HTML. Anything you click stays a
Streamlit widget, because it has to send data back to Python.
"""

import base64
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template

import streamlit as st

FOLDER = Path(__file__).parent
ASSETS = FOLDER.parent / "assets"
ITEM_START, ITEM_END = "<!-- ITEM -->", "<!-- /ITEM -->"
# Plain characters, as Streamlit's icon font isn't available inside st.html.
KIND_SYMBOLS = {"flight": "✈️", "transit": "🚆", "drive": "🚗", "stay": "🛏️", "meal": "🍽️", "attraction": "📷"}


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (FOLDER / name).read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    return Template(template).safe_substitute(values)


def theme() -> None:
    """TripMate's styles (theme.css) for the current page. Its colours follow the light or dark theme
    in the browser. Given as a .css file, st.html adds it as page styles (a <style> block in an HTML
    string would be stripped by its HTML cleaner)."""
    st.html(FOLDER / "theme.css")


def logo_path() -> Path:
    """The logo: one amber (#e8930a) that reads on both the light and the dark theme."""
    return ASSETS / "logo.svg"


@lru_cache(maxsize=2)
def _logo_data_uri(path: Path) -> str:
    # As a data URI, because st.html strips inline SVG but keeps images.
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/svg+xml;base64,{data}"


def hero(tagline: str) -> None:
    st.html(_fill(_read("hero.html"), logo=_logo_data_uri(logo_path()), tagline=escape(tagline)))


def divider(text: str) -> None:
    """A line with a word in the middle ("or"), styled in theme.css."""
    st.html(f'<div class="tm-or">{escape(text)}</div>')


def _item_html(template: str, item: dict) -> str:
    link = item.get("link") or ""
    steps = item.get("steps") or []
    return _fill(
        template,
        icon=KIND_SYMBOLS.get(item["kind"], "•"),
        title=escape(item["title"] or ""),
        price=f' · <span class="tm-price">{escape(item["price"])}</span>' if item.get("price") else "",
        link=f' · <a href="{escape(link)}" target="_blank" rel="noopener">link</a>'
             if link.startswith(("http://", "https://")) else "",
        detail=f'<div class="tm-detail">{escape(item["detail"])}</div>' if item.get("detail") else "",
        steps=("<details><summary>Steps</summary><ol>" + "".join(f"<li>{escape(s)}</li>" for s in steps)
               + "</ol></details>") if steps else "",
    )


def day_html(day: dict) -> str:
    """One trip day as HTML, from timeline.html (separate from drawing, so it can be tested)."""
    page = _read("timeline.html")
    start, end = page.index(ITEM_START), page.index(ITEM_END) + len(ITEM_END)
    item_template = page[start + len(ITEM_START):end - len(ITEM_END)]
    items = "".join(_item_html(item_template, item) for item in day["items"])
    when = f" · {date.fromisoformat(day['date']):%a %d %b}" if day.get("date") else ""
    unpriced = "".join(f'<div class="tm-unpriced">No price: {escape(name)}</div>'
                       for name in day.get("unpriced") or [])
    # The day is filled in before the items go in, so a "$" in an item's text is never read as a placeholder.
    outer = _fill(page[:start] + "\0items\0" + page[end:], day=str(day["day"]), date=escape(when),
                  city=escape(day.get("city") or ""), unpriced=unpriced)
    return outer.replace("\0items\0", items)


def timeline_day(day: dict) -> None:
    st.html(day_html(day))

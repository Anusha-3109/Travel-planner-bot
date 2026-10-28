"""The two themes' colours, for the parts Streamlit's theme doesn't reach: charts, the map, the
"How it answers" diagram and the CSS in frontend/html/theme.css. They match the [theme.dark] and
[theme.light] sections of .streamlit/config.toml. Chart colours were checked for colour-blind
separation on each theme's background, which is why the chart amber differs from the accent.

colours() gives the set for the theme the viewer has chosen in Streamlit's menu (⋮ → Settings:
Light, Dark or System); Graphite amber when it can't tell.
"""

import streamlit as st

DARK = {
    "accent": "#f59e0b",  # buttons, links, the logo (primaryColor)
    "chart_amber": "#c98500", "chart_soft": "#fcd34d",  # chart marks, and a second series of the same kind
    "chart_blue": "#3987e5", "chart_teal": "#199e70", "neutral": "#8b8b8b", "danger": "#ef4444",
    "background": "#161616", "card": "#202020", "field": "#161616", "sidebar": "#111111",
    "border": "#2f2f2f", "text": "#ececec", "muted": "#a3a3a3", "soft_text": "#cfcfcf", "link": "#fbbf24",
}
LIGHT = {
    "accent": "#d97706",
    "chart_amber": "#b45309", "chart_soft": "#e9a23b",
    "chart_blue": "#2a78d6", "chart_teal": "#0f8a5f", "neutral": "#7a7268", "danger": "#c62828",
    "background": "#faf8f4", "card": "#ffffff", "field": "#fffdf9", "sidebar": "#f1ede5",
    "border": "#e6dfd3", "text": "#1f1b16", "muted": "#6f665c", "soft_text": "#4a433b", "link": "#b45309",
}
ON_ACCENT = "#1c1300"  # dark text on amber buttons, in both themes (white on amber is too faint)


def theme_type() -> str:
    """ "light" or "dark": the theme the viewer's browser shows (dark when it can't tell)."""
    try:
        return "light" if st.context.theme.type == "light" else "dark"
    except Exception:  # outside a running app, for example in a test that builds a chart
        return "dark"


def colours() -> dict[str, str]:
    return LIGHT if theme_type() == "light" else DARK


def rgb(hex_colour: str) -> list[int]:
    """'#f59e0b' -> [245, 158, 11], for pydeck's map layers."""
    return [int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)]

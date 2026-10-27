"""The Graphite amber theme's colours, for the parts Streamlit's theme doesn't reach: charts,
the map, the "How it answers" diagram and the CSS in frontend/html/theme.css. They match
.streamlit/config.toml. Chart colours were checked for colour-blind separation on the dark
background, which is why the chart amber is a step darker than the accent.
"""

ACCENT = "#f59e0b"  # buttons, links, the logo (theme primaryColor)
ACCENT_SOFT = "#fcd34d"  # a lighter amber for a second series of the same kind
CHART_AMBER = "#c98500"  # amber for chart marks
CHART_BLUE = "#3987e5"  # the second chart colour
CHART_TEAL = "#199e70"
NEUTRAL = "#8b8b8b"  # muted marks, lines and "other"
DANGER = "#ef4444"
BACKGROUND, SURFACE, BORDER, TEXT = "#161616", "#202020", "#2f2f2f", "#ececec"

# The same colours as [r, g, b] for pydeck's map layers.
ACCENT_RGB = [245, 158, 11]
TEAL_RGB = [25, 158, 112]
NEUTRAL_RGB = [139, 139, 139]

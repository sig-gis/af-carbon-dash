"""Deterministic palette coloring for map polygons.

Pure helper — no Streamlit / folium dependency — so it stays easy to
reason about and reuse (legends, charts, downloaded reports).
"""

from __future__ import annotations

import hashlib

# Curated 12-color palette: mid-saturation, distinct on CartoDB Positron,
# DO NOT use yellow/red, reserved for the hover/selection highlight.
PALETTE: tuple[str, ...] = (
    "#1f77b4",  # steel blue
    "#2ca02c",  # forest green
    "#9467bd",  # purple
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#17becf",  # cyan
    "#2b5f76",  # slate teal
    "#ff7f0e",  # orange
    "#5254a3",  # indigo
    "#637939",  # moss
    "#ce6dbd",  # magenta
    "#a55194",  # plum
)


def color_for_feature(properties: dict) -> str:
    """Return a deterministic palette color for a variant-loccode polygon.

    Falls back gracefully if either property is missing — an empty string
    still hashes, just to a consistent bucket. ``hashlib.md5`` is used
    instead of Python's built-in ``hash()`` because the latter is salted
    per interpreter run, which would change colors on every server restart.
    """
    key = f"{properties.get('FVSVariant', '')}-{properties.get('FVSLocCode', '')}"
    digest = hashlib.md5(key.encode("utf-8")).digest()
    return PALETTE[digest[0] % len(PALETTE)]

import json
from pathlib import Path

import streamlit as st


APP_ROOT = Path(__file__).resolve().parents[2]
LABEL_PATH = APP_ROOT / "conf" / "base" / "variant_labels.json"


@st.cache_data
def load_variant_labels() -> dict[str, str]:
    """Load user-facing FVS variant labels keyed by internal variant code."""
    try:
        with open(LABEL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def variant_display_name(variant: str | None) -> str:
    """Return the friendly display label for an internal variant code."""
    if not variant:
        return ""
    return load_variant_labels().get(str(variant), str(variant))


def format_variant_label(variant: str | None, *, include_code: bool = False) -> str:
    """Format a variant for UI display while preserving raw codes internally.

    Public pages can use the friendly label only. Admin/model-management views
    should pass ``include_code=True`` so staff can still see the registry code.
    """
    if not variant:
        return ""
    variant_code = str(variant)
    label = variant_display_name(variant_code)
    if include_code and label != variant_code:
        return f"{label} ({variant_code})"
    return label
"""Per-variant slider bounds derived from variant presets.

Pure helpers — no Streamlit dependency — so they stay easy to reason about
and will be the natural first unit-test targets once test infra exists.
"""

from __future__ import annotations

# Fallbacks used when a variant preset has no explicit bound fields.
DEFAULT_SI_MIN = 0
DEFAULT_SI_MAX = 300
DEFAULT_SURVIVAL_MIN = 50
DEFAULT_SURVIVAL_MAX = 90


def slider_bounds(preset: dict) -> dict:
    """Return the SI and survival slider bounds for a variant preset.

    Falls back to module-level defaults for any field the preset omits.
    """
    return {
        "si_min": int(preset.get("si_min", DEFAULT_SI_MIN)),
        "si_max": int(preset.get("si_max", DEFAULT_SI_MAX)),
        "survival_min": int(preset.get("survival_min", DEFAULT_SURVIVAL_MIN)),
        "survival_max": int(preset.get("survival_max", DEFAULT_SURVIVAL_MAX)),
    }


def clamp(value: int, lo: int, hi: int) -> int:
    """Constrain ``value`` to the inclusive range ``[lo, hi]``."""
    return int(min(max(value, lo), hi))

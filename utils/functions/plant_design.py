import json
import os
from pathlib import Path
from urllib.parse import urlparse

import altair as alt
import numpy as np
import numpy_financial as npf
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from matplotlib import colors as mcolors
from plotly.colors import qualitative
from scipy.interpolate import make_interp_spline

from model_service.main import (
    _load_proforma_defaults,
    load_variant_presets,
    load_variant_species,
)
from utils.config import get_api_base_url, normalize_params
from utils.functions.helper import HELP, H
from utils.functions.slider_bounds import clamp, slider_bounds
from utils.functions.statefulness import (
    _backup_keys,
    _carbon_units_keys,
    _init_carbon_units_state,
    _init_planting_state,
    _restore_backup,
    _species_keys,
    _species_label,
)

SI_INSENSITIVE_VARIANTS = {"CI", "IE"}


def _resolve_sub_variants(map_variant: str, loccode: str) -> list[str]:
    """
    Given a variant code from the map (e.g. 'CR') and a loccode, return the
    sub-variants that have models available for that loccode in the registry.
    Falls back to species config prefix matching if no registry entries found.
    """
    try:
        resp = requests.get(f"{get_api_base_url()}/models/registry", timeout=5)
        resp.raise_for_status()
        registry = resp.json().get("models", [])
    except Exception:
        registry = []

    # Prefer registry varloc matches
    registered = sorted(
        {
            m["variant"]
            for m in registry
            if m.get("loccode") == loccode
            and m.get("variant")
            and (
                m["variant"] == map_variant
                or m["variant"].startswith(map_variant + "_")
            )
        }
    )
    if registered:
        return registered

    # Fallback with species-config keys matching map_variant
    vs = load_variant_species()
    sub_keys = sorted(
        k
        for k, v in vs.items()
        if isinstance(v, list) and k.startswith(map_variant + "_")
    )
    if sub_keys:
        return sub_keys
    if map_variant in vs and isinstance(vs[map_variant], list):
        return [map_variant]
    return [map_variant]


API_BASE_URL = get_api_base_url()

CHART_BASE_YEAR = 2026
HATCH_START_AGE = 40
HATCH_BG_ALPHA = 0.08
HATCH_LINE_ALPHA = 0.18
HATCH_STEP_YEARS = 2.0
HATCH_SLOPE_YEARS = 4.0
BASE_LINE_WIDTH = 3.0
PROTOCOL_ORDER = ["ACR", "CAR", "VERRA", "GS", "ISO"]

# Keep protocol line colors stable regardless of selection/removal order.
PROTOCOL_COLOR_MAP = {
    "ACR": "#1f77b4",
    "CAR": "#ff7f0e",
    "VERRA": "#2ca02c",
    "GS": "#d62728",
    "ISO": "#9467bd",
}


def _rgba_with_alpha(color: str, alpha: float) -> str:
    """Convert a matplotlib/hex color into an rgba(...) string with custom alpha."""
    r, g, b, _ = mcolors.to_rgba(color)
    return f"rgba({int(r * 255)}, {int(g * 255)}, {int(b * 255)}, {alpha:.3f})"


def _add_fading_line_series(
    fig: go.Figure,
    series_df: pd.DataFrame,
    x_col: str,
    y_col: str,
    color: str,
    label: str | None,
    showlegend: bool,
    line_dash: str = "solid",
):
    """Add a single series to a Plotly figure with constant-opacity lines/markers."""
    if series_df.empty:
        return

    x = series_df[x_col].astype(float).to_numpy()
    y = series_df[y_col].astype(float).to_numpy()

    if len(x) == 1:
        marker_color = _rgba_with_alpha(color, 1.0)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="markers",
                marker=dict(color=[marker_color], size=7),
                name=label,
                legendgroup=label,
                showlegend=showlegend,
                hovertemplate=f"Year: %{{x:.0f}}<br>{y_col}: %{{y:,.2f}}"
                + (f"<br>Series: {label}" if label else "")
                + "<extra></extra>",
            )
        )
        return

    for idx in range(len(x) - 1):
        x0, x1 = x[idx], x[idx + 1]
        y0, y1 = y[idx], y[idx + 1]
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(
                    color=_rgba_with_alpha(color, 1.0),
                    width=BASE_LINE_WIDTH,
                    dash=line_dash,
                ),
                name=label,
                legendgroup=label,
                showlegend=showlegend and idx == 0,
                hoverinfo="skip",
            )
        )

    marker_colors = [_rgba_with_alpha(color, 1.0) for _ in x]
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="markers",
            marker=dict(color=marker_colors, size=7),
            name=label,
            legendgroup=label,
            showlegend=False,
            hovertemplate=f"Year: %{{x:.0f}}<br>{y_col}: %{{y:,.2f}}"
            + (f"<br>Series: {label}" if label else "")
            + "<extra></extra>",
        )
    )


def _plot_fading_line_chart(
    data: pd.DataFrame,
    x_col: str,
    y_col: str,
    title: str,
    y_title: str,
    include_years: list[int],
    series_col: str | None = None,
    show_future_hatch: bool = False,
):
    """Render a Plotly line chart with optional year-40+ hatch background."""
    fig = go.Figure()

    # hatch_start_year = CHART_BASE_YEAR + HATCH_START_AGE
    # x_end = max(include_years) if include_years else CHART_BASE_YEAR
    chart_start_year = min(include_years) if include_years else int(data[x_col].min())
    hatch_start_year = chart_start_year + HATCH_START_AGE
    x_end = max(include_years) if include_years else chart_start_year

    if (
        show_future_hatch
        and x_end > hatch_start_year
        and not data.empty
        and y_col in data.columns
    ):
        y_series = data[y_col].astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        if not y_series.empty:
            y_min = float(y_series.min())
            y_max = float(y_series.max())
            if y_min == y_max:
                pad = max(abs(y_min) * 0.05, 1.0)
                y_min -= pad
                y_max += pad

            fig.add_shape(
                type="rect",
                x0=hatch_start_year,
                x1=x_end,
                y0=y_min,
                y1=y_max,
                xref="x",
                yref="y",
                line=dict(width=0),
                fillcolor=f"rgba(120,120,120,{HATCH_BG_ALPHA:.3f})",
                layer="below",
            )

            x_cursor = hatch_start_year - (y_max - y_min)
            while x_cursor < x_end:
                x0 = max(hatch_start_year, x_cursor)
                x1 = min(x_end, x_cursor + HATCH_SLOPE_YEARS)
                if x1 > x0:
                    fig.add_shape(
                        type="line",
                        x0=x0,
                        y0=y_min,
                        x1=x1,
                        y1=y_max,
                        xref="x",
                        yref="y",
                        line=dict(
                            color=f"rgba(90,90,90,{HATCH_LINE_ALPHA:.3f})", width=1
                        ),
                        layer="below",
                    )
                x_cursor += HATCH_STEP_YEARS

    if series_col:
        series_vals = data[series_col].dropna().unique().tolist()
        protocol_dash_map = {"ACR": "dash", "CAR": "longdash", "VERRA": "dot"}
        if series_col == "Protocol":
            ordered = [p for p in PROTOCOL_ORDER if p in series_vals]
            remaining = [s for s in series_vals if s not in ordered]
            series_vals = ordered + sorted(remaining)
        # Keep protocol colors stable regardless of selection order.
        palette = qualitative.Plotly
        fallback_cycle = iter(palette)
        color_map: dict[str, str] = {}
        for s in series_vals:
            key = str(s)
            if key in PROTOCOL_COLOR_MAP:
                color_map[s] = PROTOCOL_COLOR_MAP[key]
            else:
                color_map[s] = next(fallback_cycle, "#7f7f7f")

        for s in series_vals:
            s_df = data[data[series_col] == s].sort_values(x_col)
            _add_fading_line_series(
                fig=fig,
                series_df=s_df,
                x_col=x_col,
                y_col=y_col,
                color=color_map[s],
                label=str(s),
                showlegend=True,
                line_dash=protocol_dash_map.get(str(s), "solid")
                if series_col == "Protocol"
                else "solid",
            )
    else:
        _add_fading_line_series(
            fig=fig,
            series_df=data.sort_values(x_col),
            x_col=x_col,
            y_col=y_col,
            color=qualitative.Plotly[0],
            label=None,
            showlegend=False,
        )

    fig.update_layout(
        title=title,
        template="plotly_white",
        height=400,
        margin=dict(l=20, r=20, t=50, b=20),
        legend_title=series_col if series_col else None,
    )
    fig.update_xaxes(
        title_text="Year",
        tickvals=include_years,
        tickformat="d",
        tickangle=30,
        # range=[CHART_BASE_YEAR, max(include_years)],
        range=[chart_start_year, max(include_years)],
        showgrid=True,
        gridcolor="rgba(0,0,0,0.15)",
    )
    fig.update_yaxes(
        title_text=y_title,
        showgrid=True,
        gridcolor="rgba(0,0,0,0.15)",
    )

    st.plotly_chart(fig, use_container_width=True)


def _five_year_values(max_year: int, start_year) -> list[int]:
    """Return 5-year x-axis values from start_year through max_year (inclusive range)."""
    if max_year < start_year:
        return [start_year]
    return list(range(start_year, int(max_year) + 1, 5))


def _filter_to_five_year_intervals(
    df: pd.DataFrame,
    year_col: str = "Year",
    # start_year: int = CHART_BASE_YEAR,
    start_year: int | None = None,
) -> tuple[pd.DataFrame, list[int]]:
    """Keep rows at/after start_year and restricted to 5-year intervals from start_year."""
    out = df.copy()

    if start_year is None:
        start_year = int(pd.to_numeric(out[year_col], errors="coerce").min())

    out = out[out[year_col] >= start_year]
    if out.empty:
        return out, [start_year]

    include_years = _five_year_values(int(out[year_col].max()), start_year=start_year)
    out = out[out[year_col].isin(include_years)]
    return out, include_years

def _regrid_series_to_five_year_intervals(
    df: pd.DataFrame,
    value_col: str,
    year_col: str = "Year",
    # start_year: int = CHART_BASE_YEAR,
    start_year: int | None = None,
) -> tuple[pd.DataFrame, list[int]]:
    """Interpolate a single series onto 5-year grid from start_year."""
    out = df.copy()

    if start_year is None:
        start_year = int(pd.to_numeric(out[year_col], errors="coerce").min())

    out = out[out[year_col] >= start_year]
    out = out[[year_col, value_col]].dropna().sort_values(year_col)
    if out.empty:
        return out, [start_year]

    x = out[year_col].astype(float).to_numpy()
    y = out[value_col].astype(float).to_numpy()
    include_years = _five_year_values(int(x.max()), start_year=start_year)
    xi = np.array(include_years, dtype=float)
    yi = np.interp(xi, x, y)

    reg = pd.DataFrame({year_col: xi.astype(int), value_col: yi})
    return reg, include_years

def _co2e_accumulation_summary(
    df: pd.DataFrame,
    value_col: str = "CO2e",
    year_col: str = "Year",
    # base_year: int = CHART_BASE_YEAR,
    base_year: int | None = None,
    horizons: tuple[int, ...] = (10, 50, 100),
) -> pd.DataFrame:
    """Return CO2e accumulation values interpolated at project-year horizons."""
    if df.empty or value_col not in df.columns or year_col not in df.columns:
        return pd.DataFrame()

    curve = df[[year_col, value_col]].copy()
    curve[year_col] = pd.to_numeric(curve[year_col], errors="coerce")
    curve[value_col] = pd.to_numeric(curve[value_col], errors="coerce")
    curve = curve.dropna(subset=[year_col, value_col]).sort_values(year_col)

    if curve.empty:
        return pd.DataFrame()

    if base_year is None:
        base_year = int(curve[year_col].min())

    x = curve[year_col].astype(float).to_numpy()
    y = curve[value_col].astype(float).to_numpy()
    target_years = np.array([base_year + horizon for horizon in horizons], dtype=float)
    values = np.interp(target_years, x, y)

    return pd.DataFrame(
        [
            {f"Year {horizon}": f"{value:,.2f}" for horizon, value in zip(horizons, values)}
        ]
    )


def _protocol_color_scale(protocols: list[str]) -> alt.Scale:
    """Build a deterministic Altair color scale for selected protocols."""
    domain = [p for p in protocols if p in PROTOCOL_COLOR_MAP]
    # Fallback color for any unknown protocol names
    unknown = [p for p in protocols if p not in PROTOCOL_COLOR_MAP]
    domain.extend(unknown)

    color_range = [PROTOCOL_COLOR_MAP[p] for p in domain if p in PROTOCOL_COLOR_MAP]
    color_range.extend(["#7f7f7f"] * len(unknown))

    return alt.Scale(domain=domain, range=color_range)


def _protocol_dash_scale(protocols: list[str]) -> alt.Scale:
    """Stable protocol dash mapping while preserving existing colors."""
    domain = [p for p in protocols if p in PROTOCOL_COLOR_MAP]
    unknown = [p for p in protocols if p not in PROTOCOL_COLOR_MAP]
    domain.extend(unknown)

    # ACR/CAR/VERRA get dashed styles; others remain solid.
    dash_map = {
        "ACR": [6, 4],
        "CAR": [10, 4],
        "VERRA": [2, 3],
    }
    dash_range = [dash_map.get(p, [1, 0]) for p in domain]
    return alt.Scale(domain=domain, range=dash_range)


def _build_future_hatch_layers(
    df: pd.DataFrame,
    y_col: str,
    include_years: list[int],
) -> alt.LayerChart | None:
    """Create subtle future-period hatch-like background (year 40 onward)."""
    if df.empty or y_col not in df.columns or not include_years:
        return None

    hatch_start = CHART_BASE_YEAR + HATCH_START_AGE
    x_end = max(include_years)
    if x_end <= hatch_start:
        return None

    y_series = pd.to_numeric(df[y_col], errors="coerce").dropna()
    if y_series.empty:
        return None
    y_min = float(y_series.min())
    y_max = float(y_series.max())
    if y_min == y_max:
        pad = max(abs(y_min) * 0.05, 1.0)
        y_min -= pad
        y_max += pad

    rect_df = pd.DataFrame([{"x0": hatch_start, "x1": x_end, "y0": y_min, "y1": y_max}])
    rect = (
        alt.Chart(rect_df)
        .mark_rect(color="#777777", opacity=0.08)
        .encode(
            x="x0:Q",
            x2="x1:Q",
            y="y0:Q",
            y2="y1:Q",
        )
    )

    stripe_years = np.arange(hatch_start, x_end + 0.1, 2.0)
    stripe_df = pd.DataFrame({"x": stripe_years, "y0": y_min, "y1": y_max})
    stripes = (
        alt.Chart(stripe_df)
        .mark_rule(color="#666666", opacity=0.18, strokeDash=[2, 3])
        .encode(
            x="x:Q",
            y="y0:Q",
            y2="y1:Q",
        )
    )

    return rect + stripes

# def _prepend_zero_year_row(
#     df: pd.DataFrame,
#     value_col: str,
#     year_col: str = "Year",
#     base_year: int = CHART_BASE_YEAR,
# ) -> pd.DataFrame:
#     """Prepend a synthetic base-year row (value=0) for single-series charts."""
#     out = df.copy()
#     out = out[out[year_col] != base_year]
#     zero_row = {col: np.nan for col in out.columns}
#     zero_row[year_col] = base_year
#     zero_row[value_col] = 0.0
#     out = pd.concat([pd.DataFrame([zero_row]), out], ignore_index=True)
#     return out.sort_values(year_col).reset_index(drop=True)


# def _prepend_zero_year_rows_by_group(
#     df: pd.DataFrame,
#     group_col: str,
#     value_col: str,
#     year_col: str = "Year",
#     base_year: int = CHART_BASE_YEAR,
# ) -> pd.DataFrame:
#     """Prepend a synthetic base-year row (value=0) for each group in multi-series charts."""
#     out = df.copy()
#     out = out[out[year_col] != base_year]
#     groups = out[group_col].dropna().unique().tolist()

#     if not groups:
#         return out

#     zero_rows = pd.DataFrame(
#         [{year_col: base_year, group_col: g, value_col: 0.0} for g in groups]
#     )
#     out = pd.concat([zero_rows, out], ignore_index=True)
#     return out.sort_values([group_col, year_col]).reset_index(drop=True)


def _credits_keys(prefix: str = "credits_") -> list[str]:
    """
    Return all proforma input keys (prefixed) that should persist for the Credits section.
    Uses the JSON defaults as the source for which keys exist.
    """
    defaults = _proforma_base_defaults()
    return [prefix + k for k in defaults.keys()]


def _seed_defaults(prefix: str = "credits_"):
    """
    Seed Streamlit session state with default financial and credit parameters
    based on proforma defaults. Only sets missing keys.
    """
    defaults = _proforma_base_defaults()
    for k, v in defaults.items():
        st.session_state.setdefault(prefix + k, v)


def _proforma_base_defaults() -> dict:
    """Return the global/fallback proforma defaults.

    Supports both the original flat proforma_presets.json structure and the new
    structure with protocol-specific overrides:

        {
            "num_plots": 250,
                flat fallback defaults ...,
            "protocol_overrides": {
                "ACR": {"registry_fees": 8500},
                ...
            }
        }
    """
    raw = _load_proforma_defaults() or {}

    # If a future JSON is wrapped as {"defaults": {...}, "protocol_overrides": {...}},
    # use the wrapped defaults. Otherwise keep the current flat structure and
    # ignore nested override blocks when building the fallback defaults.
    if isinstance(raw.get("defaults"), dict):
        return raw["defaults"].copy()

    return {
        k: v
        for k, v in raw.items()
        if k not in {"defaults", "protocol_overrides", "protocols"}
    }


def _proforma_protocol_overrides() -> dict:
    """Return protocol-specific proforma overrides from proforma_presets.json."""
    raw = _load_proforma_defaults() or {}
    overrides = raw.get("protocol_overrides") or raw.get("protocols") or {}
    return overrides if isinstance(overrides, dict) else {}


def _proforma_defaults_for_protocol(protocol: str) -> dict:
    """Merge fallback defaults with protocol-specific overrides.

    Blank/null override values are ignored so incomplete protocol rows, such as
    ISO with some blank cells, safely fall back to the global defaults.
    """
    defaults = _proforma_base_defaults()
    overrides = _proforma_protocol_overrides().get(protocol, {})

    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if v is not None:
                defaults[k] = v

    return defaults


def _sync_active_variant():
    """Push a Planting Design sub-variant pick into ``active_variant``.

    Runs as the selectbox ``on_change`` callback (before the rerun) so the
    single source of truth reflects the user's choice *before* the widget is
    re-seeded from it on the next run.
    """
    st.session_state["active_variant"] = st.session_state.get("planting_sub_variant")


def planting_sliders():
    """
    Render all planting-related Streamlit sliders. Restores saved state, renders species sliders, computes species mix values, and stores
    all planting parameters in session state.
    """
    presets = load_variant_presets()
    map_variant = st.session_state.get("selected_variant", "PN")
    varloc_name = st.session_state.get(
        "selected_varloc_name", "Olympic National Forest"
    )
    varloc_code = st.session_state.get("selected_varloc_code", "609")

    # Sub-variant refinement at the committed location. The Site Selection
    # chooser may have already set ``active_variant`` (incl. cross-variant
    # overlaps); here the user can still switch between sub-variants registered
    # at this loccode (e.g. NC_1 vs NC_2). Selection stays in sync via
    # ``active_variant``.
    sub_variants = _resolve_sub_variants(map_variant, varloc_code)
    current = st.session_state.get("active_variant")
    if current not in sub_variants:
        current = sub_variants[0]
    # ``active_variant`` is the single source of truth for the sub-variant.
    # Seed the keyed selectbox from it every run so an upstream change (the
    # Site Selection chooser) propagates here. A keyed widget's stored value
    # otherwise overrides the ``index=`` default whenever it is still a valid
    # option (e.g. switching NC_1 <-> NC_2), silently pinning the variant — and
    # with it the species list and the variant actually run. ``on_change``
    # pushes user picks back into ``active_variant`` so this never clobbers a
    # fresh selection.
    st.session_state["planting_sub_variant"] = current

    if len(sub_variants) > 1:
        variant = st.selectbox(
            "FVS Variant",
            options=sub_variants,
            key="planting_sub_variant",
            on_change=_sync_active_variant,
            help=H("planting.variant_label"),
        )
    else:
        variant = sub_variants[0]
        st.markdown(
            f"**FVS Variant:** {variant}",
            unsafe_allow_html=False,
            help=H("planting.variant_label"),
            width="stretch",
        )
    st.session_state["active_variant"] = variant

    if variant not in presets:
        st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
    preset = presets.get(variant, presets.get("PN", {}))
    st.markdown(
        f"**FVS Location Name:** {varloc_name}",
        unsafe_allow_html=False,
        help=H("planting.varloc_label"),
        width="stretch",
    )
    st.markdown(
        f"**FVS Location Code:** {varloc_code}",
        unsafe_allow_html=False,
        help=H("planting.varcode_label"),
        width="stretch",
    )

    sp_keys = _species_keys(variant)

    # restore any missing keys from previous interaction with page
    _restore_backup(["survival", "si", "net_acres", *sp_keys])

    # Initialize presets ONLY if the variant truly changed
    _init_planting_state(variant, preset)

    # Per-variant slider bounds. Clamp before rendering to avoid StreamlitValueBelowMinError.
    bounds = slider_bounds(preset)
    st.session_state["si"] = clamp(
        int(st.session_state.get("si", bounds["si_min"])),
        bounds["si_min"],
        bounds["si_max"],
    )
    st.session_state["survival"] = clamp(
        int(st.session_state.get("survival", bounds["survival_min"])),
        bounds["survival_min"],
        bounds["survival_max"],
    )

    st.number_input(
        "Net Acres:",
        min_value=1,
        step=100,
        key="net_acres",
        help=H("number.inputs.acres"),
    )
    st.caption(f"{int(st.session_state.get('net_acres', 0)):,} acres")
    st.slider(
        "Survival Percentage",
        bounds["survival_min"],
        bounds["survival_max"],
        key="survival",
        help=H("planting.slider_survival"),
    )
    si_locked = variant.split("_")[0] in SI_INSENSITIVE_VARIANTS
    st.slider(
        "Site Index",
        bounds["si_min"],
        bounds["si_max"],
        key="si",
        disabled=si_locked,
        help=H("planting.slider_si_disabled") if si_locked else H("planting.slider_si"),
    )

    st.markdown(
        "Species Mix (TPA)",
        unsafe_allow_html=False,
        help=H("planting.species_mix_header"),
        width="stretch",
    )
    tpa_cap = preset.get("_tpa_cap", 435)
    for i, spk in enumerate(sp_keys):
        st.slider(_species_label(variant, i), 0, tpa_cap, key=spk)

    # Summary
    total_tpa = sum(int(st.session_state.get(k, 0)) for k in sp_keys)
    st.markdown(
        f"**Total TPA:** {total_tpa}",
        unsafe_allow_html=False,
        help=H("planting.total_tpa_label"),
        width="stretch",
    )
    if total_tpa > tpa_cap:
        st.warning(
            f"Total initial TPA exceeds {tpa_cap} and may present an unrealistic scenario. Consider adjusting sliders."
        )
    elif total_tpa == 0:
        st.error(
            "Set at least one species above 0 TPA. A planting design with no trees "
            "produces no carbon."
        )

    # Store as positional list for the API
    st.session_state["species_tpa"] = [int(st.session_state.get(k, 0)) for k in sp_keys]

    # Backup latest values so they're available if user navigates away and back
    _backup_keys(["survival", "si", "net_acres", *sp_keys])


def carbon_chart():
    if not all(
        k in st.session_state for k in ["survival", "si", "net_acres", "species_tpa"]
    ):
        st.info("Adjust Planting Design sliders to see the carbon output.")
        return

    species_tpa = st.session_state["species_tpa"]
    if not species_tpa or all(v == 0 for v in species_tpa):
        st.info("Set at least one species TPA value.")
        return

    variant = st.session_state.get(
        "active_variant", st.session_state.get("selected_variant", "PN")
    )
    loccode = st.session_state.get("selected_varloc_code", "609")

    _PCT_LABELS = HELP.get("planting.pct_level", {}).get("labels") or {
        "PCT0": "None — no pre-commercial thinning",
        "PCT1": "Light thinning",
        "PCT2": "Moderate thinning",
    }
    # Fetch available PCT levels with retention percentages for this variant/location
    try:
        _pct_resp = requests.get(
            f"{API_BASE_URL}/models/pct-info",
            params={"variant": variant, "loccode": loccode},
            timeout=5,
        )
        _pct_resp.raise_for_status()
        _pct_info = {p["pct_level"]: p.get("pct_retention") for p in _pct_resp.json()}
    except Exception:
        _pct_info = {"PCT0": None, "PCT1": None, "PCT2": None}

    _pct_options = sorted(_pct_info.keys())

    def _fmt_pct(code: str) -> str:
        label = _PCT_LABELS.get(code, code)
        ret = _pct_info.get(code)
        return f"{label} ({ret}% of trees retained)" if ret is not None else label

    pct_level = st.selectbox(
        "Pre-commercial Thin (PCT)",
        options=_pct_options,
        format_func=_fmt_pct,
        key="pct_level",
        help=H("planting.pct_level"),
    )

    # Store retention % in session state for reports
    st.session_state["pct_retention"] = _pct_info.get(pct_level)

    payload = {
        "variant": variant,
        "loccode": loccode,
        "survival": st.session_state["survival"],
        "si": st.session_state["si"],
        "species_tpa": [float(v) for v in species_tpa],
        "pct_level": pct_level,
    }

    resp = requests.post(
        f"{API_BASE_URL}/carbon/calculate",
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()

    result = resp.json()
    df = pd.DataFrame(result["carbon_df"])
    st.session_state.carbon_df = df
    model_source = result.get("model_source", "coefficients")

    # Metric definitions: label, column, unit (per-acre), unit (project), scales_with_acres
    METRIC_DEFS = {
        "CO2e": {
            "label": "CO2e",
            "unit": "tons CO2e/acre",
            "unit_project": "tons CO2e",
            "scales": True,
        },
        "BA": {
            "label": "Basal area",
            "unit": "sq ft/acre",
            "unit_project": "sq ft",
            "scales": True,
        },
        "ABLD_C": {
            "label": "Aboveground live biomass carbon",
            "unit": "tons",
            "unit_project": "tons",
            "scales": True,
        },
        "QMD": {
            "label": "Quadratic mean diameter",
            "unit": "inches",
            "unit_project": "inches",
            "scales": False,
        },
        "SDI": {
            "label": "Stand density index",
            "unit": "index",
            "unit_project": "index",
            "scales": False,
        },
        "TCuFt": {
            "label": "Total cubic volume",
            "unit": "cu ft/acre",
            "unit_project": "cu ft",
            "scales": True,
        },
        "MCuFt": {
            "label": "Merchantable cubic volume",
            "unit": "cu ft/acre",
            "unit_project": "cu ft",
            "scales": True,
        },
        "Tpa": {
            "label": "Trees per acre",
            "unit": "trees/acre",
            "unit_project": "trees/acre",
            "scales": False,
        },
    }

    # Convert aboveground live biomass carbon to CO2e
    if "ABLD_C" in df.columns:
        df["CO2e"] = df["ABLD_C"] * 3.667

    available = {col: METRIC_DEFS[col] for col in METRIC_DEFS if col in df.columns}

    toggle_oc = st.toggle(
        "Show Total Project Acreage", True, "toggle_oc", H("toggle.inputs.acres")
    )
    net_acres = st.session_state["net_acres"]

    plot_df = df.copy()

    if toggle_oc:
        for col, meta in available.items():
            if meta["scales"]:
                plot_df[col] = plot_df[col] * net_acres

    if len(available) > 1:
        # FVS model: dual metric selectors
        metric_labels = {m["label"]: col for col, m in available.items()}
        metric_options = list(metric_labels.keys())
        col_select_1, col_select_2 = st.columns(2)
        with col_select_1:
            primary_label = st.selectbox(
                "Primary variable",
                metric_options,
                index=0,
                key="primary_metric_select",
            )
        with col_select_2:
            secondary_default = min(1, len(metric_options) - 1)
            secondary_label = st.selectbox(
                "Secondary variable",
                metric_options,
                index=secondary_default,
                key="secondary_metric_select",
            )
        st.divider()

        def _render_metric(label: str):
            col = metric_labels[label]
            meta = available[col]
            unit = (
                meta["unit_project"] if (toggle_oc and meta["scales"]) else meta["unit"]
            )
            # df_m = _prepend_zero_year_row(
            #     plot_df[["Year", col]].copy(), value_col=col, base_year=CHART_BASE_YEAR
            # )
            # df_m, inc = _regrid_series_to_five_year_intervals(
            #     df_m, value_col=col, year_col="Year", start_year=CHART_BASE_YEAR
            # )

            df_m = plot_df[["Year", col]].copy()
            chart_start_year = int(df_m["Year"].min())

            df_m, inc = _regrid_series_to_five_year_intervals(
                df_m, value_col=col, year_col="Year", start_year=chart_start_year
            )

            chart = (
                alt.Chart(df_m)
                .mark_line(point=True)
                .encode(
                    x=alt.X(
                        "Year:Q",
                        title="Year",
                        axis=alt.Axis(values=inc, format="d", labelAngle=30),
                        # scale=alt.Scale(domain=[CHART_BASE_YEAR, max(inc)]),
                        scale=alt.Scale(domain=[chart_start_year, max(inc)]),
                    ),
                    y=alt.Y(f"{col}:Q", title=f"{label} ({unit})"),
                    tooltip=["Year", col],
                )
                .properties(title=label, height=350)
            )
            st.altair_chart(chart, use_container_width=True)
            # QMD disclaimer per Dave: 2029 values are unreliable
            if col == "QMD":
                st.caption(
                    "Note: QMD predictions at year 2029 are unreliable and should be interpreted with caution."
                )

        _render_metric(primary_label)
        st.divider()
        _render_metric(secondary_label)
    else:
        # Coefficient fallback: single ABLD_C chart
        chart_title = (
            "Onsite Carbon (tons/project)" if toggle_oc else "Onsite Carbon (tons/acre)"
        )
        # plot_df = _prepend_zero_year_row(
        #     plot_df, value_col="ABLD_C", base_year=CHART_BASE_YEAR
        # )
        # plot_df, include_years = _regrid_series_to_five_year_intervals(
        #     plot_df, value_col="ABLD_C", year_col="Year", start_year=CHART_BASE_YEAR
        # )

        chart_start_year = int(plot_df["Year"].min())

        plot_df, include_years = _regrid_series_to_five_year_intervals(
            plot_df, value_col="ABLD_C", year_col="Year", start_year=chart_start_year
        )

        line = (
            alt.Chart(plot_df)
            .mark_line(point=True)
            .encode(
                x=alt.X(
                    "Year:Q",
                    title="Year",
                    axis=alt.Axis(values=include_years, format="d", labelAngle=30),
                    # scale=alt.Scale(domain=[CHART_BASE_YEAR, max(include_years)]),
                    scale=alt.Scale(domain=[chart_start_year, max(include_years)]),
                ),
                y=alt.Y("ABLD_C:Q", title=chart_title),
                tooltip=["Year", "ABLD_C"],
            )
            .properties(title="Cumulative " + chart_title, width=600, height=400)
        )
        st.altair_chart(line, use_container_width=True)

    # Summary output
    if "ABLD_C" in plot_df.columns:
        final_co2e = plot_df["ABLD_C"].iloc[-1] * 3.667
        st.success(
            f"Final CO2e Output (year {int(plot_df['Year'].max())}): {final_co2e:,.2f} tons CO2e"
        )

    if model_source == "coefficients":
        st.caption(
            "Using coefficient-based estimates. Add FVS model files for richer predictions."
        )

def carbon_units():
    if "carbon_df" not in st.session_state:
        st.error("No carbon data found.")
        st.stop()

    protocols = st.session_state.get("carbon_units_inputs", {}).get("protocols", [])

    if not protocols:
        st.info("Select at least one protocol.")
        return

    payload = {
        "carbon_rows": st.session_state.carbon_df[["Year", "ABLD_C"]].to_dict(
            orient="records"
        ),
        "protocols": protocols,
    }

    json.dumps(payload)

    resp = requests.post(
        f"{API_BASE_URL}/carbon/units",
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()

    final_df = pd.DataFrame(resp.json()["rows"])

    if final_df.empty:
        st.error("No protocols selected or no data available to plot.")
        return

    st.session_state.merged_df = final_df

    toggle_ce = st.toggle(
        "Show Total Project Acreage", True, "toggle_ce", H("toggle.inputs.acres")
    )

    # Adjust values based on toggle
    plot_df = final_df.copy()
    if toggle_ce:
        plot_df["CU"] = plot_df["CU"] * st.session_state["net_acres"]

    chart_title = "(tons/project)" if toggle_ce else "(tons/acre)"

    # Add synthetic base-year zero rows
    # plot_df = _prepend_zero_year_rows_by_group(
    #     plot_df,
    #     group_col="Protocol",
    #     value_col="CU",
    #     base_year=CHART_BASE_YEAR,
    # )

    # Sort before cumulative calculations
    plot_df = plot_df.sort_values(["Protocol", "Year"])

    # Calculate cumulative CO2e values for each protocol
    plot_df["Cumulative_CU"] = plot_df.groupby("Protocol")["CU"].cumsum()

    chart_start_year = int(plot_df["Year"].min())

    # Filter to 5-year intervals for chart/table display
    # plot_df, include_years = _filter_to_five_year_intervals(
    #     plot_df, year_col="Year", start_year=CHART_BASE_YEAR
    # )

    plot_df, include_years = _filter_to_five_year_intervals(
        plot_df, year_col="Year", start_year=chart_start_year
    )

    # ----------------------------
    # Annual CO2e chart
    # ----------------------------
    _plot_fading_line_chart(
        data=plot_df,
        x_col="Year",
        y_col="CU",
        title="Annual CO2e Estimates " + chart_title,
        y_title="CO2e " + chart_title,
        include_years=include_years,
        series_col="Protocol",
        show_future_hatch=True,
    )

    # Annual CO2e table
    annual_table_df = (
        plot_df.pivot_table(
            index="Year",
            columns="Protocol",
            values="CU",
            aggfunc="first",
        )
        .reindex(columns=protocols)
        .reset_index()
        .sort_values("Year")
    )

    if not annual_table_df.empty:
        annual_table_df["Year"] = annual_table_df["Year"].astype(int)
        st.markdown("**Annual CO2e Estimates**")
        st.dataframe(
            annual_table_df.style.format(
                {col: "{:,.2f}" for col in annual_table_df.columns if col != "Year"}
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ----------------------------
    # Cumulative CO2e chart
    # ----------------------------
    _plot_fading_line_chart(
        data=plot_df,
        x_col="Year",
        y_col="Cumulative_CU",
        title="Cumulative CO2e Estimates " + chart_title,
        y_title="Cumulative CO2e " + chart_title,
        include_years=include_years,
        series_col="Protocol",
        show_future_hatch=True,
    )

    # Cumulative CO2e table
    cumulative_table_df = (
        plot_df.pivot_table(
            index="Year",
            columns="Protocol",
            values="Cumulative_CU",
            aggfunc="first",
        )
        .reindex(columns=protocols)
        .reset_index()
        .sort_values("Year")
    )

    if not cumulative_table_df.empty:
        cumulative_table_df["Year"] = cumulative_table_df["Year"].astype(int)
        st.markdown("**Cumulative CO2e Estimates**")
        st.dataframe(
            cumulative_table_df.style.format(
                {col: "{:,.2f}" for col in cumulative_table_df.columns if col != "Year"}
            ),
            use_container_width=True,
            hide_index=True,
        )


def credits_inputs(prefix: str = "credits_") -> dict:
    """
    Render per-protocol Proforma inputs with editable assumptions separated
    from fixed assumptions, and return protocol -> typed parameter dictionary.
    """
    protocols = st.session_state.get("carbon_units_inputs", {}).get("protocols", [])

    if not protocols:
        st.info(
            "Select at least one protocol in Carbon Estimates to edit project financial assumptions."
        )
        return {}

    defaults = _proforma_base_defaults()
    PRICE_OPTIONS = [15.0, 25.0, 35.0, 45.0, 55.0]

    def _nearest_price_option(value):
        return min(PRICE_OPTIONS, key=lambda x: abs(x - float(value)))

    net_acres = float(st.session_state.get("net_acres", 0) or 0)
    synced_num_plots = 200 if net_acres <= 10000 else 250
    table_state_key = f"{prefix}protocol_params"
    protocol_state = st.session_state.get(table_state_key, {})

    # Keep values only for selected protocols, and seed defaults for newly selected ones.
    protocol_state = {p: protocol_state[p] for p in protocols if p in protocol_state}
    fixed_financial_keys = [
        "cost_per_cfi_plot",
        "credit_price_increase",
        "registry_fees",
        "validation_cost",
        "verification_cost",
        "issuance_fee_per_ert",
        "anticipated_inflation",
        "discount_rate",
    ]

    for protocol in protocols:
        protocol_defaults = _proforma_defaults_for_protocol(protocol)

        if protocol not in protocol_state:
            protocol_state[protocol] = {
                "num_plots": synced_num_plots,
                "cost_per_cfi_plot": protocol_defaults.get("cost_per_cfi_plot", defaults.get("cost_per_cfi_plot", 150)),
                "price_per_ert_initial": protocol_defaults.get("price_per_ert_initial", defaults.get("price_per_ert_initial", 25.0)),
                "credit_price_increase": protocol_defaults.get("credit_price_increase", defaults.get("credit_price_increase", 2.0)),
                "registry_fees": protocol_defaults.get("registry_fees", defaults.get("registry_fees", 500)),
                "validation_cost": protocol_defaults.get("validation_cost", defaults.get("validation_cost", 45000)),
                "verification_cost": protocol_defaults.get("verification_cost", defaults.get("verification_cost", 25000)),
                "issuance_fee_per_ert": protocol_defaults.get("issuance_fee_per_ert", defaults.get("issuance_fee_per_ert", 0.15)),
                "anticipated_inflation": protocol_defaults.get("anticipated_inflation", defaults.get("anticipated_inflation", 0.0)),
                "discount_rate": protocol_defaults.get("discount_rate", defaults.get("discount_rate", 6.0)),
                "planting_cost": protocol_defaults.get("planting_cost", defaults.get("planting_cost", 1000)),
            }

        # Always sync Number of Plots to the current net acres threshold.
        protocol_state[protocol]["num_plots"] = synced_num_plots

        # Fixed assumptions should always reflect the current protocol-specific
        # preset file. Editable assumptions are intentionally not overwritten
        # after they have been seeded, so user edits persist.
        for key in fixed_financial_keys:
            if key in protocol_defaults:
                protocol_state[protocol][key] = protocol_defaults[key]

    st.session_state[table_state_key] = protocol_state

    st.markdown("Financial Options by Protocol", help=H("credits.expander_subheader"))
    st.caption("For more information on a specific assumption, hover your cursor over the column header you'd like more details on.")
    # st.info(
    #     "Edit **Initial Planting Cost / Acre** and **Initial Price / CO2e** on the left. "
    #     "The values on the right are fixed assumptions used by the financial model."
    # )

    editable_df = pd.DataFrame(
        [
            {
                "Protocol": protocol,
                "planting_cost": protocol_state[protocol]["planting_cost"],
                "price_per_ert_initial": _nearest_price_option(
                    protocol_state[protocol]["price_per_ert_initial"]
                ),
            }
            for protocol in protocols
        ]
    )

    fixed_df = pd.DataFrame(
        [
            {
                "Protocol": protocol,
                "num_plots": protocol_state[protocol]["num_plots"],
                "cost_per_cfi_plot": protocol_state[protocol]["cost_per_cfi_plot"],
                "registry_fees": protocol_state[protocol]["registry_fees"],
                "issuance_fee_per_ert": protocol_state[protocol][
                    "issuance_fee_per_ert"
                ],
                "validation_cost": protocol_state[protocol]["validation_cost"],
                "verification_cost": protocol_state[protocol]["verification_cost"],
                "anticipated_inflation": protocol_state[protocol][
                    "anticipated_inflation"
                ],
                "discount_rate": protocol_state[protocol]["discount_rate"],
                "credit_price_increase": protocol_state[protocol][
                    "credit_price_increase"
                ],
            }
            for protocol in protocols
        ]
    )

    left, right = st.columns([1, 2], gap="large")

    with left:
        st.subheader("Editable Inputs")
        st.caption("Adjust these assumptions for each selected protocol.")

        edited_df = st.data_editor(
            editable_df,
            key=f"{prefix}editable_financials_table",
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            disabled=["Protocol"],
            column_config={
                "Protocol": st.column_config.TextColumn("Protocol"),
                "planting_cost": st.column_config.NumberColumn(
                    "Initial Planting Cost / Acre",
                    min_value=0.0,
                    step=100,
                    format="$ %.2f",
                    help=H("credits.inputs.planting_cost"),
                ),
                "price_per_ert_initial": st.column_config.SelectboxColumn(
                    "Initial Price / CO2e",
                    options=PRICE_OPTIONS,
                    required=True,
                    help=H("credits.inputs.price_per_ert_initial"),
                ),
            },
        )

    with right:
        st.subheader("Fixed Financial Assumptions")
        st.caption("These values are shown for reference and are not editable.")

        st.dataframe(
            fixed_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Protocol": st.column_config.TextColumn("Protocol"),
                "num_plots": st.column_config.NumberColumn(
                    "Plots",
                    format="%d",
                    help=H("credits.inputs.num_plots"),
                ),
                "cost_per_cfi_plot": st.column_config.NumberColumn(
                    "Cost / CFI Plot",
                    format="$ %.2f",
                    help=H("credits.inputs.cost_per_cfi_plot"),
                ),
                "registry_fees": st.column_config.NumberColumn(
                    "Registry Fee",
                    format="$ %.2f",
                    help=H("credits.inputs.registry_fees"),
                ),
                "issuance_fee_per_ert": st.column_config.NumberColumn(
                    "Issuance Fee / CO2e",
                    format="$ %.4f",
                    help=H("credits.inputs.issuance_fee_per_ert"),
                ),
                "validation_cost": st.column_config.NumberColumn(
                    "Validation Cost",
                    format="$ %.2f",
                    help=H("credits.inputs.validation_cost"),
                ),
                "verification_cost": st.column_config.NumberColumn(
                    "Verification Cost",
                    format="$ %.2f",
                    help=H("credits.inputs.verification_cost"),
                ),
                "anticipated_inflation": st.column_config.NumberColumn(
                    "Anticipated Inflation",
                    format="%.2f",
                    help=H("credits.inputs.anticipated_inflation"),
                ),
                "discount_rate": st.column_config.NumberColumn(
                    "Discount Rate",
                    format="%.2f",
                    help=H("credits.inputs.discount_rate"),
                ),
                "credit_price_increase": st.column_config.NumberColumn(
                    "Credit Price Increase",
                    format="%.2f",
                    help=H("credits.inputs.credit_price_increase"),
                ),
            },
        )

    # Persist edited values by protocol while keeping fixed values unchanged.
    edited_by_protocol = {row["Protocol"]: row for _, row in edited_df.iterrows()}

    for protocol in protocols:
        row = edited_by_protocol[protocol]
        protocol_state[protocol]["planting_cost"] = float(row["planting_cost"])
        protocol_state[protocol]["price_per_ert_initial"] = float(
            row["price_per_ert_initial"]
        )

    st.session_state[table_state_key] = protocol_state

    # Keep legacy single-value keys populated for report/export compatibility.
    first_protocol = protocols[0]
    first_row = protocol_state[first_protocol]
    st.session_state[f"{prefix}num_plots"] = first_row["num_plots"]
    st.session_state[f"{prefix}cost_per_cfi_plot"] = first_row["cost_per_cfi_plot"]
    st.session_state[f"{prefix}price_per_ert_initial"] = first_row[
        "price_per_ert_initial"
    ]
    st.session_state[f"{prefix}credit_price_increase"] = first_row[
        "credit_price_increase"
    ]
    st.session_state[f"{prefix}registry_fees"] = first_row["registry_fees"]
    st.session_state[f"{prefix}validation_cost"] = first_row["validation_cost"]
    st.session_state[f"{prefix}verification_cost"] = first_row["verification_cost"]
    st.session_state[f"{prefix}issuance_fee_per_ert"] = first_row[
        "issuance_fee_per_ert"
    ]
    st.session_state[f"{prefix}anticipated_inflation"] = first_row[
        "anticipated_inflation"
    ]
    st.session_state[f"{prefix}discount_rate"] = first_row["discount_rate"]
    st.session_state[f"{prefix}planting_cost"] = first_row["planting_cost"]

    # NPV year-horizon selector — applies to every protocol in this run.
    npv_year = st.selectbox(
        "NPV Year Horizon",
        options=[10, 15, 20, 25, 30, 35, 40],
        index=6,
        key=f"{prefix}npv_year",
        help=H("credits.inputs.npv_year")
        or "Number of years from project start over which to discount cashflows for NPV.",
    )

    # constants constrained by modeling backend
    # year_start = 2026

    merged_df = st.session_state.get("merged_df")
    if merged_df is not None and not merged_df.empty and "Year" in merged_df.columns:
        year_start = int(pd.to_numeric(merged_df["Year"], errors="coerce").min())
    else:
        year_start = 2024

    years_advance = 35
    net_acres = st.session_state["net_acres"]

    return {
        protocol: {
            "net_acres": net_acres,
            "num_plots": values["num_plots"],
            "cost_per_cfi_plot": values["cost_per_cfi_plot"],
            "price_per_ert_initial": values["price_per_ert_initial"],
            "credit_price_increase": values["credit_price_increase"] / 100.0,
            "registry_fees": values["registry_fees"],
            "validation_cost": values["validation_cost"],
            "verification_cost": values["verification_cost"],
            "issuance_fee_per_ert": values["issuance_fee_per_ert"],
            "anticipated_inflation": values["anticipated_inflation"] / 100.0,
            "discount_rate": values["discount_rate"] / 100.0,
            "planting_cost": values["planting_cost"],
            "year_start": year_start,
            "years_advance": years_advance,
            "npv_year": int(npv_year),
        }
        for protocol, values in protocol_state.items()
    }


def credits_results(params: dict, prefix: str = "credits_") -> dict:
    """
    Execute the proforma model, summarize financial outputs, render revenue
    charts, generate summary tables, and provide formatted CSV export.
    """
    if "merged_df" not in st.session_state:
        st.error(
            "No carbon data found. Return to the CO2e Estimate section first."
        )
        st.stop()

    # Extract merged CO2e data per protocol
    df_ert_ac_all = st.session_state.merged_df[["Year", "CU", "Protocol"]].copy()
    df_ert_ac_all = df_ert_ac_all.replace([np.inf, -np.inf], np.nan)
    df_ert_ac_all = df_ert_ac_all.dropna(subset=["CU"])

    if not params:
        st.info(
            "No protocol financial assumptions available. Select at least one protocol."
        )
        return None

    proforma_frames = []
    summary_frames = []

    for protocol, protocol_params in params.items():
        df_protocol = df_ert_ac_all[df_ert_ac_all["Protocol"] == protocol].copy()
        if df_protocol.empty:
            continue

        payload = {
            "df_ert_ac": df_protocol.to_dict(orient="records"),
            "params": normalize_params(protocol_params),
        }

        json.dumps(payload)
        resp = requests.post(
            f"{API_BASE_URL}/proforma/compute",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

        proforma_frames.append(pd.DataFrame(resp.json()["proforma_rows"]))
        summary_frames.append(pd.DataFrame(resp.json()["summaries"]))

    if not proforma_frames:
        st.error("No protocol financial results were generated.")
        return None

    df_pf = pd.concat(proforma_frames, ignore_index=True)

    # Drop rows with NaN Net_Revenue to avoid chart issues
    df_pf = df_pf.dropna(subset=["Net_Revenue"])

    # Store proforma outputs for report generation
    st.session_state["proforma_df"] = df_pf.copy()

    # Summary metrics per protocol
    first_params = next(iter(params.values()))
    year_start = first_params["year_start"]
    year_stop = int(df_pf["Year"].max())

    summaries_df = pd.concat(summary_frames, ignore_index=True)

    # Chart alignment: start at base year (2026), then show every 5 years
    # include_years = _five_year_values(year_stop, start_year=CHART_BASE_YEAR)
    # df_chart = _prepend_zero_year_rows_by_group(
    #     df_pf,
    #     group_col="Protocol",
    #     value_col="Net_Revenue",
    #     base_year=CHART_BASE_YEAR,
    # )
    # df_chart, include_years = _filter_to_five_year_intervals(
    #     df_chart, year_col="Year", start_year=CHART_BASE_YEAR
    # )

    chart_start_year = int(pd.to_numeric(df_pf["Year"], errors="coerce").min())

    include_years = _five_year_values(year_stop, start_year=chart_start_year)

    df_chart, include_years = _filter_to_five_year_intervals(
        df_pf,
        year_col="Year",
        start_year=chart_start_year,
    )

    plot_df = df_chart.copy()

    toggle_nr = st.toggle(
        "Show Total Project Acreage", True, "toggle_nr", H("toggle.inputs.acres")
    )

    if toggle_nr:
        plot_df["Net_Revenue"] = plot_df["Net_Revenue"].round(-1)
    else:
        plot_df["Net_Revenue"] = (
            plot_df["Net_Revenue"] / first_params["net_acres"]
        ).round(-1)

    chart_title = "Total" if toggle_nr else "Per Acre"

    _plot_fading_line_chart(
        data=plot_df,
        x_col="Year",
        y_col="Net_Revenue",
        title=chart_title
        + f" Estimated Credits for {first_params['net_acres']:,} acres project",
        y_title=chart_title + " Net Revenue",
        include_years=include_years,
        series_col="Protocol",
        show_future_hatch=True,
    )

    summaries_df_display = summaries_df.copy()
    npv_year_label = int(summaries_df_display["npv_year"].iloc[0])
    npv_col = f"NPV (Year {npv_year_label})"
    npv_per_acre_col = f"NPV (Year {npv_year_label}) / Acre"

    summaries_df_display["Total Net Revenue, $"] = summaries_df_display[
        "total_net"
    ].map(lambda x: "${:,.0f}".format(round(x, -1)))
    summaries_df_display[npv_col] = summaries_df_display["npv_yr"].map(
        lambda x: "${:,.0f}".format(round(x, -1))
    )
    summaries_df_display[npv_per_acre_col] = summaries_df_display["npv_per_acre"].map(
        lambda x: "${:,.0f}".format(round(x, -1))
    )

    # Keep only the columns to show
    summaries_df_display = summaries_df_display[
        ["Protocol", "Total Net Revenue, $", npv_col, npv_per_acre_col]
    ]

    st.subheader(
        "Project Financials Summary",
        anchor=None,
        help=H("credits.summary_subheader"),
        divider=False,
        width="stretch",
    )
    st.table(summaries_df_display.set_index("Protocol"))

    # CSV download
    st.download_button(
        label="⬇️ Download Proforma table (CSV)",
        data=df_pf.to_csv(index=False).encode("utf-8"),
        file_name="credits_proforma.csv",
        mime="text/csv",
        use_container_width=True,
        help=H("credits.download_button"),
    )

    st.markdown(
        "Generate a comprehensive PDF report of your project analysis.",
        help=H("reports.generate_report_description"),
    )
    if st.button(
        "Generate Project Report",
        use_container_width=True,
        type="primary",
        help=H("reports.generate_report_button"),
    ):
        pdf_data = generate_report()
        if pdf_data:
            st.session_state["report_pdf_data"] = pdf_data
            st.success("Report generated successfully!")

    if "report_pdf_data" in st.session_state:
        st.download_button(
            label="Download Project Report (PDF)",
            data=st.session_state["report_pdf_data"],
            file_name="project_report.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="download_project_report_pdf",
        )


def generate_report():
    """
    Collect project data and request PDF report from the Quarto API.
    Returns PDF bytes on success, else None.
    """
    if "merged_df" not in st.session_state:
        st.error("Complete the financial analysis first.")
        return None
    if "carbon_df" not in st.session_state:
        st.error("No carbon data found. Return to the Carbon Estimates section first.")
        return None
    if "proforma_df" not in st.session_state:
        st.error(
            "No financial data found. Return to the Project Financials section first."
        )
        return None

    # Collect data for the report
    # Planting design - using static values for now (can be made dynamic later)
    planting_design = [
        {"column1": "Reforestation Strategy", "column2": "Mixed Species Planting"},
        {
            "column1": "Variant",
            "column2": st.session_state.get(
                "active_variant", st.session_state.get("selected_variant", "PN")
            ),
        },
        {
            "column1": "Location Name",
            "column2": st.session_state.get(
                "selected_varloc_name", "Olympic National Forest"
            ),
        },
        {
            "column1": "Location Code",
            "column2": st.session_state.get("selected_varloc_code", "609"),
        },
        {
            "column1": "Area, acres",
            "column2": str(st.session_state.get("net_acres", 10000)),
        },
        {
            "column1": "Survival Rate, %",
            "column2": st.session_state.get("survival", 70),
        },
        {"column1": "Site Index", "column2": str(st.session_state.get("si", 120))},
        {
            "column1": "Included Protocols",
            "column2": ", ".join(
                st.session_state.get("carbon_units_inputs", {}).get("protocols", [])
            ),
        },
        {"column1": "PCT Level", "column2": st.session_state.get("pct_level", "PCT0")},
        {
            "column1": "PCT Retention, %",
            "column2": str(st.session_state.get("pct_retention", "")),
        },
    ]

    # Species mix — built dynamically from variant species config
    species_mix = []
    species_mix.append(
        {"column1": "Species", "column2": "TPA#footnote[Trees per Acre]"}
    )
    report_variant = st.session_state.get(
        "active_variant", st.session_state.get("selected_variant", "PN")
    )
    sp_keys = _species_keys(report_variant)
    for i, key in enumerate(sp_keys):
        value = st.session_state.get(key, 0)
        if value > 0:
            label = _species_label(report_variant, i)
            species_mix.append({"column1": label, "column2": str(value)})

    # Financial options 1
    financial_options1 = [
        {
            "column1": "Number of Plots",
            "column2": str(st.session_state.get("credits_num_plots", 1)),
        },
        {
            "column1": "Cost per CFI Plot, $",
            "column2": str(st.session_state.get("credits_cost_per_cfi_plot", 1)),
        },
        {
            "column1": "Initial Price per CO2e, $",
            "column2": str(st.session_state.get("credits_price_per_ert_initial", 1.0)),
        },
        {
            "column1": "Credit Price Increase, %",
            "column2": str(st.session_state.get("credits_credit_price_increase", 0.0)),
        },
        {
            "column1": "Validation Cost, $",
            "column2": str(st.session_state.get("credits_validation_cost", 1)),
        },
        {
            "column1": "Verification Cost, $",
            "column2": str(st.session_state.get("credits_verification_cost", 1)),
        },
    ]

    # Financial options 2
    financial_options2 = [
        {
            "column1": "Registry Fees, $",
            "column2": str(st.session_state.get("credits_registry_fees", 1)),
        },
        {
            "column1": "Issuance Fee per CO2e, $",
            "column2": str(st.session_state.get("credits_issuance_fee_per_ert", 0.0)),
        },
        {
            "column1": "Anticipated Inflation, %",
            "column2": str(st.session_state.get("credits_anticipated_inflation", 0.0)),
        },
        {
            "column1": "Discount Rate, %",
            "column2": str(st.session_state.get("credits_discount_rate", 0.0)),
        },
        {
            "column1": "Initial Planting Cost per Acre, $",
            "column2": str(st.session_state.get("credits_planting_cost", 1000)),
        },
    ]

    # Carbon data from merged_df - map to expected column names
    carbon_df = st.session_state.merged_df[["Year", "CU", "Protocol"]].copy()
    carbon_df = carbon_df.rename(columns={"CU": "CO2e"})

    # Report chart alignment: derive cumulative onsite CO2 from carbon curve and
    # interpolate onto report years to avoid zero-fills from year-grid mismatch.
    report_years = sorted(carbon_df["Year"].dropna().astype(int).unique().tolist())
    carbon_curve = st.session_state.carbon_df[["Year", "ABLD_C"]].copy()
    carbon_curve = carbon_curve.dropna(subset=["Year", "ABLD_C"]).sort_values("Year")

    if not carbon_curve.empty and report_years:
        x = carbon_curve["Year"].astype(float).to_numpy()
        y = carbon_curve["ABLD_C"].astype(float).to_numpy() * 3.667
        xi = np.array(report_years, dtype=float)
        yi = np.interp(xi, x, y)
        carbon_scores = pd.DataFrame(
            {
                "Year": xi.astype(int),
                # Keep existing report column names for compatibility with report.ipynb
                "Annual CO2 per acre": yi,
                "Annual CO2": yi * st.session_state.get("net_acres", 0),
            }
        )
    else:
        carbon_scores = pd.DataFrame(
            {
                "Year": report_years,
                "Annual CO2 per acre": [0.0] * len(report_years),
                "Annual CO2": [0.0] * len(report_years),
            }
        )

    # Financials per protocol/year from proforma outputs
    proforma_df = st.session_state.proforma_df[
        ["Year", "Protocol", "Total_Revenue", "Total_Costs", "Net_Revenue"]
    ].copy()
    proforma_df = proforma_df.rename(
        columns={
            "Total_Revenue": "TotalRevenue",
            "Total_Costs": "TotalCosts",
            "Net_Revenue": "NetRevenue",
        }
    )

    carbon_df = carbon_df.merge(carbon_scores, on="Year", how="left")
    carbon_df = carbon_df.merge(proforma_df, on=["Year", "Protocol"], how="left")
    carbon_df[
        [
            "Annual CO2 per acre",
            "Annual CO2",
            "NetRevenue",
            "TotalCosts",
            "TotalRevenue",
        ]
    ] = carbon_df[
        [
            "Annual CO2 per acre",
            "Annual CO2",
            "NetRevenue",
            "TotalCosts",
            "TotalRevenue",
        ]
    ].fillna(0)

    carbon_data = carbon_df.to_dict(orient="records")

    # Use the concrete chosen variant (set by the Site Selection chooser), not the
    # base map variant, so the report's species/model match the run.
    selected_variant = st.session_state.get(
        "active_variant", st.session_state.get("selected_variant", "PN")
    )
    selected_varloc_name = st.session_state.get(
        "selected_varloc_name", "Olympic National Forest"
    )
    selected_varloc_code = st.session_state.get("selected_varloc_code", "609")

    payload = {
        "data": {
            "planting_design": planting_design,
            "species_mix": species_mix,
            "financial_options1": financial_options1,
            "financial_options2": financial_options2,
            "carbon": carbon_data,
            "selected_variant": selected_variant,
        }
    }

    try:
        with st.spinner("Generating report..."):
            resp = requests.post(
                f"{API_BASE_URL}/reports/generate",
                json=payload,
                timeout=300,  # Longer timeout for report generation
            )
            resp.raise_for_status()
            return resp.content

    except requests.RequestException as e:
        st.error(f"Failed to generate report: {str(e)}")
        return None


@st.fragment
def run_chart():
    """
    Top-level workflow controller. Runs planting sliders, carbon chart,
    CO2e chart, financial inputs, and financial results.
    """
    # Row 1: Planting sliders | Carbon chart
    with st.expander(label="Planting Parameters", expanded=True):
        col1, col2 = st.columns([1, 2], gap="large")
        with col1:
            planting_sliders()
        with col2:
            carbon_chart()

    # Row 2: Protocol selector -> acreage toggle -> Carbon units chart
    with st.expander(label="Carbon Estimates", expanded=True):
        if "carbon_df" not in st.session_state:
            st.error("No carbon data found. Adjust sliders above first.")
            st.stop()

        carbon_summary_df = st.session_state.carbon_df.copy()
        if "ABLD_C" in carbon_summary_df.columns:
            carbon_summary_df["CO2e"] = (
                pd.to_numeric(carbon_summary_df["ABLD_C"], errors="coerce") * 3.667
            )
            carbon_summary_df["CO2e"] = carbon_summary_df["CO2e"] * st.session_state.get(
                "net_acres", 1
            )
            # summary_df = _co2e_accumulation_summary(carbon_summary_df)
            summary_base_year = int(pd.to_numeric(carbon_summary_df["Year"], errors="coerce").min())
            summary_df = _co2e_accumulation_summary(
                carbon_summary_df,
                base_year=summary_base_year,
            )
            
            if not summary_df.empty:
                st.markdown("**CO2e Accumulation Summary**")
                cu_txt = '''
                CO₂e represents the carbon dioxide equivalent of the carbon sequestered by the project. The reported CO₂e values account for applicable deductions, including leakage (emissions that occur outside the project boundary as a result of project activities), buffer pool contributions for risk mitigation, and any other required adjustments under the relevant accounting framework. As a result, CO₂e reflects the net climate benefit attributable to the project after these considerations.
                '''
                st.markdown(cu_txt)
                st.caption(
                    "Modeled CO2e accumulation is interpolated from aboveground live biomass carbon "
                    "at 10-, 50-, and 100-year project horizons and shown in tons CO2e."
                )
                st.dataframe(summary_df, use_container_width=True, hide_index=True)
                # st.divider()

        # restore backup and init state for CO2e estimates
        _restore_backup(_carbon_units_keys(), backup_name="_carbon_units_backup")
        _init_carbon_units_state()

        # render widget using key only to enable restoring backups
        protocols = st.multiselect(
            "Select Protocol(s)",
            options=["ACR", "CAR", "VERRA", "GS", "ISO"],
            key="carbon_units_protocols",
            help=H("carbon.protocols_multiselect"),
        )

        st.session_state["carbon_units_inputs"] = {"protocols": protocols}

        # backup latest selections for CO2e estimates
        _backup_keys(_carbon_units_keys(), backup_name="_carbon_units_backup")

        carbon_units()

    # Row 3: Proforma inputs | Credits chart + summary
    with st.expander(label="Project Financials", expanded=True):
        proforma_params = credits_inputs(prefix="credits_")
        credits_results(proforma_params)

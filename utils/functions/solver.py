"""Solver (breakeven acreage) view: the team's "Solver" dashboard.

Where Planting Design fixes acreage and reports NPV, the Solver fixes the
planting design + financial assumptions and **solves for the net acreage that
drives NPV to a target** (default $0, the breakeven point). It then sweeps the
key financial levers to show how that breakeven acreage moves.

The breakeven solve is a closed-form linear inverse the model service computes
server-side (``solve`` directive on ``/scenario/run`` and ``/scenario/bulk``).
This module is the same pattern ``scripts/npv_benchmarks.py`` drives in batch,
surfaced as an interactive view.

Kept self-contained with its own ``solver_`` session-state prefix so it never
collides with Planting Design, and so it can later become a swappable
counterpart to that view. ``build_solve_scenario`` / ``build_grid_scenarios``
are pure (no Streamlit) and unit-tested.
"""

import itertools

import altair as alt
import pandas as pd
import requests
import streamlit as st

from model_service.main import _load_proforma_defaults, load_variant_presets
from utils.config import get_api_base_url, normalize_params
from utils.functions.helper import H
from utils.functions.plant_design import PROTOCOL_ORDER, _resolve_sub_variants
from utils.functions.slider_bounds import clamp, slider_bounds
from utils.functions.statefulness import (
    _backup_keys,
    _restore_backup,
    _species_codes,
    _species_label,
)

API_BASE_URL = get_api_base_url()

# Rate fields the UI shows in percent (6.0) but the API contract expects as a
# fraction (0.06). Mirrors plant_design.credits_inputs() / .credits_results().
PERCENT_FIELDS = ("credit_price_increase", "anticipated_inflation", "discount_rate")

# Financial fields swept as plain $/count values (no percent conversion).
_ABSOLUTE_LEVERS = ("price_per_ert_initial", "issuance_fee_per_ert")

# Levers the grid can sweep, with the preset value lists offered in the UI.
# discount_rate is entered/swept in PERCENT (server + builder convert to fraction).
LEVER_LABELS = {
    "discount_rate": "Discount Rate (%)",
    "price_per_ert_initial": "ERT Price ($)",
    "issuance_fee_per_ert": "Issuance Fee ($/ERT)",
    "npv_year": "NPV Horizon (yr)",
}
LEVER_OPTIONS = {
    "discount_rate": [6.0, 8.0, 10.0, 12.0],
    "price_per_ert_initial": [15.0, 25.0, 35.0, 45.0, 55.0],
    "issuance_fee_per_ert": [0.15, 0.30],
    "npv_year": [10, 15, 20, 25, 30, 35, 40],
}

# Financial levers accept typed custom values; npv_year stays a fixed picklist
# (the standard 5-year horizons), so it's the one lever without custom entry.
_CUSTOM_VALUE_LEVERS = ("discount_rate", "price_per_ert_initial", "issuance_fee_per_ert")

MAX_BULK_CELLS = 1000  # server cap on /scenario/bulk


# --------------------------------------------------------------------------- #
# Pure scenario builders (no Streamlit); unit-test targets.
# --------------------------------------------------------------------------- #
def _pct_to_fraction(financial_params_pct: dict) -> dict:
    """Convert percent-shaped rate fields (6.0) to fractions (0.06).

    Matches plant_design's percent->fraction step. The server also guards
    values >1, so this is belt-and-suspenders, but keeping it explicit means
    the payload we send is already in the API's native units.
    """
    out = dict(financial_params_pct)
    for field in PERCENT_FIELDS:
        if out.get(field) is not None:
            out[field] = float(out[field]) / 100.0
    return out


def build_solve_scenario(
    *,
    variant: str,
    loccode: str,
    pct_level: str,
    survival: float,
    si: float,
    species_tpa: list[float],
    protocol: str,
    financial_params_pct: dict,
    npv_year: int,
    target_npv: float,
) -> dict:
    """Assemble a ``/scenario/run`` payload that solves net_acres for an NPV target.

    ``financial_params_pct`` carries rate fields in percent form (as shown in
    the UI); they are converted to fractions here. ``net_acres`` is intentionally
    omitted; the solve directive computes it.
    """
    return {
        "variant": variant,
        "loccode": str(loccode),
        "survival": survival,
        "si": si,
        "species_tpa": [float(v) for v in species_tpa],
        "pct_level": pct_level,
        "protocols": [protocol],
        "financial_params": {
            protocol: normalize_params(_pct_to_fraction(financial_params_pct))
        },
        "npv_year": int(npv_year),
        "solve": {"variable": "net_acres", "target": "npv", "value": float(target_npv)},
    }


def build_tpa_breakeven_scenario(
    *,
    variant: str,
    loccode: str,
    pct_level: str,
    survival: float,
    si: float,
    species_tpa: list[float],
    protocol: str,
    financial_params_pct: dict,
    npv_year: int,
    target_npv: float,
    mode: str = "scalar",
    species: int | str | None = None,
    op: str = ">=",
    grid: dict | None = None,
    include_curve: bool = True,
) -> dict:
    """Assemble a ``/scenario/solve-tpa`` payload that sweeps planting density.

    ``species_tpa`` is the base mix the sweep scales/varies. ``mode`` is
    "scalar" | "species" | "per_species"; ``species`` (index or code) is
    required for mode="species". Rate fields are converted percent->fraction.
    """
    payload = {
        "variant": variant,
        "loccode": str(loccode),
        "survival": survival,
        "si": si,
        "species_tpa": [float(v) for v in species_tpa],
        "pct_level": pct_level,
        "protocols": [protocol],
        "financial_params": {
            protocol: normalize_params(_pct_to_fraction(financial_params_pct))
        },
        "npv_year": int(npv_year),
        "mode": mode,
        "op": op,
        "target_npv": float(target_npv),
        "include_curve": include_curve,
    }
    if species is not None:
        payload["species"] = species
    if grid is not None:
        payload["grid"] = grid
    return payload


def build_grid_scenarios(
    base_kwargs: dict,
    sweep: dict[str, list],
) -> tuple[list[dict], list[dict]]:
    """Cross-product the swept levers into solve scenarios.

    ``base_kwargs`` is the full kwargs dict for ``build_solve_scenario`` holding
    the single (non-swept) values. ``sweep`` maps lever name -> list of values;
    ``npv_year`` overrides the top-level horizon, the rest override
    ``financial_params_pct``. Returns ``(scenarios, cells)`` where ``cells[i]``
    records the swept values that produced ``scenarios[i]``.
    """
    levers = list(sweep.keys())
    value_lists = [sweep[lever] for lever in levers]

    scenarios: list[dict] = []
    cells: list[dict] = []
    for combo in itertools.product(*value_lists):
        kw = dict(base_kwargs)
        kw["financial_params_pct"] = dict(base_kwargs["financial_params_pct"])
        cell: dict = {}
        for lever, value in zip(levers, combo):
            cell[lever] = value
            if lever == "npv_year":
                kw["npv_year"] = value
            else:
                kw["financial_params_pct"][lever] = value
        scenarios.append(build_solve_scenario(**kw))
        cells.append(cell)
    return scenarios, cells


def _coerce_lever_values(lever: str, values: list) -> list:
    """Turn selected/typed lever values into sorted, de-duped numbers.

    Custom entries arrive as strings (st.multiselect accept_new_options);
    unparseable entries are dropped. npv_year is coerced to int, the rest float.
    """
    cast = int if lever == "npv_year" else float
    out = set()
    for v in values:
        try:
            out.add(cast(float(v)))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _breakeven_acres(result: dict | None) -> float | None:
    """Pull the solved net_acres out of a scenario result, or None."""
    if not result:
        return None
    acres = result.get("inputs", {}).get("net_acres")
    return float(acres) if acres is not None else None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #
def _run_scenario(scenario: dict) -> dict:
    """POST one solve scenario to /scenario/run. Raises on HTTP error."""
    resp = requests.post(f"{API_BASE_URL}/scenario/run", json=scenario, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _run_bulk(scenarios: list[dict]) -> tuple[list[dict | None], list[dict]]:
    """POST a batch of solve scenarios to /scenario/bulk.

    Returns ``(results, errors)`` aligned to the input order, matching the
    shape of ``aff_dash_client.run_many``.
    """
    resp = requests.post(
        f"{API_BASE_URL}/scenario/bulk",
        json={"scenarios": scenarios},
        timeout=120,
    )
    resp.raise_for_status()
    body = resp.json()
    return body["results"], body["errors"]


def _run_solve_tpa(scenario: dict) -> dict:
    """POST one TPA-breakeven scenario to /scenario/solve-tpa. Raises on HTTP error."""
    resp = requests.post(
        f"{API_BASE_URL}/scenario/solve-tpa", json=scenario, timeout=120
    )
    resp.raise_for_status()
    return resp.json()


def _detail_from_http_error(exc: requests.HTTPError) -> str:
    """Extract the FastAPI ``detail`` message from a 4xx response if present."""
    try:
        return exc.response.json().get("detail", str(exc))
    except Exception:
        return str(exc)


# --------------------------------------------------------------------------- #
# Input panel (own ``solver_`` session-state prefix)
# --------------------------------------------------------------------------- #
def _init_solver_planting_state(variant: str, preset: dict, sp_keys: list[str]):
    """Seed solver planting sliders when the variant changes; else leave intact."""
    if st.session_state.get("_last_solver_variant") == variant:
        return
    for key in ["solver_survival", "solver_si", *sp_keys]:
        st.session_state.pop(key, None)
    st.session_state["solver_survival"] = int(preset.get("survival", 70))
    st.session_state["solver_si"] = int(preset.get("si", 120))
    default_tpa = preset.get("default_tpa", [])
    for i, key in enumerate(sp_keys):
        st.session_state.setdefault(
            key, int(default_tpa[i]) if i < len(default_tpa) else 0
        )
    st.session_state["_last_solver_variant"] = variant


def _pct_selectbox(variant: str, loccode: str) -> str:
    """Render the PCT selector (own key); options come from the model registry."""
    _PCT_LABELS = {"PCT0": "None", "PCT1": "Light", "PCT2": "Moderate"}
    try:
        resp = requests.get(
            f"{API_BASE_URL}/models/pct-info",
            params={"variant": variant, "loccode": loccode},
            timeout=5,
        )
        resp.raise_for_status()
        pct_info = {p["pct_level"]: p.get("pct_retention") for p in resp.json()}
    except Exception:
        pct_info = {"PCT0": None, "PCT1": None, "PCT2": None}

    def _fmt(code: str) -> str:
        label = _PCT_LABELS.get(code, code)
        ret = pct_info.get(code)
        return f"{label} ({ret}%)" if ret is not None else label

    return st.selectbox(
        "Pre-commercial Thin (PCT)",
        options=sorted(pct_info.keys()),
        format_func=_fmt,
        key="solver_pct_level",
        help=H("planting.pct_level"),
    )


# (field, label, percent?, format, min, step) for the financial form, mirroring
# credits_inputs. Units live in the label; st.number_input's `format` only
# accepts a bare printf numeric spec (no "$" prefix, unlike data_editor columns).
_FIN_FIELDS = [
    ("planting_cost", "Planting Cost ($)", False, "%d", 0.0, 50.0),
    ("price_per_ert_initial", "ERT Price ($)", False, "%.2f", 0.0, 1.0),
    ("num_plots", "Plots", False, "%d", 1.0, 1.0),
    ("cost_per_cfi_plot", "Cost/CFI Plot ($)", False, "%.2f", 0.0, 1.0),
    ("registry_fees", "Registry Fee ($)", False, "%.2f", 0.0, 1.0),
    ("issuance_fee_per_ert", "Issuance Fee ($/ERT)", False, "%.4f", 0.0, 0.01),
    ("validation_cost", "Validation Cost ($)", False, "%d", 0.0, 1000.0),
    ("verification_cost", "Verification Cost ($)", False, "%d", 0.0, 1000.0),
    ("anticipated_inflation", "Inflation (%)", True, "%.2f", 0.0, 0.5),
    ("discount_rate", "Discount Rate (%)", True, "%.2f", 0.0, 0.5),
    ("credit_price_increase", "Credit Price Increase (%)", True, "%.2f", 0.0, 0.5),
]


def _financial_form() -> dict:
    """Render the single-protocol financial inputs (percent fields stay percent)."""
    defaults = _load_proforma_defaults()
    values: dict = {}
    cols = st.columns(3)
    for i, (field, label, _is_pct, fmt, minv, step) in enumerate(_FIN_FIELDS):
        key = f"solver_fin_{field}"
        # Match the value/min/step types to the format so an integer-formatted
        # ("%d") input doesn't get a float value (Streamlit warns on the mismatch).
        cast = int if fmt == "%d" else float
        if key not in st.session_state:
            st.session_state[key] = cast(defaults.get(field, 0))
        with cols[i % 3]:
            values[field] = st.number_input(
                label,
                min_value=cast(minv),
                step=cast(step),
                format=fmt,
                key=key,
                help=H(f"credits.inputs.{field}"),
            )
    return values


def _solver_inputs() -> dict | None:
    """Render the full Solver input panel; return the resolved inputs or None.

    Returns None (after showing guidance) if no site has been selected yet.
    """
    map_variant = st.session_state.get("selected_variant")
    if not map_variant:
        st.info("Select a site on the Site Selection map first, then return here.")
        return None

    varloc_code = st.session_state.get("selected_varloc_code", "609")
    varloc_name = st.session_state.get("selected_varloc_name", "")
    presets = load_variant_presets()

    # Sub-variant choice (own key so it doesn't drive Planting Design's variant).
    sub_variants = _resolve_sub_variants(map_variant, varloc_code)
    if len(sub_variants) > 1:
        variant = st.selectbox(
            "FVS Variant",
            options=sub_variants,
            key="solver_sub_variant",
            help=H("planting.variant_label"),
        )
    else:
        variant = sub_variants[0]
        st.markdown(f"**FVS Variant:** {variant}", help=H("planting.variant_label"))
    st.caption(f"Location: {varloc_name} ({varloc_code})")

    preset = presets.get(variant, presets.get("PN", {}))
    bounds = slider_bounds(preset)
    sp_keys = [f"solver_sp{i + 1}_tpa" for i in range(len(_species_codes(variant)))]
    _init_solver_planting_state(variant, preset, sp_keys)

    st.markdown("**Planting Design**")
    pct_level = _pct_selectbox(variant, varloc_code)
    st.session_state["solver_si"] = clamp(
        int(st.session_state.get("solver_si", bounds["si_min"])),
        bounds["si_min"],
        bounds["si_max"],
    )
    st.session_state["solver_survival"] = clamp(
        int(st.session_state.get("solver_survival", bounds["survival_min"])),
        bounds["survival_min"],
        bounds["survival_max"],
    )
    survival = st.slider(
        "Survival Percentage",
        bounds["survival_min"],
        bounds["survival_max"],
        key="solver_survival",
        help=H("planting.slider_survival"),
    )
    si = st.slider(
        "Site Index",
        bounds["si_min"],
        bounds["si_max"],
        key="solver_si",
        help=H("planting.slider_si"),
    )
    tpa_cap = preset.get("_tpa_cap", 435)
    st.markdown("Species Mix (TPA)", help=H("planting.species_mix_header"))
    for i, spk in enumerate(sp_keys):
        st.slider(_species_label(variant, i), 0, tpa_cap, key=spk)
    species_tpa = [int(st.session_state.get(k, 0)) for k in sp_keys]

    if sum(species_tpa) == 0:
        st.warning(
            "Set at least one species above 0 TPA. A planting design with no trees "
            "produces no carbon, so there is nothing to solve for."
        )
        return None

    st.markdown("**Carbon & Financials**")
    c1, c2, c3 = st.columns(3)
    with c1:
        protocol = st.selectbox(
            "Protocol",
            options=PROTOCOL_ORDER,
            key="solver_protocol",
            help=H("solver.protocol"),
        )
    with c2:
        npv_year = st.selectbox(
            "NPV Year Horizon",
            options=[10, 15, 20, 25, 30, 35, 40],
            index=6,
            key="solver_npv_year",
            help=H("credits.inputs.npv_year"),
        )
    with c3:
        target_npv = st.number_input(
            "Target NPV ($)",
            value=0.0,
            step=1000.0,
            key="solver_target_npv",
            help=H("solver.target_npv"),
        )
    financial_params_pct = _financial_form()

    return {
        "variant": variant,
        "loccode": varloc_code,
        "pct_level": pct_level,
        "survival": survival,
        "si": si,
        "species_tpa": species_tpa,
        "protocol": protocol,
        "financial_params_pct": financial_params_pct,
        "npv_year": int(npv_year),
        "target_npv": float(target_npv),
        "tpa_cap": int(tpa_cap),
    }


# --------------------------------------------------------------------------- #
# Apply-to-Planting-Design handoff
# --------------------------------------------------------------------------- #
def _planting_payload(inputs: dict, *, net_acres=None, species_tpa=None) -> dict:
    """Build the one-shot prefill dict consumed by plant_design/statefulness."""
    fin = inputs["financial_params_pct"]
    payload = {
        "variant": inputs["variant"],
        "pct_level": inputs["pct_level"],
        "survival": inputs["survival"],
        "si": inputs["si"],
        "species_tpa": list(species_tpa if species_tpa is not None else inputs["species_tpa"]),
        "protocol": inputs["protocol"],
        "npv_year": inputs["npv_year"],
        "planting_cost": fin["planting_cost"],
        "price_per_ert_initial": fin["price_per_ert_initial"],
    }
    if net_acres is not None:
        payload["net_acres"] = int(net_acres)
    return payload


def current_solver_prefill() -> dict | None:
    """Prefill payload from the solver's current inputs in session state (no
    solved value). Backs the header nav button, which renders before
    run_solver() — so values are read from state, not the input widgets."""
    map_variant = st.session_state.get("selected_variant")
    if not map_variant:
        return None
    varloc_code = st.session_state.get("selected_varloc_code", "609")
    sub_variants = _resolve_sub_variants(map_variant, varloc_code)
    variant = st.session_state.get("solver_sub_variant")
    if variant not in sub_variants:
        variant = sub_variants[0]
    sp_keys = [f"solver_sp{i + 1}_tpa" for i in range(len(_species_codes(variant)))]
    defaults = _load_proforma_defaults()
    return _planting_payload(
        {
            "variant": variant,
            "pct_level": st.session_state.get("solver_pct_level", "PCT0"),
            "survival": int(st.session_state.get("solver_survival", 70)),
            "si": int(st.session_state.get("solver_si", 120)),
            "species_tpa": [int(st.session_state.get(k, 0)) for k in sp_keys],
            "protocol": st.session_state.get("solver_protocol", PROTOCOL_ORDER[0]),
            "npv_year": int(st.session_state.get("solver_npv_year", 40)),
            "financial_params_pct": {
                "planting_cost": float(
                    st.session_state.get(
                        "solver_fin_planting_cost", defaults.get("planting_cost", 1000)
                    )
                ),
                "price_per_ert_initial": float(
                    st.session_state.get(
                        "solver_fin_price_per_ert_initial",
                        defaults.get("price_per_ert_initial", 25.0),
                    )
                ),
            },
        }
    )


def _apply_to_planting(payload: dict):
    """Button callback: stage the prefill and switch tabs (rerun follows the callback)."""
    st.session_state["_planting_prefill"] = payload
    st.session_state.active_tab = "Planting Design"


def _apply_button(key: str, payload: dict):
    st.button(
        "Apply to Planting Design",
        key=key,
        on_click=_apply_to_planting,
        kwargs={"payload": payload},
    )
    st.caption(
        "Prefills Planting Design with these inputs and the solved value. "
        "Fixed financial assumptions there come from protocol presets."
    )


# --------------------------------------------------------------------------- #
# Output sections
# --------------------------------------------------------------------------- #
# Keys in the resolved inputs dict that aren't scenario-builder arguments.
_INPUT_META_KEYS = ("tpa_cap",)


def _scenario_inputs(inputs: dict) -> dict:
    """Drop UI-only metadata (e.g. tpa_cap) before passing to the acreage builders."""
    return {k: v for k, v in inputs.items() if k not in _INPUT_META_KEYS}


def _render_headline(inputs: dict):
    """Solve breakeven acreage for the current inputs and show the headline."""
    scenario = build_solve_scenario(**_scenario_inputs(inputs))
    try:
        result = _run_scenario(scenario)
    except requests.HTTPError as exc:
        st.warning(
            f"Could not solve breakeven for these inputs: {_detail_from_http_error(exc)}"
        )
        return
    except requests.RequestException as exc:
        st.error(f"Model service unreachable: {exc}")
        return

    acres = _breakeven_acres(result)
    summary = (result.get("summaries") or [{}])[0]
    if acres is None:
        st.warning("No breakeven acreage returned for these inputs.")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Breakeven Net Acres", f"{acres:,.0f}")
    m2.metric(f"NPV @ yr {inputs['npv_year']}", f"$ {summary.get('npv_yr', 0):,.0f}")
    m3.metric("Total Net Revenue", f"$ {summary.get('total_net', 0):,.0f}")
    st.caption(
        f"Acreage at which {inputs['protocol']} NPV reaches "
        f"$ {inputs['target_npv']:,.0f} at the {inputs['npv_year']}-year horizon."
    )
    _apply_button(
        "solver_apply_acres",
        _planting_payload(inputs, net_acres=max(1, round(acres))),
    )


def _render_grid(inputs: dict):
    """Sweep up to two financial levers and show breakeven acreage per cell."""
    swept = st.multiselect(
        "Sweep levers (pick 1-2)",
        options=list(LEVER_LABELS.keys()),
        format_func=lambda k: LEVER_LABELS[k],
        default=["discount_rate", "price_per_ert_initial"],
        max_selections=2,
        key="solver_sweep_levers",
        help=H("solver.sweep_levers"),
    )
    if not swept:
        st.info("Pick one or two levers to sweep breakeven acreage across.")
        return

    sweep: dict[str, list] = {}
    val_cols = st.columns(len(swept))
    for col, lever in zip(val_cols, swept):
        custom = lever in _CUSTOM_VALUE_LEVERS
        with col:
            raw = st.multiselect(
                LEVER_LABELS[lever],
                options=LEVER_OPTIONS[lever],
                default=LEVER_OPTIONS[lever][:3],
                key=f"solver_sweep_vals_{lever}",
                accept_new_options=custom,
                help="Pick presets or type a custom value." if custom else None,
            )
        sweep[lever] = _coerce_lever_values(lever, raw)
    if any(not vals for vals in sweep.values()):
        st.info("Select at least one value for each swept lever.")
        return

    n_cells = 1
    for vals in sweep.values():
        n_cells *= len(vals)
    if n_cells > MAX_BULK_CELLS:
        st.error(
            f"Sweep would produce {n_cells:,} cells, over the {MAX_BULK_CELLS:,} limit. "
            "Reduce the number of swept values."
        )
        return

    base_kwargs = _scenario_inputs(inputs)
    scenarios, cells = build_grid_scenarios(base_kwargs, sweep)

    with st.spinner(f"Solving {n_cells} breakeven scenarios…"):
        try:
            results, errors = _run_bulk(scenarios)
        except requests.RequestException as exc:
            st.error(f"Bulk solve failed: {exc}")
            return

    rows = []
    for cell, result in zip(cells, results):
        row = {LEVER_LABELS[lever]: cell[lever] for lever in swept}
        row["Breakeven Acres"] = _breakeven_acres(result)
        rows.append(row)
    df = pd.DataFrame(rows)

    if errors:
        st.caption(
            f"{len(errors)} of {n_cells} scenarios could not be solved (shown blank)."
        )

    if len(swept) == 2:
        row_lever, col_lever = LEVER_LABELS[swept[0]], LEVER_LABELS[swept[1]]
        heat = (
            alt.Chart(df)
            .mark_rect()
            .encode(
                x=alt.X(f"{col_lever}:O", title=col_lever),
                y=alt.Y(f"{row_lever}:O", title=row_lever),
                color=alt.Color(
                    "Breakeven Acres:Q",
                    title="Breakeven Acres",
                    scale=alt.Scale(scheme="greens"),
                ),
                tooltip=list(df.columns),
            )
        )
        text = heat.mark_text(baseline="middle").encode(
            text=alt.Text("Breakeven Acres:Q", format=",.0f"),
        )
        st.altair_chart(heat + text, use_container_width=True, key="solver_acreage_heatmap")
    st.dataframe(
        df.style.format({"Breakeven Acres": "{:,.0f}"}, na_rep="-"),
        use_container_width=True,
        hide_index=True,
    )


_TPA_MODE_LABELS = {
    "Scalar (whole mix)": "scalar",
    "Single species": "species",
    "Per species": "per_species",
}


def _clamped_grid(mode: str, species_tpa: list, cap: float) -> dict:
    """Grid bounds that never sweep past the TPA cap (no model extrapolation).

    Scalar sweeps a multiplier, so the cap is applied to total TPA via the
    hi factor; species/per-species sweep TPA directly, so the cap clamps hi.
    """
    if mode == "scalar":
        total = sum(species_tpa)
        return {"hi_factor": min(4.0, cap / total) if total else 4.0}
    return {"max_value": float(cap)}


def _tpa_breakeven_curve_chart(res: dict, inputs: dict, x_label: str):
    """NPV-vs-density line with the target rule and breakeven floor marked."""
    curve = res.get("curve") or []
    if not curve:
        return None
    df = pd.DataFrame([{"x": p["x"], "npv": p["npv"]} for p in curve])
    line = (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("x:Q", title=x_label),
            y=alt.Y("npv:Q", title=f"Total NPV @ yr {inputs['npv_year']} ($)"),
            tooltip=[
                alt.Tooltip("x:Q", title=x_label, format=",.2f"),
                alt.Tooltip("npv:Q", title="NPV", format="$,.0f"),
            ],
        )
    )
    # Reference-line layers MUST reuse the same field names ("npv", "x") as the
    # line. Layering rules on differently-named fields makes Vega union mismatched
    # scale domains, which renders the chart blank intermittently.
    target_rule = (
        alt.Chart(pd.DataFrame({"npv": [float(inputs["target_npv"])]}))
        .mark_rule(color="firebrick", strokeDash=[4, 4])
        .encode(y="npv:Q")
    )
    layers = [line, target_rule]
    rng = res.get("range")
    if rng and not rng.get("lo_clipped"):
        floor = (
            alt.Chart(pd.DataFrame({"x": [float(rng["lo"])]}))
            .mark_rule(color="green")
            .encode(x="x:Q")
        )
        layers.append(floor)
    return alt.layer(*layers).properties(height=320)


def _render_tpa_per_species(resp: dict):
    """Table of the minimum breakeven TPA per species (others held fixed)."""
    rows = []
    for res in resp["results"]:
        rng = res.get("range")
        code = res.get("species_code") or f"SP{(res.get('species_index') or 0) + 1}"
        if rng is None:
            breakeven, note = None, "never breaks even up to cap"
        elif rng.get("lo_clipped"):
            breakeven, note = None, "non-binding"
        else:
            breakeven, note = rng["lo"], ""
        rows.append({"Species": code, "Breakeven (TPA)": breakeven, "Note": note})
    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.format({"Breakeven (TPA)": "{:,.0f}"}, na_rep="-"),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Minimum TPA per species to break even, holding the others fixed.")


def _scalar_breakdown_df(variant: str, base_tpa: list, k: float):
    """Per-species and total TPA at the scalar breakeven density (k x base mix)."""
    rows = [
        {"Species": _species_label(variant, i), "Breakeven (TPA)": k * b}
        for i, b in enumerate(base_tpa)
    ]
    rows.append({"Species": "Total", "Breakeven (TPA)": k * sum(base_tpa)})
    return pd.DataFrame(rows)


def _render_tpa_breakeven(inputs: dict):
    """Solve for the breakeven planting density (trees per acre)."""
    variant = inputs["variant"]
    cap = inputs.get("tpa_cap", 435)
    mode = _TPA_MODE_LABELS[
        st.radio(
            "Density sweep",
            list(_TPA_MODE_LABELS.keys()),
            horizontal=True,
            key="solver_tpa_mode",
            help=H("solver.tpa_mode"),
        )
    ]

    species_sel = None
    if mode == "species":
        codes = _species_codes(variant)
        species_sel = st.selectbox(
            "Species",
            options=list(range(len(codes))),
            format_func=lambda i: _species_label(variant, i),
            key="solver_tpa_species",
            help=H("solver.tpa_species"),
        )

    scenario = build_tpa_breakeven_scenario(
        variant=variant,
        loccode=inputs["loccode"],
        pct_level=inputs["pct_level"],
        survival=inputs["survival"],
        si=inputs["si"],
        species_tpa=inputs["species_tpa"],
        protocol=inputs["protocol"],
        financial_params_pct=inputs["financial_params_pct"],
        npv_year=inputs["npv_year"],
        target_npv=inputs["target_npv"],
        mode=mode,
        species=species_sel,
        op=">=",
        grid=_clamped_grid(mode, inputs["species_tpa"], cap),
        include_curve=(mode != "per_species"),
    )
    try:
        resp = _run_solve_tpa(scenario)
    except requests.HTTPError as exc:
        st.warning(f"Could not solve breakeven density: {_detail_from_http_error(exc)}")
        return
    except requests.RequestException as exc:
        st.error(f"Model service unreachable: {exc}")
        return

    st.caption(
        f"Breakeven density: where {inputs['protocol']} NPV reaches "
        f"$ {inputs['target_npv']:,.0f} at year {inputs['npv_year']}, "
        f"swept up to the {int(cap)} TPA cap. NPV rises with density, so this is "
        "the minimum to break even."
    )

    if mode == "per_species":
        _render_tpa_per_species(resp)
        return

    res = resp["results"][0]
    rng = res.get("range")
    is_scalar = res["variable"] == "k"
    code = None if is_scalar else (res.get("species_code") or f"SP{(res.get('species_index') or 0) + 1}")
    x_label = "Density multiplier (× current mix)" if is_scalar else f"{code} trees/acre"

    if rng is None:
        st.warning(
            f"NPV never reaches the target at any density up to the {int(cap)} TPA cap. "
            "Try a lower target or different financials."
        )
    elif is_scalar and rng.get("lo_clipped"):
        st.success(
            f"Profitable at every density up to the {int(cap)} TPA cap; "
            "breakeven is below this range."
        )
    elif is_scalar:
        total_base = sum(inputs["species_tpa"])
        st.metric("Breakeven density", f"{rng['lo'] * total_base:,.0f} total TPA")
        st.caption(f"= {rng['lo']:.2f}× your current mix.")
        breakdown = _scalar_breakdown_df(inputs["variant"], inputs["species_tpa"], rng["lo"])
        st.dataframe(
            breakdown.style.format({"Breakeven (TPA)": "{:,.0f}"}),
            use_container_width=True,
            hide_index=True,
        )
        _apply_button(
            "solver_apply_tpa_scalar",
            _planting_payload(
                inputs,
                species_tpa=[round(rng["lo"] * b) for b in inputs["species_tpa"]],
            ),
        )
    elif rng.get("lo_clipped"):
        st.success(f"{code} is non-binding; profitable across its full range up to the cap.")
    else:
        st.metric(f"{code} breakeven", f"{rng['lo']:,.0f} TPA")
        solved_mix = list(inputs["species_tpa"])
        solved_mix[species_sel] = round(rng["lo"])
        _apply_button(
            "solver_apply_tpa_species",
            _planting_payload(inputs, species_tpa=solved_mix),
        )

    # Always render the curve (a stable key keeps Streamlit from dropping it when
    # the elements above it change between reruns).
    chart = _tpa_breakeven_curve_chart(res, inputs, x_label)
    if chart is not None:
        st.altair_chart(chart, use_container_width=True, key="solver_tpa_curve")


def _solver_state_keys() -> list[str]:
    """Solver input keys to back up across tab switches. Widget-only keys
    (buttons, charts) must stay out — Streamlit forbids restoring them."""
    keys = [
        "solver_sub_variant",
        "solver_pct_level",
        "solver_survival",
        "solver_si",
        "solver_protocol",
        "solver_npv_year",
        "solver_target_npv",
        "solver_variable",
        "solver_tpa_mode",
        "solver_tpa_species",
        "solver_sweep_levers",
    ]
    keys += [f"solver_fin_{field}" for field, *_ in _FIN_FIELDS]
    keys += [f"solver_sweep_vals_{lever}" for lever in LEVER_LABELS]
    keys += [
        k for k in st.session_state if k.startswith("solver_sp") and k.endswith("_tpa")
    ]
    return keys


def run_solver():
    """Top-level Solver view entry point (mirrors plant_design.run_chart())."""
    # Streamlit drops solver_* widget state whenever this view isn't rendered
    # (other tab active), and the variant sentinel blocks re-seeding — restore
    # from the backup taken at the end of the last render.
    _restore_backup(
        list(st.session_state.get("_solver_backup", {})), backup_name="_solver_backup"
    )

    inputs = _solver_inputs()
    if inputs is None:
        return

    choice = st.radio(
        "Solve for",
        ["Breakeven Acreage", "Breakeven Trees-per-Acre"],
        horizontal=True,
        key="solver_variable",
        help=H("solver.variable_toggle"),
    )

    if choice == "Breakeven Acreage":
        with st.expander("Breakeven Acreage", expanded=True):
            _render_headline(inputs)
        with st.expander("Sensitivity (Breakeven vs. Financial Levers)", expanded=True):
            _render_grid(inputs)
    else:
        with st.expander("Breakeven Trees-per-Acre", expanded=True):
            _render_tpa_breakeven(inputs)

    _backup_keys(_solver_state_keys(), backup_name="_solver_backup")

import streamlit as st           
import json                       
import pandas as pd               
import numpy as np                 
import numpy_financial as npf     
from pathlib import Path           
from scipy.interpolate import make_interp_spline  
import altair as alt  
import requests
import os
from urllib.parse import urlparse

from utils.functions.helper import  H
from utils.functions.statefulness import  _carbon_units_keys, _init_planting_state, _init_carbon_units_state, _backup_keys, _restore_backup, _species_keys, _species_label
from utils.config import get_api_base_url, normalize_params

from model_service.main import load_variant_presets, load_variant_species, _load_proforma_defaults


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
    vs = load_variant_species()

    # Find all sub-variant keys that could match this map variant
    candidate_keys = []
    if map_variant in vs and isinstance(vs[map_variant], list):
        candidate_keys = [map_variant]
    else:
        candidate_keys = sorted(k for k, v in vs.items() if isinstance(v, list) and k.startswith(map_variant + "_"))

    if not candidate_keys:
        candidate_keys = [map_variant]

    # Filter to sub-variants that have models for this loccode
    available = [
        k for k in candidate_keys
        if any(m["variant"] == k and m["loccode"] == loccode for m in registry)
    ]

    return available if available else candidate_keys

API_BASE_URL = get_api_base_url()

CHART_BASE_YEAR = 2024


def _five_year_values(max_year: int, start_year: int = CHART_BASE_YEAR) -> list[int]:
    """Return 5-year x-axis values from start_year through max_year (inclusive range)."""
    if max_year < start_year:
        return [start_year]
    return list(range(start_year, int(max_year) + 1, 5))


def _prepend_zero_year_row(
    df: pd.DataFrame,
    value_col: str,
    year_col: str = "Year",
    base_year: int = CHART_BASE_YEAR,
) -> pd.DataFrame:
    """Prepend a synthetic base-year row (value=0) for single-series charts."""
    out = df.copy()
    out = out[out[year_col] != base_year]
    zero_row = {col: np.nan for col in out.columns}
    zero_row[year_col] = base_year
    zero_row[value_col] = 0.0
    out = pd.concat([pd.DataFrame([zero_row]), out], ignore_index=True)
    return out.sort_values(year_col).reset_index(drop=True)


def _prepend_zero_year_rows_by_group(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    year_col: str = "Year",
    base_year: int = CHART_BASE_YEAR,
) -> pd.DataFrame:
    """Prepend a synthetic base-year row (value=0) for each group in multi-series charts."""
    out = df.copy()
    out = out[out[year_col] != base_year]
    groups = out[group_col].dropna().unique().tolist()

    if not groups:
        return out

    zero_rows = pd.DataFrame(
        [{year_col: base_year, group_col: g, value_col: 0.0} for g in groups]
    )
    out = pd.concat([zero_rows, out], ignore_index=True)
    return out.sort_values([group_col, year_col]).reset_index(drop=True)

def _credits_keys(prefix: str = "credits_") -> list[str]:
    """
    Return all proforma input keys (prefixed) that should persist for the Credits section.
    Uses the JSON defaults as the source for which keys exist.
    """
    defaults = _load_proforma_defaults()
    return [prefix + k for k in defaults.keys()]

def _seed_defaults(prefix: str = "credits_"):
    """
    Seed Streamlit session state with default financial and credit parameters
    based on proforma defaults. Only sets missing keys.
    """
    defaults = _load_proforma_defaults()
    for k, v in defaults.items():
        st.session_state.setdefault(prefix + k, v)

def planting_sliders():
    """
    Render all planting-related Streamlit sliders. Restores saved state, renders species sliders, computes species mix values, and stores
    all planting parameters in session state. 
    """
    presets = load_variant_presets()
    map_variant = st.session_state.get("selected_variant", "PN")
    varloc_name = st.session_state.get("selected_varloc_name", "Olympic National Forest")
    varloc_code = st.session_state.get("selected_varloc_code", "609")

    # Resolve sub-variants based on what models exist for this loccode
    sub_variants = _resolve_sub_variants(map_variant, varloc_code)
    if len(sub_variants) > 1:
        variant = st.selectbox(
            "Sub-variant",
            options=sub_variants,
            index=0,
            key="selected_sub_variant",
        )
    else:
        variant = sub_variants[0]
    st.session_state["active_variant"] = variant

    if variant not in presets:
        st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
    preset = presets.get(variant, presets.get("PN", {}))

    st.markdown(f"**FVS Variant:** {map_variant}", unsafe_allow_html=False, help=H("planting.variant_label"), width="stretch")
    st.markdown(f"**FVS Location Name:** {varloc_name}", unsafe_allow_html=False, help=H("planting.varloc_label"), width="stretch")
    st.markdown(f"**FVS Location Code:** {varloc_code}", unsafe_allow_html=False, help=H("planting.varcode_label"), width="stretch")

    sp_keys = _species_keys(variant)

    # restore any missing keys from previous interaction with page
    _restore_backup(["survival", "si", "net_acres", *sp_keys])

    # Initialize presets ONLY if the variant truly changed
    _init_planting_state(variant, preset)

    st.number_input(
        "Net Acres:",
        min_value=1,
        step=100,
        key="net_acres",
        help=H("number.inputs.acres")
    )
    st.caption(f"{int(st.session_state.get('net_acres', 0)):,} acres")
    st.slider("Survival Percentage", 40, 90, key="survival", help=H("planting.slider_survival"))
    st.slider("Site Index", 96, 137, key="si", help=H("planting.slider_si"))

    st.markdown("Species Mix (TPA)", unsafe_allow_html=False, help=H("planting.species_mix_header"), width="stretch")
    tpa_cap = preset.get("_tpa_cap", 435)
    for i, spk in enumerate(sp_keys):
        st.slider(_species_label(variant, i), 0, tpa_cap, key=spk)

    # Summary
    total_tpa = sum(int(st.session_state.get(k, 0)) for k in sp_keys)
    st.markdown(f"**Total TPA:** {total_tpa}", unsafe_allow_html=False, help=H("planting.total_tpa_label"), width="stretch")
    if total_tpa > tpa_cap:
        st.warning(f"Total initial TPA exceeds {tpa_cap} and may present an unrealistic scenario. Consider adjusting sliders.")

    # Store as positional list for the API
    st.session_state["species_tpa"] = [int(st.session_state.get(k, 0)) for k in sp_keys]

    # Backup latest values so they're available if user navigates away and back
    _backup_keys(["survival", "si", "net_acres", *sp_keys])

def carbon_chart():
    if not all(k in st.session_state for k in ["survival", "si", "net_acres", "species_tpa"]):
        st.info("Adjust Planting Design sliders to see the carbon output.")
        return

    species_tpa = st.session_state["species_tpa"]
    if not species_tpa or all(v == 0 for v in species_tpa):
        st.info("Set at least one species TPA value.")
        return

    variant = st.session_state.get("active_variant", st.session_state.get("selected_variant", "PN"))
    loccode = st.session_state.get("selected_varloc_code", "609")

    pct_level = st.selectbox(
        "Pre-commercial Thin (PCT)",
        options=["PCT0", "PCT1", "PCT2"],
        format_func=lambda x: {"PCT0": "None", "PCT1": "Light", "PCT2": "Moderate"}[x],
        key="pct_level",
        help=H("planting.pct_level"),
    )

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
        "ABLD_C":  {"label": "Aboveground live biomass carbon", "unit": "tons",       "unit_project": "tons",     "scales": True},
        "BA":      {"label": "Basal area",                      "unit": "sq ft/acre", "unit_project": "sq ft",    "scales": True},
        "QMD":     {"label": "Quadratic mean diameter",         "unit": "inches",     "unit_project": "inches",   "scales": False},
        "SDI":     {"label": "Stand density index",             "unit": "index",      "unit_project": "index",    "scales": False},
        "TCuFt":   {"label": "Total cubic volume",             "unit": "cu ft/acre", "unit_project": "cu ft",    "scales": True},
        "MCuFt":   {"label": "Merchantable cubic volume",      "unit": "cu ft/acre", "unit_project": "cu ft",    "scales": True},
        "Tpa":     {"label": "Trees per acre",                  "unit": "trees/acre", "unit_project": "trees",    "scales": True},
    }

    available = {col: METRIC_DEFS[col] for col in METRIC_DEFS if col in df.columns}

    toggle_oc = st.toggle('Show Project Acreage', True, 'toggle_oc', H("toggle.inputs.acres"))
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
            unit = meta["unit_project"] if (toggle_oc and meta["scales"]) else meta["unit"]
            df_m = _prepend_zero_year_row(plot_df[["Year", col]].copy(), value_col=col, base_year=CHART_BASE_YEAR)
            inc = _five_year_values(df_m["Year"].max(), start_year=CHART_BASE_YEAR)
            df_m = df_m[df_m["Year"].isin(inc)]
            chart = (
                alt.Chart(df_m).mark_line(point=True).encode(
                    x=alt.X("Year:Q", title="Year", axis=alt.Axis(values=inc, format="d", labelAngle=30),
                            scale=alt.Scale(domain=[CHART_BASE_YEAR, max(inc)])),
                    y=alt.Y(f"{col}:Q", title=f"{label} ({unit})"),
                    tooltip=["Year", col],
                ).properties(title=label, height=350)
            )
            st.altair_chart(chart, use_container_width=True)
            # QMD disclaimer per Dave: 2029 values are unreliable
            if col == "QMD":
                st.caption("Note: QMD predictions at year 2029 are unreliable and should be interpreted with caution.")

        _render_metric(primary_label)
        st.divider()
        _render_metric(secondary_label)
    else:
        # Coefficient fallback: single ABLD_C chart
        chart_title = "Onsite Carbon (tons/project)" if toggle_oc else "Onsite Carbon (tons/acre)"
        plot_df = _prepend_zero_year_row(plot_df, value_col="ABLD_C", base_year=CHART_BASE_YEAR)
        include_years = _five_year_values(plot_df["Year"].max(), start_year=CHART_BASE_YEAR)
        plot_df = plot_df[plot_df["Year"].isin(include_years)]

        line = alt.Chart(plot_df).mark_line(point=True).encode(
            x=alt.X('Year:Q', title='Year',
                     axis=alt.Axis(values=include_years, format='d', labelAngle=30),
                     scale=alt.Scale(domain=[CHART_BASE_YEAR, max(include_years)])),
            y=alt.Y('ABLD_C:Q', title=chart_title),
            tooltip=['Year', 'ABLD_C']
        ).properties(title="Cumulative " + chart_title, width=600, height=400)
        st.altair_chart(line, use_container_width=True)

    # Summary output
    if "ABLD_C" in plot_df.columns:
        st.success(f"Final Carbon Output (year {int(plot_df['Year'].max())}): {plot_df['ABLD_C'].iloc[-1]:,.2f}")

    if model_source == "coefficients":
        st.caption("Using coefficient-based estimates. Add FVS model files for richer predictions.")

def carbon_units():
        if "carbon_df" not in st.session_state:
            st.error("No carbon data found.")
            st.stop()

        protocols = st.session_state.get(
            "carbon_units_inputs", {}
        ).get("protocols", [])

        if not protocols:
            st.info("Select at least one protocol.")
            return

        payload = {
            "carbon_rows": st.session_state.carbon_df[
                ["Year", "ABLD_C"]
            ].to_dict(orient="records"),
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

        toggle_ce = st.toggle('Show Project Acreage', True, 'toggle_ce', H("toggle.inputs.acres"))

        # Adjust chart values based on toggle
        plot_df = final_df.copy()
        if toggle_ce:
            plot_df['CU'] = plot_df['CU'] * st.session_state["net_acres"]

        chart_title = "(tons/project)" if toggle_ce else "(tons/acre)"

        plot_df = _prepend_zero_year_rows_by_group(
            plot_df,
            group_col='Protocol',
            value_col='CU',
            base_year=CHART_BASE_YEAR,
        )
        include_years = _five_year_values(plot_df['Year'].max(), start_year=CHART_BASE_YEAR)
        plot_df = plot_df[plot_df['Year'].isin(include_years)]

        CU_chart = alt.Chart(plot_df).mark_line(point=True).encode(
            x=alt.X(
                'Year:Q',
                title='Year',
                axis=alt.Axis(values=include_years, format='d', labelAngle=30),
                scale=alt.Scale(domain=[CHART_BASE_YEAR, max(include_years)])
            ),
            y=alt.Y('CU:Q', title='CUs ' + chart_title),
            color='Protocol:N',
            tooltip=['Year', 'CU', 'Protocol']
        ).properties(
            title='Annual CU Estimates ' + chart_title,
            width=600,
            height=400
        ).configure_axis(grid=True, gridOpacity=0.3)

        st.altair_chart(CU_chart, use_container_width=True)

def credits_inputs(prefix: str = "credits_") -> dict:
    """
    Render per-protocol Proforma inputs as an editable table and return
    a mapping of protocol -> typed parameter dictionary.
    """
    protocols = st.session_state.get("carbon_units_inputs", {}).get("protocols", [])

    if not protocols:
        st.info("Select at least one protocol in Carbon Estimates to edit project financial assumptions.")
        return {}

    defaults = _load_proforma_defaults()
    table_state_key = f"{prefix}protocol_params"
    protocol_state = st.session_state.get(table_state_key, {})

    # Keep values only for selected protocols, and seed defaults for any newly selected ones.
    protocol_state = {p: protocol_state[p] for p in protocols if p in protocol_state}
    for protocol in protocols:
        if protocol not in protocol_state:
            protocol_state[protocol] = {
                "num_plots": defaults.get("num_plots", 250),
                "cost_per_cfi_plot": defaults.get("cost_per_cfi_plot", 150),
                "price_per_ert_initial": defaults.get("price_per_ert_initial", 25.0),
                "credit_price_increase": defaults.get("credit_price_increase", 2.0),
                "registry_fees": defaults.get("registry_fees", 500),
                "validation_cost": defaults.get("validation_cost", 45000),
                "verification_cost": defaults.get("verification_cost", 25000),
                "issuance_fee_per_ert": defaults.get("issuance_fee_per_ert", 0.15),
                "anticipated_inflation": defaults.get("anticipated_inflation", 0.0),
                "discount_rate": defaults.get("discount_rate", 6.0),
                "planting_cost": defaults.get("planting_cost", 1000),
            }

    st.session_state[table_state_key] = protocol_state
    st.markdown("Financial Options by Protocol", help=H("credits.expander_subheader"))

    table_df = pd.DataFrame(
        [
            {
                "Protocol": protocol,
                "num_plots": protocol_state[protocol]["num_plots"],
                "cost_per_cfi_plot": protocol_state[protocol]["cost_per_cfi_plot"],
                "registry_fees": protocol_state[protocol]["registry_fees"],
                "issuance_fee_per_ert": protocol_state[protocol]["issuance_fee_per_ert"],
                "validation_cost": protocol_state[protocol]["validation_cost"],
                "verification_cost": protocol_state[protocol]["verification_cost"],
                "anticipated_inflation": protocol_state[protocol]["anticipated_inflation"],
                "discount_rate": protocol_state[protocol]["discount_rate"],
                "price_per_ert_initial": protocol_state[protocol]["price_per_ert_initial"],
                "credit_price_increase": protocol_state[protocol]["credit_price_increase"],
                "planting_cost": protocol_state[protocol]["planting_cost"],
            }
            for protocol in protocols
        ]
    )

    edited_df = st.data_editor(
        table_df,
        key=f"{prefix}financials_table",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["Protocol"],
        column_config={
            "Protocol": st.column_config.TextColumn("Protocol"),
            "num_plots": st.column_config.NumberColumn("Plots", min_value=1, step=1, format="%d"),
            "cost_per_cfi_plot": st.column_config.NumberColumn("Cost/CFI Plot", min_value=1, step=1, format="$ %.2f"),
            "registry_fees": st.column_config.NumberColumn("Registry Fee", min_value=0.0, step=1, format="$ %.2f"),
            "issuance_fee_per_ert": st.column_config.NumberColumn("Issuance Fee", min_value=0.0, step=0.01, format="$ %.4f"),
            "validation_cost": st.column_config.NumberColumn("Validation Cost", min_value=0.0, step=1, format="$ %.2f"),
            "verification_cost": st.column_config.NumberColumn("Verification Cost", min_value=0.0, step=1, format="$ %.2f"),
            "anticipated_inflation": st.column_config.NumberColumn("Anticipated Inflation", min_value=0.0, step=0.1, format="%.2f"),
            "discount_rate": st.column_config.NumberColumn("Discount Rate", min_value=0.0, step=0.1, format="%.2f"),
            "price_per_ert_initial": st.column_config.NumberColumn("Initial Price / CU", min_value=0.0, step=0.1, format="$ %.2f"),
            "credit_price_increase": st.column_config.NumberColumn("Credit Price Increase", min_value=0.0, step=0.1, format="%.2f"),
            "planting_cost": st.column_config.NumberColumn("Initial Planting Cost", min_value=0.0, step=100, format="$ %.2f"),
        },
    )

    # Persist edited values by protocol.
    protocol_state = {
        row["Protocol"]: {
            "num_plots": int(row["num_plots"]),
            "cost_per_cfi_plot": float(row["cost_per_cfi_plot"]),
            "price_per_ert_initial": float(row["price_per_ert_initial"]),
            "credit_price_increase": float(row["credit_price_increase"]),
            "registry_fees": float(row["registry_fees"]),
            "validation_cost": float(row["validation_cost"]),
            "verification_cost": float(row["verification_cost"]),
            "issuance_fee_per_ert": float(row["issuance_fee_per_ert"]),
            "anticipated_inflation": float(row["anticipated_inflation"]),
            "discount_rate": float(row["discount_rate"]),
            "planting_cost": float(row["planting_cost"]),
        }
        for _, row in edited_df.iterrows()
    }
    st.session_state[table_state_key] = protocol_state

    # Keep legacy single-value keys populated for report/export compatibility.
    first_protocol = protocols[0]
    first_row = protocol_state[first_protocol]
    st.session_state[f"{prefix}num_plots"] = first_row["num_plots"]
    st.session_state[f"{prefix}cost_per_cfi_plot"] = first_row["cost_per_cfi_plot"]
    st.session_state[f"{prefix}price_per_ert_initial"] = first_row["price_per_ert_initial"]
    st.session_state[f"{prefix}credit_price_increase"] = first_row["credit_price_increase"]
    st.session_state[f"{prefix}registry_fees"] = first_row["registry_fees"]
    st.session_state[f"{prefix}validation_cost"] = first_row["validation_cost"]
    st.session_state[f"{prefix}verification_cost"] = first_row["verification_cost"]
    st.session_state[f"{prefix}issuance_fee_per_ert"] = first_row["issuance_fee_per_ert"]
    st.session_state[f"{prefix}anticipated_inflation"] = first_row["anticipated_inflation"]
    st.session_state[f"{prefix}discount_rate"] = first_row["discount_rate"]
    st.session_state[f"{prefix}planting_cost"] = first_row["planting_cost"]

    # constants (constrained by modeling backend)
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
        }
        for protocol, values in protocol_state.items()
    }

def credits_results(params: dict, prefix: str = "credits_") -> dict:
    """
    Execute the proforma model, summarize financial outputs, render revenue
    charts, generate summary tables, and provide formatted CSV export.
    """
    if "merged_df" not in st.session_state:
        st.error("No carbon data found. Return to the Carbon Units Estimate section first.")
        st.stop()

    # Extract merged CU data per protocol
    df_ert_ac_all = st.session_state.merged_df[['Year', 'CU', 'Protocol']].copy()
    df_ert_ac_all = df_ert_ac_all.replace([np.inf, -np.inf], np.nan)
    df_ert_ac_all = df_ert_ac_all.dropna(subset=['CU'])

    if not params:
        st.info("No protocol financial assumptions available. Select at least one protocol.")
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
    df_pf = df_pf.dropna(subset=['Net_Revenue'])

    # Store proforma outputs for report generation
    st.session_state["proforma_df"] = df_pf.copy()

    # Summary metrics per protocol
    first_params = next(iter(params.values()))
    year_start = first_params['year_start']
    year_stop = int(df_pf['Year'].max())

    summaries_df = pd.concat(summary_frames, ignore_index=True)

    # Chart alignment: start at 2024 (0), then show every 5 years
    include_years = _five_year_values(year_stop, start_year=CHART_BASE_YEAR)
    df_chart = _prepend_zero_year_rows_by_group(
        df_pf,
        group_col='Protocol',
        value_col='Net_Revenue',
        base_year=CHART_BASE_YEAR,
    )
    df_chart = df_chart[df_chart['Year'].isin(include_years)]

    plot_df = df_chart.copy()

    toggle_nr = st.toggle('Show Project Acreage', True, 'toggle_nr', H("toggle.inputs.acres"))

    if toggle_nr:
        plot_df['Net_Revenue'] = plot_df['Net_Revenue']
    else :
        plot_df['Net_Revenue'] = plot_df['Net_Revenue'] / first_params["net_acres"]

    chart_title = "Total" if toggle_nr else "Per Acre"

    chart = (
        alt.Chart(plot_df)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                'Year:Q',
                title='Year',
                axis=alt.Axis(values=include_years, format='d', labelAngle=30),
                scale=alt.Scale(domain=[CHART_BASE_YEAR, max(include_years)])
            ),
            y=alt.Y('Net_Revenue:Q', title= chart_title + ' Net Revenue'),
            color=alt.Color('Protocol:N', title='Protocol'),
            tooltip=['Year', 'Net_Revenue', 'Protocol']
        )
        .properties(
            title= chart_title + f' Estimated Credits for {first_params["net_acres"]:,} acres project',
            width=600,
            height=400
        )
        .configure_axis(grid=True, gridOpacity=0.3)
    )

    st.altair_chart(chart, use_container_width=True)

    summaries_df_display = summaries_df.copy()
    summaries_df_display['Total Net Revenue, $'] = summaries_df_display['total_net'].map('${:,.2f}'.format)
    summaries_df_display['NPV (Year 20)'] = summaries_df_display['npv_yr20'].map('${:,.2f}'.format)
    summaries_df_display['NPV / Acre'] = summaries_df_display['npv_per_acre'].map('${:,.2f}'.format)

    # Keep only the columns to show
    summaries_df_display = summaries_df_display[['Protocol', 'Total Net Revenue, $', 'NPV (Year 20)', 'NPV / Acre']]

    st.subheader("Project Financials Summary", anchor=None, help=H("credits.summary_subheader"), divider=False, width="stretch")
    st.table(summaries_df_display.set_index('Protocol'))

    # CSV download
    st.download_button(
        label="⬇️ Download Proforma table (CSV)",
        data=df_pf.to_csv(index=False).encode("utf-8"),
        file_name="credits_proforma.csv",
        mime="text/csv",
        use_container_width=True,
        help=H("credits.download_button")
    )

    st.markdown(
        "Generate a comprehensive PDF report of your project analysis.",
        help=H("reports.generate_report_description")
    )
    if st.button(
        "Generate Project Report",
        use_container_width=True,
        type="primary",
        help=H("reports.generate_report_button")
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
        st.error("No financial data found. Return to the Project Financials section first.")
        return None
    
    
    
    # Collect data for the report
    # Planting design - using static values for now (can be made dynamic later)
    planting_design = [
        {"column1": "Reforestation Strategy", "column2": "Mixed Species Planting"},
        {"column1": "Variant", "column2": st.session_state.get("selected_variant", "PN")},
        {"column1": "Location Name", "column2": st.session_state.get("selected_varloc_name", "Olympic National Forest")},
        {"column1": "Location Code", "column2": st.session_state.get("selected_varloc_code", "609")},
        {"column1": "Area, acres", "column2": str(st.session_state.get('net_acres', 10000))},
        {"column1": "Survival Rate, %", "column2": st.session_state.get('survival', 70)},
        {"column1": "Site Index", "column2": str(st.session_state.get('si', 120))},
        {"column1": "Included Protocols", "column2": ", ".join(st.session_state.get("carbon_units_inputs", {}).get("protocols", []))},
    ]

    # Species mix — built dynamically from variant species config
    species_mix = []
    species_mix.append({"column1": "Species", "column2": "TPA#footnote[Trees per Acre]"})
    selected_variant = st.session_state.get("selected_variant", "PN")
    sp_keys = _species_keys(selected_variant)
    for i, key in enumerate(sp_keys):
        value = st.session_state.get(key, 0)
        if value > 0:
            label = _species_label(selected_variant, i)
            species_mix.append({"column1": label, "column2": str(value)})

    # Financial options 1
    financial_options1 = [
        {"column1": "Number of Plots", "column2": str(st.session_state.get('credits_num_plots', 1))},
        {"column1": "Cost per CFI Plot, $", "column2": str(st.session_state.get('credits_cost_per_cfi_plot', 1))},
        {"column1": "Initial Price per CU, $", "column2": str(st.session_state.get('credits_price_per_ert_initial', 1.0))},
        {"column1": "Credit Price Increase, %", "column2": str(st.session_state.get('credits_credit_price_increase', 0.0))},
        {"column1": "Validation Cost, $", "column2": str(st.session_state.get('credits_validation_cost', 1))},
        {"column1": "Verification Cost, $", "column2": str(st.session_state.get('credits_verification_cost', 1))},        
    ]

    # Financial options 2
    financial_options2 = [
        {"column1": "Registry Fees, $", "column2": str(st.session_state.get('credits_registry_fees', 1))},
        {"column1": "Issuance Fee per CU, $", "column2": str(st.session_state.get('credits_issuance_fee_per_ert', 0.0))},
        {"column1": "Anticipated Inflation, %", "column2": str(st.session_state.get('credits_anticipated_inflation', 0.0))},
        {"column1": "Discount Rate, %", "column2": str(st.session_state.get('credits_discount_rate', 0.0))},
        {"column1": "Initial Planting Cost, $", "column2": str(st.session_state.get('credits_planting_cost', 1000))},
    ]

    # Carbon data from merged_df - map to expected column names
    carbon_df = st.session_state.merged_df[['Year', 'CU', 'Protocol']].copy()
    carbon_df = carbon_df.rename(columns={'CU': 'CUs'})

    # Annual CO2 per acre derived from carbon scores (no protocol split)
    carbon_scores = st.session_state.carbon_df[["Year", "Annual_ABLD_C"]].copy()
    carbon_scores["Annual CO2 per acre"] = carbon_scores["Annual_ABLD_C"] * 3.667
    carbon_scores["Annual CO2"] = carbon_scores["Annual CO2 per acre"] * st.session_state.get("net_acres", 0)
    carbon_scores = carbon_scores[["Year", "Annual CO2 per acre", "Annual CO2"]]

    # Financials per protocol/year from proforma outputs
    proforma_df = st.session_state.proforma_df[["Year", "Protocol", "Total_Revenue", "Total_Costs", "Net_Revenue"]].copy()
    proforma_df = proforma_df.rename(
        columns={
            "Total_Revenue": "TotalRevenue",
            "Total_Costs": "TotalCosts",
            "Net_Revenue": "NetRevenue",
        }
    )

    carbon_df = carbon_df.merge(carbon_scores, on="Year", how="left")
    carbon_df = carbon_df.merge(proforma_df, on=["Year", "Protocol"], how="left")
    carbon_df[["Annual CO2 per acre", "Annual CO2", "NetRevenue", "TotalCosts", "TotalRevenue"]] = (
        carbon_df[["Annual CO2 per acre", "Annual CO2", "NetRevenue", "TotalCosts", "TotalRevenue"]].fillna(0)
    )

    carbon_data = carbon_df.to_dict(orient="records")

    # Get selected variant
    selected_variant = st.session_state.get("selected_variant", "PN")
    selected_varloc_name = st.session_state.get("selected_varloc_name", "Olympic National Forest")
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
    carbon unit chart, financial inputs, and financial results.
    """
    # Row 1: Planting sliders | Carbon chart
    with st.expander(label="Planting Parameters", expanded=True):
        col1, col2 = st.columns([1,2], gap="large")
        with col1:
            planting_sliders()
        with col2:
            carbon_chart()

    # Row 2: Acreage & Protocol | Carbon units chart
    with st.expander(label="Carbon Estimates", expanded=True):
        col3, col4 = st.columns([1,2], gap="large")
        with col3:
            if "carbon_df" not in st.session_state:
                st.error("No carbon data found. Adjust sliders above first.")
                st.stop()
            
            # restore backup and init state for carbon units
            _restore_backup(_carbon_units_keys(), backup_name="_carbon_units_backup")
            _init_carbon_units_state()

            # render widget using key only to enable restoring backups
            protocols = st.multiselect(
                "Select Protocol(s)",
                options=["ACR",
                         "CAR",
                         "VERRA",
                         "GS",  
                         "ISO"],
                key="carbon_units_protocols",
                help=H("carbon.protocols_multiselect")
            )

            st.session_state["carbon_units_inputs"] = {"protocols": protocols}

            # backup latest selections for carbon units
            _backup_keys(_carbon_units_keys(), backup_name="_carbon_units_backup")

        with col4:
            carbon_units() 

    # Row 3: Proforma inputs | Credits chart + summary
    with st.expander(label="Project Financials", expanded=True):
        proforma_params = credits_inputs(prefix="credits_")
        credits_results(proforma_params)

    
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
from utils.functions.statefulness import  _carbon_units_keys, _init_planting_state, _init_carbon_units_state, _backup_keys, _restore_backup, _species_keys, _label_for
from utils.functions.models import build_input_vector, pick_fvs_models, load_fvs_models, predict_metrics
from utils.config import get_api_base_url

API_BASE_URL = get_api_base_url()

@st.cache_data
def load_variant_presets(path: str = "conf/base/FVSVariant_presets.json"):
    """
    Load FVS variant preset values from a JSON file and return them as a
    dictionary. Cached by Streamlit to avoid repeated disk access.
    """
    with open(path, "r") as f:
        return json.load(f)

def _credits_keys(prefix: str = "credits_") -> list[str]:
    """
    Return all proforma input keys (prefixed) that should persist for the Credits section.
    Uses the JSON defaults as the source for which keys exist.
    """
    defaults = _load_proforma_defaults()
    return [prefix + k for k in defaults.keys()]

def planting_sliders():
    """
    Render all planting-related Streamlit sliders. Restores saved state, renders species sliders, computes species mix values, and stores
    all planting parameters in session state. 
    """
    presets = load_variant_presets()
    variant = st.session_state.get("selected_variant", "PN")

    if variant not in presets:
        st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
    preset = presets.get(variant, presets.get("PN", {}))

    st.markdown(f"**FVS Variant:** {variant}", unsafe_allow_html=False, help=H("planting.variant_label"), width="stretch")

    species_keys = _species_keys(preset)
    
    # restore any missing keys from previous interaction with page (in case widgets were unmounted on the other page)
    _restore_backup(["survival", "si", "net_acres", *species_keys])

    # Initialize presets ONLY if the variant truly changed
    _init_planting_state(variant, preset) 

    # Render widgets (key only; no value) so existing state is used
    # net_acres input in planting params for organization (top of page), but not in FVSVariant_presets.json
    st.number_input(
    "Net Acres:",
    min_value=1,
    step=100,
    key="net_acres",
    help=H("number.inputs.acres")
    )
    st.slider("Survival Percentage", 40, 90, key="survival", help=H("planting.slider_survival"))
    st.slider("Site Index", 96, 137, key="si", help=H("planting.slider_si"))

    st.markdown("🌲 Species Mix (TPA)", unsafe_allow_html=False, help=H("planting.species_mix_header"), width="stretch")
    tpa_cap = preset.get("_tpa_cap", 435)
    for spk in species_keys:
        st.slider(_label_for(spk), 0, tpa_cap, key=spk)

    # Summary 
    total_tpa = sum(int(st.session_state.get(k, 0)) for k in species_keys)
    st.markdown(f"**Total TPA:** {total_tpa}", unsafe_allow_html=False, help=H("planting.total_tpa_label"), width="stretch")
    if total_tpa > tpa_cap:
        st.warning(f"Total initial TPA exceeds {tpa_cap} and may present an unrealistic scenario. Consider adjusting sliders.")

    st.session_state["species_mix"] = {k: int(st.session_state.get(k, 0)) for k in species_keys}

    # Backup latest values so they're available if user navigates away and back
    _backup_keys(["survival", "si", "net_acres", *species_keys])

@st.cache_data(ttl=300)
def fetch_carbon_coefficients():
    resp = requests.get(f"{API_BASE_URL}/carbon/coefficients", timeout=5)
    resp.raise_for_status()
    return resp.json()

def carbon_chart():
    """
    Compute cumulative and annual carbon scores using regression coefficients and
    current planting inputs. Build a DataFrame and render an Altair time-series
    carbon chart. Store intermediate data in session state.
    """
    # calculate total_tpa from session inputs (required input to models)
    if "species_keys" in st.session_state:
        species_keys = st.session_state["species_keys"]
    else:
        presets = load_variant_presets()
        variant = st.session_state.get("selected_variant", "PN")
        if variant not in presets:
            st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
        preset = presets.get(variant, presets.get("PN", {}))
        species_keys = _species_keys(preset)

    total_tpa = sum(int(st.session_state.get(k, 0)) for k in species_keys)
    
    # load fvs models
    models_path = pick_fvs_models(
        base='data/',
        variant=st.session_state.get("selected_variant", "PN"),
        loccode=st.session_state.get("FVSLocCode"),
    )
    models = load_fvs_models(models_path)

    # create model input vector from user inputs
    X = build_input_vector(
        survival=st.session_state["survival"],
        total_tpa=total_tpa,
        sp1=st.session_state[species_keys[0]],  # indexing this way works because spp order is preserved from JSON w/ tuple
        sp2=st.session_state[species_keys[1]],  # see _species_keys function
        sp3=st.session_state[species_keys[2]],
        sp4=st.session_state[species_keys[3]],
        si=st.session_state["si"],
    )

    st.session_state.carbon_df = predict_metrics(models, X)

    toggle_oc = st.toggle('Show Project Acreage', True, 'toggle_oc', H("toggle.inputs.acres"))

    # Scale outputs if project acreage selected
    plot_df = st.session_state.carbon_df.copy()
    plot_df_vars = [v for v in plot_df.columns.values if v != 'Year']
    if toggle_oc:
        for v in plot_df_vars:
            plot_df[v] = plot_df[v] * st.session_state["net_acres"]

    # Mapping from friendly labels to variable names
    single_metric_vars = {
        "Aboveground live biomass carbon": "ABLD_C",
        "Basal area": "BA",
        "Quadratic mean diameter": "QMD",
        "Stand density index": "SDI",
        "Total cubic volume": "TCuFt",
    }
    metric_options = list(single_metric_vars.keys())

    # Select primary and secondary variables to plot
    col_select_1, col_select_2 = st.columns(2)
    with col_select_1:
        primary_metric_label = st.selectbox(
            "Primary variable to display",
            metric_options,
            index=metric_options.index("Aboveground live biomass carbon"),
            key="primary_metric_select",
        )
    with col_select_2:
        secondary_metric_label = st.selectbox(
            "Secondary variable to display",
            metric_options,
            index=metric_options.index("Basal area"),
            key="secondary_metric_select",
        )
    st.divider()

    def render_metric_chart(selected_metric_label: str, title_suffix: str = ""):
        """Render a line chart for a selected metric label."""
        var_name = single_metric_vars[selected_metric_label]
        if var_name not in plot_df.columns:
            st.warning(f"Metric '{selected_metric_label}' is not available in the current model outputs.")
            return

        df_metric = plot_df[["Year", var_name]]

        # Use the friendly label as y-axis title
        metric_chart = (
            alt.Chart(df_metric)
            .mark_line(point=True)
            .encode(
                x=alt.X("Year:O", title="Year", axis=alt.Axis(labelAngle=30)),
                y=alt.Y(f"{var_name}:Q", title=selected_metric_label),
                tooltip=["Year", var_name],
            )
            .properties(
                title=f"{selected_metric_label}{title_suffix}",
                height=350,
            )
        )
        st.altair_chart(metric_chart, use_container_width=True)

    # Render two plots
    render_metric_chart(primary_metric_label, title_suffix="")
    st.divider()
    render_metric_chart(secondary_metric_label, title_suffix="")
    st.divider()

    # Success messages based on ABLD_C (still tied to carbon)
    if "ABLD_C" in plot_df.columns:
        try:
            year_2064_val = plot_df.loc[plot_df['Year'] == 2064, 'ABLD_C'].iloc[-1]
            st.success(f"Final Carbon Output (year 2064): {year_2064_val:.2f}")
        except IndexError:
            pass  # year 2064 not present

        st.success(
            f"Final Carbon Output (year {int(plot_df['Year'].max())}): "
            f"{plot_df['ABLD_C'].iloc[-1]:.2f}"
        )
    else:
        st.info("ABLD_C is not available in the current model outputs.")

def carbon_units():
    """
    Convert annual carbon scores into carbon units (CUs) for each selected
    protocol. Apply buffers, rules, and interpolation. Store results in session
    state and render the CU chart.
    """
    if "carbon_df" not in st.session_state:
            st.error("No carbon data found. Adjust sliders first.")
            st.stop()

    df = st.session_state.carbon_df.copy()

    inputs = st.session_state.get("carbon_units_inputs", {"protocols": ["ACR/CAR/VERRA"]})
    protocols = inputs["protocols"]

    all_protocol_dfs = []
    
    for protocol in protocols:
        df_base = df.copy()
        df_base['Onsite Total CO2'] = df_base['ABLD_C'] * 3.667

        if protocol == "ACR/CAR/VERRA": 
            BUF = 0.20
            coeff = 1.0
            apply_buf = True
        elif protocol == "GS": #no buffer value
            coeff = 1.0
            apply_buf = False
        elif protocol == "ISO":
            BUF = 0.25 #dummy value
            coeff = 1.0
            apply_buf = True
        else:
            BUF = 0.20
            coeff = 1.0
            apply_buf = True

        df_base['Onsite Total CO2'] = df_base['Onsite Total CO2'] * coeff

        # Interpolation
        df_poly = df_base[['Year', 'Onsite Total CO2']].sort_values('Year')
        X = df_poly['Year'].values
        y = df_poly['Onsite Total CO2'].values
        spline = make_interp_spline(X, y, k=3)

        years_interp = np.arange(df_poly['Year'].min(), df_poly['Year'].max() + 1)
        y_interp = spline(years_interp)

        df_interp = pd.DataFrame({
            'Year': years_interp,
            'Onsite Total CO2_interp': y_interp,
            'ModelType': 'Project',
            'Protocol': protocol
        })

        baseline_df = pd.DataFrame({
            'Year': years_interp,
            'Onsite Total CO2_interp': 0,
            'ModelType': 'Baseline',
            'Protocol': protocol
        })

        baseline_df['delta_C_baseline'] = baseline_df['Onsite Total CO2_interp'].diff()
        df_interp['delta_C_project'] = df_interp['Onsite Total CO2_interp'].diff()

        merged_df = pd.merge(
            baseline_df[['Year', 'delta_C_baseline']],
            df_interp[['Year', 'delta_C_project']],
            on='Year'
        )

        # Compute CU only if buffer applies
        if apply_buf:
            merged_df['C_total'] = merged_df['delta_C_project'] - merged_df['delta_C_baseline']
            merged_df['BUF'] = merged_df['C_total'] * BUF
            merged_df['CU'] = merged_df['C_total'] - merged_df['BUF']
        else:
            merged_df['C_total'] = merged_df['delta_C_project'] - merged_df['delta_C_baseline']
            merged_df['BUF'] = 0.0
            merged_df['CU'] = merged_df['C_total']

        merged_df['Protocol'] = protocol

        for col in ['delta_C_project', 'delta_C_baseline', 'C_total', 'BUF', 'CU']:
            merged_df[col] = merged_df[col].round(2)

        # Append each protocol's results to the list
        all_protocol_dfs.append(merged_df)

    # Combine results
    if all_protocol_dfs:
        final_df = pd.concat(all_protocol_dfs)
        st.session_state.merged_df = final_df
    else:
        st.error("No protocols selected or no data available to plot.")
        return

    toggle_ce = st.toggle('Show Project Acreage', True, 'toggle_ce', H("toggle.inputs.acres"))

    # Adjust chart values based on toggle
    plot_df = final_df.copy()
    if toggle_ce:
        plot_df['CU'] = plot_df['CU'] * st.session_state["net_acres"]

    chart_title = "(tons/project)" if toggle_ce else "(tons/acre)"

    CU_chart = alt.Chart(plot_df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('CU:Q', title='CUs ' + chart_title),
        color='Protocol:N',
        tooltip=['Year', 'CU', 'Protocol']
    ).properties(
        title='Annual CU Estimates ' + chart_title,
        width=600,
        height=400
    ).configure_axis(grid=True, gridOpacity=0.3)

    st.altair_chart(CU_chart, use_container_width=True)

# @st.cache_data
# def _load_proforma_defaults() -> dict:
#     """
#     Load the default proforma economic and financial parameters from conf/base/proforma_presets.json.
#     """
#     with open("conf/base/proforma_presets.json") as f:
#         return json.load(f)

@st.cache_data(ttl=300)
def _load_proforma_defaults() -> dict:
    resp = requests.get(f"{API_BASE_URL}/proforma/presets", timeout=5)
    resp.raise_for_status()
    return resp.json()

def _seed_defaults(prefix: str = "credits_"):
    """
    Seed Streamlit session state with default financial and credit parameters
    based on proforma defaults. Only sets missing keys.
    """
    defaults = _load_proforma_defaults()
    for k, v in defaults.items():
        st.session_state.setdefault(prefix + k, v)

def credits_inputs(prefix: str = "credits_") -> dict:
    """
    Render Proforma inputs in the current container and return a dictionary of typed values.
    """
    # restore backup so users keep their previous values after navigation
    _restore_backup(_credits_keys(prefix), backup_name="_credits_backup")
    
    # seed defaults (setdefault) will not overwrite restored/user values
    _seed_defaults(prefix)
    
    st.markdown("Financial Options", help=None)
    container = st.container(height=600)
    with container:
        # net_acres              = st.number_input("Net Acres:", min_value=1, step=100, key=prefix+"net_acres", help=H("credits.inputs.net_acres"))
        num_plots              = st.number_input("# Plots:", min_value=1, key=prefix+"num_plots", help=H("credits.inputs.num_plots"))
        cost_per_cfi_plot      = st.number_input("Cost/CFI Plot, $:", min_value=1, key=prefix+"cost_per_cfi_plot", help=H("credits.inputs.cost_per_cfi_plot"))
        price_per_ert_initial  = st.number_input("Initial Price/CU, $:", min_value=1.0, key=prefix+"price_per_ert_initial", help=H("credits.inputs.price_per_ert_initial"))
        credit_price_increase_perc = st.number_input("Credit Price Increase, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"credit_price_increase", help=H("credits.inputs.credit_price_increase"))
        registry_fees              = st.number_input("Registry Fees, $:", min_value=1, key=prefix+"registry_fees", help=H("credits.inputs.registry_fees"))
        validation_cost            = st.number_input("Validation Cost, $:", min_value=1, key=prefix+"validation_cost", help=H("credits.inputs.validation_cost"))
        verification_cost          = st.number_input("Verification Cost, $:", min_value=1, key=prefix+"verification_cost", help=H("credits.inputs.verification_cost"))
        issuance_fee_per_ert       = st.number_input("Issuance Fee per CU, $:", min_value=0.0, step=0.01, format="%.2f", key=prefix+"issuance_fee_per_ert", help=H("credits.inputs.issuance_fee_per_ert"))
        anticipated_inflation_perc = st.number_input("Anticipated Inflation, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"anticipated_inflation", help=H("credits.inputs.anticipated_inflation"))
        discount_rate_perc         = st.number_input("Discount Rate, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"discount_rate", help=H("credits.inputs.discount_rate"))
        planting_cost              = st.number_input("Initial Planting Cost, $:", min_value=0, key=prefix+"planting_cost", help=H("credits.inputs.planting_cost"))
        seedling_cost              = st.number_input("Initial Seedling Cost, $:", min_value=0, key=prefix+"seedling_cost", help=H("credits.inputs.seedling_cost"))

    # backup inputs so the latest entries persist across navigation
    _backup_keys(_credits_keys(prefix), backup_name="_credits_backup")

    # constants (constrained by modeling backend)
    year_start     = 2024
    years_advance  = 35
    net_acres = st.session_state["net_acres"]

    return {
        "net_acres": net_acres,
        "num_plots": num_plots,
        "cost_per_cfi_plot": cost_per_cfi_plot,
        "price_per_ert_initial": float(price_per_ert_initial),
        "credit_price_increase": float(credit_price_increase_perc) / 100.0,
        "registry_fees": registry_fees,
        "validation_cost": validation_cost,
        "verification_cost": verification_cost,
        "issuance_fee_per_ert": float(issuance_fee_per_ert),
        "anticipated_inflation": float(anticipated_inflation_perc) / 100.0,
        "discount_rate": float(discount_rate_perc) / 100.0,
        "planting_cost": planting_cost,
        "seedling_cost": seedling_cost,
        "year_start": year_start,
        "years_advance": years_advance,
    }

def _compute_proforma(df_ert_ac: pd.DataFrame, p: dict) -> pd.DataFrame:
    """
    df_ert_ac: DataFrame with ['Year','CU','Protocol'] where CU is per-acre
    p: params dict from credits_inputs()
    returns full proforma DataFrame with costs, revenue, net revenue for each protocol
    """
    results = []
    for protocol, subdf in df_ert_ac.groupby("Protocol"):
        df = subdf[['Year', 'CU']].copy()
        df = df.rename(columns={'CU': 'CU_ac'})
        df['Project_acres'] = p['net_acres']
        df['CU'] = df['CU_ac'] * p['net_acres']

        # credit volume: sell every 5th year including start year
        df['CUs_Sold'] = 0.0
        for i, row in df.iterrows():
            if row['Year'] == p['year_start'] or ((row['Year'] - p['year_start']) % 5 == 0 and row['Year'] > p['year_start']):
                df.loc[i, 'CUs_Sold'] = df.loc[max(0, i-4):i, 'CU'].sum()

        # revenue
        df['CU_Credit_Price'] = p['price_per_ert_initial'] * ((1 + p['credit_price_increase']) ** (df['Year'] - p['year_start']))
        df['Total_Revenue'] = df['CUs_Sold'] * df['CU_Credit_Price']

        # costs
        df['Validation_and_Verification'] = 0
        df.loc[df['Year'] == p['year_start'], 'Validation_and_Verification'] = p['validation_cost']
        df.loc[(df['Year'] > p['year_start']) & ((df['Year'] - p['year_start']) % 5 == 0), 'Validation_and_Verification'] = p['verification_cost']

        df['Survey_Cost'] = 0
        df.loc[(df['Year'] - p['year_start']) % 5 == 4, 'Survey_Cost'] = p['num_plots'] * p['cost_per_cfi_plot'] * (1 + p['anticipated_inflation'])

        df['Registry_Fees'] = p['registry_fees']
        df['Issuance_Fees'] = df['CUs_Sold'] * p['issuance_fee_per_ert']
        df['Planting_Cost'] = p['planting_cost']
        df['Seedling_Cost'] = p['seedling_cost']

        df['Total_Costs'] = (
            df['Validation_and_Verification'] +
            df['Survey_Cost'] +
            df['Registry_Fees'] +
            df['Issuance_Fees'] +
            df['Planting_Cost'] +
            df['Seedling_Cost']
        )
        df['Net_Revenue'] = df['Total_Revenue'] - df['Total_Costs']
        df['Protocol'] = protocol
        results.append(df)

    return pd.concat(results, ignore_index=True)

def credits_results(params: dict, prefix: str = "credits_") -> dict:
    """
    Execute the proforma model, summarize financial outputs, render revenue
    charts, generate summary tables, and provide formatted CSV export.
    """
    if "merged_df" not in st.session_state:
        st.error("No carbon data found. Return to the Carbon Units Estimate section first.")
        st.stop()

    # Extract merged CU data per protocol
    df_ert_ac = st.session_state.merged_df[['Year', 'CU', 'Protocol']].copy()

    # Compute full proforma table per protocol
    df_pf = _compute_proforma(df_ert_ac, params)

    # Drop rows with NaN Net_Revenue to avoid chart issues
    df_pf = df_pf.dropna(subset=['Net_Revenue'])

    # Summary metrics per protocol
    year_start = params['year_start']
    year_stop = int(df_pf['Year'].max())

    summaries = []
    for protocol, subdf in df_pf.groupby("Protocol"):
        total_net = subdf['Net_Revenue'].sum()
        npv_yr20 = float(npf.npv(
            params['anticipated_inflation'] + params['discount_rate'],
            subdf[subdf['Year'] <= (year_start + 20)]['Net_Revenue']
        ))
        npv_per_acre = npv_yr20 / params['net_acres']
        summaries.append({
            "Protocol": protocol,
            "total_net": total_net,
            "npv_yr20": npv_yr20,
            "npv_per_acre": npv_per_acre
        })
    summaries_df = pd.DataFrame(summaries)

    # Filter chart to every 5 years (optional)
    include_years = np.arange(year_start, year_stop + 5, 5)
    df_chart = df_pf[df_pf['Year'].isin(include_years)]

    plot_df = df_chart.copy()

    toggle_nr = st.toggle('Show Project Acreage', True, 'toggle_nr', H("toggle.inputs.acres"))

    if toggle_nr:
        plot_df['Net_Revenue'] = plot_df['Net_Revenue']
    else :
        plot_df['Net_Revenue'] = plot_df['Net_Revenue'] / params["net_acres"]

    chart_title = "Total" if toggle_nr else "Per Acre"

    chart = (
        alt.Chart(plot_df)
        .mark_line(point=True)
        .encode(
            x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)), 
            y=alt.Y('Net_Revenue:Q', title= chart_title + ' Net Revenue'),
            color=alt.Color('Protocol:N', title='Protocol'),
            tooltip=['Year', 'Net_Revenue', 'Protocol']
        )
        .properties(
            title= chart_title + f' Estimated Credits for {params["net_acres"]} Acre Project',
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
                options=["ACR/CAR/VERRA", 
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
        col5, col6 = st.columns([1,2], gap="large")
        with col5:
            proforma_params = credits_inputs(prefix="credits_")
        with col6:
            credits_results(proforma_params) 
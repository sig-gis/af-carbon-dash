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
from utils.config import get_api_base_url, normalize_params

from model_service.main import load_variant_presets, _load_proforma_defaults

API_BASE_URL = get_api_base_url()

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

def carbon_chart():
    if not all(k in st.session_state for k in ["tpa_df", "tpa_rc", "tpa_wh", "survival", "si", "net_acres"]):
        st.info("Adjust Planting Design sliders to see the carbon output.")
        return

    payload = {
        "tpa_df": st.session_state["tpa_df"],
        "tpa_rc": st.session_state["tpa_rc"],
        "tpa_wh": st.session_state["tpa_wh"],
        "survival": st.session_state["survival"],
        "si": st.session_state["si"],
    }
    
    resp = requests.post(
        f"{API_BASE_URL}/carbon/calculate",
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()

    df = pd.DataFrame(resp.json()["carbon_df"])
    st.session_state.carbon_df = df

    toggle_oc = st.toggle('Show Project Acreage', True, 'toggle_oc', H("toggle.inputs.acres"))

    chart_title = "Onsite Carbon (tons/project)" if toggle_oc else "Onsite Carbon (tons/acre)"

     # Determine chart data
    plot_df = df.copy()
    if toggle_oc:
        plot_df["C_Score"] = plot_df["C_Score"] * st.session_state["net_acres"]
        plot_df["Annual_C_Score"] = plot_df["Annual_C_Score"] * st.session_state["net_acres"]

    chart_title = "Onsite Carbon (tons/project)" if toggle_oc else "Onsite Carbon (tons/acre)"

    line = alt.Chart(plot_df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('C_Score:Q', title=chart_title),
        tooltip=['Year', 'C_Score']
    ).properties(
        title="Cumulative " + chart_title,
        width=600,
        height=400
    )

    st.altair_chart(line, use_container_width=True)
    st.success(f"Final Carbon Output (year {max(plot_df['Year'])}): {plot_df['C_Score'].iloc[-1]:.2f}")

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
                ["Year", "C_Score"]
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
    df_ert_ac = df_ert_ac.replace([np.inf, -np.inf], np.nan)
    df_ert_ac = df_ert_ac.dropna(subset=['CU'])

    payload = {
        "df_ert_ac": df_ert_ac.to_dict(orient="records"),
        "params": normalize_params(params),
    }

    json.dumps(payload)
    resp = requests.post(
        f"{API_BASE_URL}/proforma/compute",
        json=payload,
        timeout=10,
    )

    resp.raise_for_status()

    df_pf = pd.DataFrame(resp.json()["proforma_rows"])

    # Drop rows with NaN Net_Revenue to avoid chart issues
    df_pf = df_pf.dropna(subset=['Net_Revenue'])

    # Summary metrics per protocol
    year_start = params['year_start']
    year_stop = int(df_pf['Year'].max())

    summaries_df = pd.DataFrame(resp.json()["summaries"])

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

def generate_report():
    """
    Collect project data and request PDF report from the Quarto API.
    """
    if "merged_df" not in st.session_state:
        st.error("Complete the financial analysis first.")
        return

    # Collect data for the report
    # Planting design - using static values for now (can be made dynamic later)
    planting_design = [
        {"column1": "Reforestation Strategy", "column2": "Mixed Species Planting"},
        {"column1": "Survival Rate", "column2": f"{st.session_state.get('survival', 70)}%"},
        {"column1": "Site Index", "column2": str(st.session_state.get('si', 120))},
        {"column1": "Net Acres", "column2": str(st.session_state.get('net_acres', 10000))},
    ]

    # Species mix
    species_mix = []
    species_labels = {
        "tpa_df": "Douglas-fir",
        "tpa_rc": "red cedar",
        "tpa_wh": "western hemlock",
        "tpa_ss": "Sitka spruce",
        "tpa_pp": "ponderosa pine",
        "tpa_wl": "western larch"
    }
    for key, label in species_labels.items():
        value = st.session_state.get(key, 0)
        if value > 0:
            species_mix.append({"column1": label, "column2": str(value)})

    # Financial options 1
    financial_options1 = [
        {"column1": "# Plots", "column2": str(st.session_state.get('credits_num_plots', 1))},
        {"column1": "Cost/CFI Plot, $", "column2": str(st.session_state.get('credits_cost_per_cfi_plot', 1))},
        {"column1": "Initial Price/CU, $", "column2": str(st.session_state.get('credits_price_per_ert_initial', 1.0))},
        {"column1": "Credit Price Increase, %", "column2": str(st.session_state.get('credits_credit_price_increase', 0.0))},
    ]

    # Financial options 2
    financial_options2 = [
        {"column1": "Registry Fees, $", "column2": str(st.session_state.get('credits_registry_fees', 1))},
        {"column1": "Validation Cost, $", "column2": str(st.session_state.get('credits_validation_cost', 1))},
        {"column1": "Verification Cost, $", "column2": str(st.session_state.get('credits_verification_cost', 1))},
        {"column1": "Issuance Fee per CU, $", "column2": str(st.session_state.get('credits_issuance_fee_per_ert', 0.0))},
        {"column1": "Anticipated Inflation, %", "column2": str(st.session_state.get('credits_anticipated_inflation', 0.0))},
        {"column1": "Discount Rate, %", "column2": str(st.session_state.get('credits_discount_rate', 0.0))},
        {"column1": "Initial Planting Cost, $", "column2": str(st.session_state.get('credits_planting_cost', 0))},
        {"column1": "Initial Seedling Cost, $", "column2": str(st.session_state.get('credits_seedling_cost', 0))},
    ]

    # Carbon data from merged_df - map to expected column names
    carbon_df = st.session_state.merged_df[['Year', 'CU', 'Protocol']].copy()
    carbon_df = carbon_df.rename(columns={'CU': 'CUs'})

    # Add placeholder columns that the notebook expects (no calculations)
    carbon_df['Annual CO2 per acre'] = 0  # Placeholder
    carbon_df['Annual CO2'] = 0  # Placeholder
    carbon_df['NetRevenue'] = 0  # Placeholder
    carbon_df['TotalRevenue'] = 0  # Placeholder
    carbon_df['TotalCosts'] = 0  # Placeholder

    carbon_data = carbon_df.to_dict(orient="records")

    # Get selected variant
    selected_variant = st.session_state.get("selected_variant", "PN")

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
                timeout=60,  # Longer timeout for report generation
            )
            resp.raise_for_status()

            # Create download button for the PDF
            pdf_data = resp.content
            st.download_button(
                label="Download Project Report (PDF)",
                data=pdf_data,
                file_name="project_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            st.success("Report generated successfully!")

    except requests.RequestException as e:
        st.error(f"Failed to generate report: {str(e)}")

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

    with st.expander(label="Generate Report", expanded=False):
        st.markdown("Generate a comprehensive PDF report of your project analysis.")
        if st.button("Generate Project Report", use_container_width=True, type="primary"):
            generate_report()
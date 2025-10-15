# -----------------------------
# Imports
# -----------------------------
import streamlit as st
import json
import pandas as pd
import os
import numpy as np
import geopandas as gpd
import folium
from pathlib import Path
from streamlit_folium import st_folium
from scipy.interpolate import make_interp_spline
import altair as alt
import numpy_financial as npf

# -----------------------------
# Functions
# -----------------------------
@st.fragment
def load_geojson_fragment(simplified_geojson_path, shapefile_path, tolerance_deg=0.001, skip_keys={"Shape_Area", "Shape_Leng"}, max_tooltip_fields=3):
    """
    Loads a GeoJSON (or simplifies a shapefile if GeoJSON doesn't exist),
    returns the geojson string and filtered tooltip fields.
    """
    @st.cache_data
    def simplify_geojson(path: Path, tolerance_deg: float = 0.001) -> str:
        gdf = gpd.read_file(path)
        gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)
        # Keep only necessary columns
        keep = [c for c in ["FVSVariant", "FVSVarName", "FVSLocName"] if c in gdf.columns]
        gdf = gdf[keep + ["geometry"]] if keep else gdf[["geometry"]]
        return gdf.to_json(na="drop")
    
    @st.cache_data
    def read_geojson_text(path: Path) -> str:
        return Path(path).read_text(encoding="utf-8")

    # Load GeoJSON
    if os.path.exists(simplified_geojson_path):
        geojson_str = read_geojson_text(simplified_geojson_path)
        st.success("GeoJSON loaded successfully")
    else:
        try:
            geojson_str = simplify_geojson(shapefile_path, tolerance_deg=tolerance_deg)
        except Exception as e:
            st.error(f"Failed to load shapefile: {e}")
            st.stop()
            return None, None

    # Extract tooltip fields
    try:
        feat0_props = json.loads(geojson_str)["features"][0]["properties"]
        tooltip_fields = [k for k in feat0_props.keys() if k not in skip_keys][:max_tooltip_fields]
    except Exception:
        tooltip_fields = None

    return geojson_str, tooltip_fields

@st.fragment
def build_map(geojson_str, center=(37.8, -96.9), zoom=5, tooltip_fields=None, highlight_feature=None):
    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB positron")
    
    # Base layer
    gj = folium.GeoJson(
        data=geojson_str,
        name="FVS Variants",
        style_function=lambda x: {"fillColor": "blue", "color": "black", "weight": 1, "fillOpacity": 0.3},
        highlight_function=lambda x: {"fillColor": "yellow", "color": "red", "weight": 2, "fillOpacity": 0.6},
    )
    if tooltip_fields:
        gj.add_child(folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_fields, sticky=True))
    gj.add_to(m)

    # Highlight only the last clicked feature
    if highlight_feature:
        folium.GeoJson(
            highlight_feature["geometry"],
            name="Selected Boundary",
            style_function=lambda x: {"fillColor": "yellow", "color": "red", "weight": 3, "fillOpacity": 0.2},
        ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m

@st.fragment
def get_tooltip_fields(geojson_str, skip_keys={"Shape_Area", "Shape_Leng"}, max_fields=4):
    try:
        feat0_props = json.loads(geojson_str)["features"][0]["properties"]
        # Filter out unwanted keys
        tooltip_fields = [k for k in feat0_props.keys() if k not in skip_keys][:max_fields]
    except Exception:
        tooltip_fields = None
    return tooltip_fields

# helper
def _loccode_str(v):
    try:
        return f"{int(v):03d}"
    except Exception:
        return None

@st.fragment
def show_clicked_variant(map_data):
    """Update session state with the last clicked feature and its properties."""
    if map_data and map_data.get("last_active_drawing"):
        feat = map_data["last_active_drawing"]
        props = feat.get("properties", {})

        if props:
            if st.session_state.get("clicked_feature") != feat:
                st.session_state["clicked_feature"] = feat
                st.session_state["clicked_props"] = props
                st.session_state["selected_variant"] = props.get("FVSVariant", "PN")
                # NEW: stash loc code (zero-padded like 712 -> "712")
                st.session_state["FVSLocCode"] = _loccode_str(props.get("FVSLocCode"))
                st.rerun()

@st.fragment
def display_selected_info():
    if "clicked_props" in st.session_state:
        props = st.session_state["clicked_props"]

        st.subheader("Selected Feature Info", anchor=None, help='Location information of selected variant.', divider=False, width="stretch")
        pretty_names = {
            "FVSLocCode": "FVS Location Code",
            "FVSLocName": "FVS Location Name",
            "FVSVarName": "FVS Variant Name",
            "FVSVariant": "FVS Variant",
        }
        skip_keys = {"Shape_Area", "Shape_Leng", 'FVSVariantLoc'}

        for key, value in props.items():
            if key not in skip_keys:
                display_key = pretty_names.get(key, key)
                st.markdown(f"**{display_key}:** {value}")

@st.fragment
def submit_map(map_data):
    if map_data and map_data.get("last_active_drawing"):
        clicked = map_data["last_active_drawing"].get("properties", {})
        if clicked:
            st.session_state["selected_variant"] = clicked.get("FVSVariant", "PN")

SPECIES_LABELS = {
    "tpa_df": "Douglas-fir",
    "tpa_rc": "red cedar",
    "tpa_wh": "western hemlock",
    "tpa_ss": "Sitka spruce",
    "tpa_pp": "ponderosa pine",
    "tpa_wl": "western larch"
}

@st.cache_data
def load_variant_presets(path: str = "conf/base/FVSVariant_presets.json"):
    with open(path, "r") as f:
        return json.load(f)
    
def _species_keys(preset: dict):
    # any key that starts with tpa_ is treated as a species slider
    return [k for k in preset.keys() if k.startswith("tpa_")]

def _label_for(key: str) -> str:
    return SPECIES_LABELS.get(key, key.replace("tpa_", "TPA_").upper())

def planting_sliders(prefix: str = "credits_"):
    presets = load_variant_presets()
    variant = st.session_state.get("selected_variant", "PN")

    if variant not in presets:
        st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
    preset = presets.get(variant, presets.get("PN", {}))

    st.markdown(f"**FVS Variant:** {variant}", unsafe_allow_html=False, help='Selected FVS Variant (see Site Selection Map tab)', width="stretch")

    # When variant changes, clear old tpa_* and seed defaults for current species
    last_variant = st.session_state.get("_last_variant")
    if last_variant != variant:
        # clear previous species values
        for k in list(st.session_state.keys()):
            if k.startswith("tpa_"):
                del st.session_state[k]
        # seed defaults for this variant's species
        for spk in _species_keys(preset):
            st.session_state[spk] = preset.get(spk, 0)
        # seed survival/si if first time or variant changed
        st.session_state["survival"] = preset.get("survival", st.session_state.get("survival", 70))
        st.session_state["si"] = preset.get("si", st.session_state.get("si", 120))
        st.session_state["_last_variant"] = variant

    # --- Common sliders ---
    st.slider("Survival Percentage", 40, 90,
              value=int(st.session_state.get("survival", preset.get("survival", 70))),
              key="survival",
              help = 'survival percentage help')
    st.slider("Site Index", 96, 137,
              value=int(st.session_state.get("si", preset.get("si", 120))),
              key="si",
              help = 'site index help')

    # --- Dynamic species sliders ---
    st.markdown("🌲 Species Mix (TPA)", unsafe_allow_html=False, help='Set trees per acre (TPA) to be planted for each species below.', width="stretch")
    species_keys = _species_keys(preset)

    # Optional: set a total TPA cap if you want to enforce one (put `_tpa_cap` in JSON if needed)
    tpa_cap = preset.get("_tpa_cap", 435) 

    running_total = 0
    for i, spk in enumerate(species_keys):
        default_val = int(st.session_state.get(spk, preset.get(spk, 0)))
        label = _label_for(spk)

        if tpa_cap is not None:
            # Greedy budget: allow up to remaining budget; last species can soak up the rest
            remaining = max(0, tpa_cap - running_total)
            max_val = remaining if i == len(species_keys) - 1 else tpa_cap
            st.slider(label, 0, tpa_cap, value=min(default_val, int(max_val)), key=spk)
        else:
            # No total cap — simple independent sliders
            st.slider(label, 0, tpa_cap, value=default_val, key=spk)

        running_total += int(st.session_state.get(spk, 0))

    # Summary
    total_tpa = sum(int(st.session_state.get(k, 0)) for k in species_keys)
    st.markdown(f"**Total TPA:** {total_tpa}", unsafe_allow_html=False, help='Sum of TPA values for all species above.', width="stretch")
    if running_total > tpa_cap:
        st.warning(f"Total initial TPA exceeds {tpa_cap} and may present an unrealistic scenario. Consider adjusting sliders.")

    # If you need the selected species mix as a dict elsewhere:
    st.session_state["species_mix"] = {k: int(st.session_state.get(k, 0)) for k in species_keys}

def carbon_chart():
    # Ensure the sliders have been set
    if not all(k in st.session_state for k in ["tpa_df", "tpa_rc", "tpa_wh", "survival", "si"]):
        st.info("Adjust Planting Scenario sliders to see the carbon output.")
        return

    tpa_df = st.session_state["tpa_df"]
    tpa_rc = st.session_state["tpa_rc"]
    tpa_wh = st.session_state["tpa_wh"]
    tpa_total = tpa_df + tpa_rc + tpa_wh
    survival = st.session_state["survival"]
    si = st.session_state["si"]

    # Load coefficients
    with open("conf/base/carbon_model_coefficients.json", "r") as file:
        coefficients = json.load(file)

    years, c_scores, ann_c_scores = [], [], []
    for year in coefficients.keys():
        c_score = (coefficients[year]['TPA_DF'] * tpa_df 
                   + coefficients[year]['TPA_RC'] * tpa_rc 
                   + coefficients[year]['TPA_WH'] * tpa_wh
                   + coefficients[year]['TPA_total'] * tpa_total
                   + coefficients[year]['Survival'] * survival
                   + coefficients[year]['SI'] * si
                   + coefficients[year]['Intercept'])
        ann_c_score = c_score - c_scores[-1] if c_scores else c_score
        c_scores.append(c_score)
        ann_c_scores.append(ann_c_score)
        years.append(int(year))
    
    year_0 = pd.DataFrame({"Year": [2024], "C_Score": [0], "Annual_C_Score": [0]})
    df = pd.DataFrame({"Year": years, "C_Score": c_scores, "Annual_C_Score": ann_c_scores})
    df = pd.concat([year_0, df])
    st.session_state.carbon_df = df

    # Plot
    line = alt.Chart(df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('C_Score:Q', title='Onsite Carbon (tons/acre)'),
        tooltip=['Year', 'C_Score']
    ).properties(
        title="Cumulative Onsite Carbon",
        width=600,
        height=400
    )
    st.altair_chart(line, use_container_width=True)
    st.success(f"Final Carbon Output (year {max(df['Year'])}): {df['C_Score'].iloc[-1]:.2f}")

def carbon_units():
    if "carbon_df" not in st.session_state:
            st.error("No carbon data found. Please adjust sliders first.")
            st.stop()

    df = st.session_state.carbon_df.copy()

    # Read multiple protocols
    inputs = st.session_state.get("carbon_units_inputs", {"protocols": ["ACR/CAR/VERRA"]})
    protocols = inputs["protocols"]

    all_protocol_dfs = []
    
    for protocol in protocols:
        df_base = df.copy()
        df_base['Onsite Total CO2'] = df_base['C_Score'] * 3.667

        # ----------------------------------
        # Protocol-specific calculations
        # ----------------------------------
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

    # Plot chart with Protocol color encoding
    CU_chart = alt.Chart(final_df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('CU:Q', title='CUs (tonnes CO₂e)'),
        color='Protocol:N',
        tooltip=['Year', 'CU', 'Protocol']
    ).properties(title='Annual CU Estimates', width=600, height=400).configure_axis(grid=True, gridOpacity=0.3)

    st.altair_chart(CU_chart, use_container_width=True)

# ---------- Credits (Proforma) functions ----------
@st.cache_data
def _load_proforma_defaults() -> dict:
    with open("conf/base/proforma_presets.json") as f:
        return json.load(f)

def _seed_defaults(prefix: str = "credits_"):
    defaults = _load_proforma_defaults()
    # store under prefixed keys to avoid collisions
    for k, v in defaults.items():
        st.session_state.setdefault(prefix + k, v)

def credits_inputs(prefix: str = "credits_") -> dict:
    """
    Render Proforma inputs in the current container and return a dict of typed values.
    """
    _seed_defaults(prefix)
    
    st.markdown("Financial Options", help = None)
    container = st.container(height=600)
    with container:
        net_acres              = st.number_input("Net Acres:", min_value=1, step=100, key=prefix+"net_acres", help = 'The total area of land enrolled in the project, measured in acres.')
        num_plots              = st.number_input("# Plots:", min_value=1, key=prefix+"num_plots", help = 'The number of sampling plots established to monitor and measure forest growth/carbon.')
        cost_per_cfi_plot      = st.number_input("Cost/CFI Plot, $:", min_value=1, key=prefix+"cost_per_cfi_plot", help = 'The cost of establishing and maintaining a single Continuous Forest Inventory plot.')
        price_per_ert_initial  = st.number_input("Initial Price/CU, $:", min_value=1.0, key=prefix+"price_per_ert_initial", help = 'The assumed starting market price per carbon credit unit.This can be an ERT, VCU, or other unit depending on protocol.')
        credit_price_increase_perc = st.number_input("Credit Price Increase, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"credit_price_increase", help = 'The assumed annual percentage increase in credit price over the project duration.')
        registry_fees              = st.number_input("Registry Fees, $:", min_value=1, key=prefix+"registry_fees", help = 'Fees charged by the carbon registry annually for project registration and maintenance.')
        validation_cost            = st.number_input("Validation Cost, $:", min_value=1, key=prefix+"validation_cost", help = 'One-time cost for the initial third-party validation of the project.')
        verification_cost          = st.number_input("Verification Cost, $:", min_value=1, key=prefix+"verification_cost", help = 'Recurring cost for independent verification of carbon credits generated.')
        issuance_fee_per_ert       = st.number_input("Issuance Fee per CU, $:", min_value=0.0, step=0.01, format="%.2f", key=prefix+"issuance_fee_per_ert", help = 'The fee charged by the registry each time credits are issued, on a per-credit basis.')
        anticipated_inflation_perc = st.number_input("Anticipated Inflation, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"anticipated_inflation", help = 'The assumed annual inflation rate applied to costs over time.')
        discount_rate_perc         = st.number_input("Discount Rate, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"discount_rate", help = 'The rate used in NPV calculations to account for the time value of money and investment risk.')
        planting_cost = st.number_input("Initial Planting Cost, $:", min_value=0, key=prefix+"planting_cost", help = 'Upfront cost of planting, including site preparation and labor.')
        seedling_cost = st.number_input("Initial Seedling Cost, $:", min_value=0, key=prefix+"seedling_cost", help = 'Upfront cost of purchasing seedlings used for planting.')

    # constants (constrained by modeling backend)
    year_start     = 2024
    years_advance  = 35
    net_acres = st.session_state[prefix + "net_acres"]

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

def credits_results(params: dict):
    if "merged_df" not in st.session_state:
        st.error("No carbon data found. Please return to the Carbon Units Estimate section first.")
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

    # Chart: Net Revenue per protocol
    chart = (
        alt.Chart(df_chart)
        .mark_line(point=True)
        .encode(
            x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)), 
            y=alt.Y('Net_Revenue:Q', title='Net Revenue'),
            color=alt.Color('Protocol:N', title='Protocol'),
            tooltip=['Year', 'Net_Revenue', 'Protocol']
        )
        .properties(
            title=f'Estimated Credits for {params["net_acres"]} Acre Project',
            width=600,
            height=400
        )
        .configure_axis(grid=True, gridOpacity=0.3)
    )

    st.altair_chart(chart, use_container_width=True)

    # Show summary metrics
    summaries_df_display = summaries_df.copy()
    summaries_df_display['Total Net Revenue'] = summaries_df_display['total_net'].map('${:,.2f}'.format)
    summaries_df_display['NPV (Year 20)'] = summaries_df_display['npv_yr20'].map('${:,.2f}'.format)
    summaries_df_display['NPV per Acre'] = summaries_df_display['npv_per_acre'].map('${:,.2f}'.format)

    # Keep only the columns to show
    summaries_df_display = summaries_df_display[['Protocol', 'Total Net Revenue', 'NPV (Year 20)', 'NPV per Acre']]

    # Display as a table
    st.subheader("Project Financials Summary", anchor=None, help='**Protocol:** The carbon accounting protocol / registry (ACR, CAR, VERRA, GS, or ISO) the financial results are based on.\n'
            '**Total Net Revenue:** The total projected revenue from the project over its full crediting period, after deducting costs.\n'
            '**NPV (Year 20) - Net Present Value at Year 20:** shows what the project’s 20-year returns are worth in today’s dollars.\n'
            '**NPV per Acre:** Net Present Value (Year 20) on a per-acre basis.', divider=False, width="stretch")
    st.table(summaries_df_display.set_index('Protocol'))

    # CSV download
    st.download_button(
        label="⬇️ Download Proforma table (CSV)",
        data=df_pf.to_csv(index=False).encode("utf-8"),
        file_name="credits_proforma.csv",
        mime="text/csv",
        use_container_width=True,
        help = 'Download table used to calculate Project Financials.'
    )

@st.fragment
def run_chart():
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
            
            protocols = st.multiselect(
                "Select Protocol(s)",
                options=["ACR/CAR/VERRA", 
                         "GS",  
                         "ISO"],
                default=["ACR/CAR/VERRA"],
                key="carbon_units_protocols",
                help = 'Select one or more protocols to estimate Carbon Units (CUs) and Project Financials.'
            )

            st.session_state["carbon_units_inputs"] = {"protocols": protocols}

        with col4:
            carbon_units() 

    # Row 3: Proforma inputs | Credits chart + summary
    with st.expander(label="Project Financials", expanded=True):
        col5, col6 = st.columns([1,2], gap="large")
        with col5:
            proforma_params = credits_inputs(prefix="credits_")
        with col6:
            # st.subheader("Credits (Proforma) – Results")
            credits_results(proforma_params) 

########################################################################################################################################################################################
# -----------------------------
# Main
# -----------------------------
# -----------------------------
# Page Config
# -----------------------------
st.set_page_config(layout="wide", page_title="Project Builder", page_icon="🌲")

# -----------------------------
# Initialize Session State
# -----------------------------
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Site Selection Map"

# -----------------------------
# File Paths
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")


# -----------------------------
# Conditional Layout (acts like tabs)
# -----------------------------
if st.session_state.active_tab == "Site Selection Map":
    # -----------------------------
    # Site Selection Map View
    # -----------------------------
    # --- Title Row (conditionally shows button after variant selection) ---
    col1, col2 = st.columns([8, 3])

    with col1:
        st.title(
            "🗺️ Site Selection",
            anchor=None,
            help=(
                "Select the FVS Variant Location geometry which contains your project location. "
                "Your selected FVS Variant location will auto-populate helpful planting parameter defaults, "
                "including species mix, for you."
            ),
        )

    with col2:
        # Only show the "Continue" button if a variant is selected
        if st.session_state.get("selected_variant"):
            if st.button(
                "➡️ Planting Scenario",
                use_container_width=True,
                help="Click to continue to the Planting Scenario calculations.",
                type = 'primary'
            ):
                st.session_state.active_tab = "Planting Scenario"
                st.rerun()
        else:
            st.empty()

    st.subheader("Select FVS Variant", anchor=None, help=None, divider=False)

    # Load GeoJSON and Map
    geojson_str, tooltip_fields = load_geojson_fragment(simplified_geojson, local_shapefile)
    st.session_state.setdefault("map_view", {"center": [45.5, -118], "zoom": 6})

    m = build_map(
        geojson_str,
        center=tuple(st.session_state["map_view"]["center"]),
        zoom=int(st.session_state["map_view"]["zoom"]),
        tooltip_fields=tooltip_fields,
        highlight_feature=st.session_state.get("clicked_feature"),
    )

    map_data = st_folium(
        m,
        key="fvs_map",
        height=500,
        use_container_width=True,
    )

    # Display info below map
    show_clicked_variant(map_data)
    display_selected_info()

else:
    # -----------------------------
    # Planting Scenario View
    # -----------------------------
    col1, col2 = st.columns([8, 3])  # adjust ratio as needed

    with col1:
        st.title("🌲 Planting Scenario", anchor=None, help=None)

    with col2:
        if st.button("⬅️ Site Selection", use_container_width=True, help = 'Click to go back to the Site Selection Map.', type = 'primary'):
            st.session_state.active_tab = "Site Selection Map"
            st.rerun()

    run_chart()
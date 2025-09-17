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

        st.subheader("Selected Feature Info")
        pretty_names = {
            "FVSLocCode": "FVS Location Code",
            "FVSLocName": "FVS Location Name",
            "FVSVarName": "FVS Variant Name",
            "FVSVariant": "FVS Variant",
        }
        skip_keys = {"Shape_Area", "Shape_Leng"}

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

def planting_sliders_fragment():
    presets = load_variant_presets()
    variant = st.session_state.get("selected_variant", "PN")

    if variant not in presets:
        st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
    preset = presets.get(variant, presets.get("PN", {}))

    st.markdown(f"**FVS Variant:** {variant}")

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
              key="survival")
    st.slider("Site Index", 96, 137,
              value=int(st.session_state.get("si", preset.get("si", 120))),
              key="si")

    # --- Dynamic species sliders ---
    st.markdown("🌲 Species Mix (TPA)")
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
    st.markdown(f"**Total TPA:** {total_tpa}")
    if running_total > tpa_cap:
        st.warning(f"Total initial TPA exceeds {tpa_cap} and may present an unrealistic scenario. Consider adjusting sliders.")

    # If you need the selected species mix as a dict elsewhere:
    st.session_state["species_mix"] = {k: int(st.session_state.get(k, 0)) for k in species_keys}

# @st.fragment
def carbon_chart_fragment():
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

    df = pd.DataFrame({"Year": years, "C_Score": c_scores, "Annual_C_Score": ann_c_scores})
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
    st.markdown(f"Final Carbon Output (year {max(df['Year'])}): {df['C_Score'].iloc[-1]:.2f}")

def carbon_units_fragment():
    if "carbon_df" not in st.session_state:
        st.error("No carbon data found. Please adjust sliders first.")
        st.stop()

    df = st.session_state.carbon_df.copy()

    # Read inputs from session state (set by the left column)
    inputs = st.session_state.get("carbon_units_inputs", {"acreage": 100, "protocol": "ACR"})
    acreage = inputs["acreage"]
    protocol = inputs["protocol"]

    # Build project DataFrame
    df_acr = df.copy()
    df_acr['Area_acres'] = acreage
    df_acr['Onsite Total CO2'] = df_acr['C_Score'] * 3.667
    df_acr['StudyArea_ModelType'] = "Project"
    df_acr['StudyArea_Protocol'] = protocol

    # Interpolation and calculations remain unchanged
    df_poly = df_acr[['Year', 'Onsite Total CO2']].sort_values('Year')
    X = df_poly['Year'].values
    y = df_poly['Onsite Total CO2'].values
    spline = make_interp_spline(X, y, k=3)
    years_interp = np.arange(df_poly['Year'].min(), df_poly['Year'].max() + 1)
    y_interp = spline(years_interp)

    df_interp = pd.DataFrame({
        'Year': years_interp,
        'Onsite Total CO2_interp': y_interp,
        'ModelType': 'Project'
    })

    baseline_df = pd.DataFrame({
        'Year': years_interp,
        'Onsite Total CO2_interp': 0,
        'ModelType': 'Baseline',
    })

    baseline_df['delta_C_baseline'] = baseline_df['Onsite Total CO2_interp'].diff()
    df_interp['delta_C_project'] = df_interp['Onsite Total CO2_interp'].diff()

    merged_df = pd.merge(
        baseline_df[['Year', 'delta_C_baseline']],
        df_interp[['Year', 'delta_C_project']],
        on='Year'
    )

    BUF = 0.20
    merged_df['C_total'] = merged_df['delta_C_project'] - merged_df['delta_C_baseline']
    merged_df['BUF'] = merged_df['C_total'] * BUF
    merged_df['ERT'] = merged_df['C_total'] - merged_df['BUF']

    for col in ['delta_C_project', 'delta_C_baseline', 'C_total', 'BUF', 'ERT']:
        merged_df[col] = merged_df[col].round(2)

    # Plot chart
    ERT_chart = alt.Chart(merged_df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('ERT:Q', title='ERTs (tonnes CO₂e)'),
        tooltip=['Year', 'ERT']
    ).properties(title='Annual ERT Estimates', width=600, height=400).configure_axis(grid=True, gridOpacity=0.3)

    st.altair_chart(ERT_chart, use_container_width=True)

@st.fragment
def run_chart():
    # Row 1: Planting sliders | Carbon chart
    col1, col2 = st.columns(2)
    with col1:
        planting_sliders_fragment()
    with col2:
        carbon_chart_fragment()

    # Row 2: Acreage & Protocol | Carbon units chart
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("Carbon Estimates")
        if "carbon_df" not in st.session_state:
            st.error("No carbon data found. Adjust sliders above first.")
            st.stop()
        acreage = st.number_input("Enter acreage:", min_value=1, value=100, key="carbon_units_acreage")
        protocol = st.selectbox("Select Protocol", options=["ACR", "CAR", "VERRA"], key="carbon_units_protocol")
        st.session_state["carbon_units_inputs"] = {"acreage": acreage, "protocol": protocol}

    with col4:
        carbon_units_fragment()  

########################################################################################################################################################################################
# -----------------------------
# Main
# -----------------------------
# Tabs
map_tab, plant_tab = st.tabs(["Site Selection Map", "Planting Scenario"])

# Load Shapefile / GeoJSON
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")

st.set_page_config(layout="wide", page_title="Project Builder", page_icon="🌲")

with map_tab:
    st.title("🌲 Site Selection")
    st.subheader("Select FVS Variant")

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

    show_clicked_variant(map_data)
    display_selected_info()

    # with st.form("map_select_form"):
    #     submitted = st.form_submit_button("Select Variant")
    #     if submitted:
    #         if "selected_variant" in st.session_state:
    #             st.success(f"Selected Variant: {st.session_state['selected_variant']}")
    #         else:
    #             st.info("Click a feature on the map first.")

with plant_tab:
    st.title("🌲 Planting Scenario")
    st.subheader("Planting Scenario")
    run_chart()
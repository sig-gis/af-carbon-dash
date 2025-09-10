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

@st.fragment
def show_clicked_variant(map_data):
    """Update session state with the last clicked feature and its properties."""
    if map_data and map_data.get("last_active_drawing"):
        feat = map_data["last_active_drawing"]
        props = feat.get("properties", {})

        if props:
            # Only trigger rerun if this feature is newly clicked
            if st.session_state.get("clicked_feature") != feat:
                st.session_state["clicked_feature"] = feat
                st.session_state["clicked_props"] = props
                st.session_state["selected_variant"] = props.get("FVSVariant", "PN")
                st.rerun()  # <-- Updated for latest Streamlit

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

# @st.fragment
def planting_sliders_fragment():

    # Variant presets
    variant_presets = {
        "AK": {"survival": 70, "si": 110, "tpa_df": 50, "tpa_rc": 20, "tpa_wh": 10},
        "BM": {"survival": 65, "si": 120, "tpa_df": 60, "tpa_rc": 25, "tpa_wh": 15},
        "CA": {"survival": 80, "si": 130, "tpa_df": 55, "tpa_rc": 30, "tpa_wh": 10},
        "CI": {"survival": 75, "si": 125, "tpa_df": 45, "tpa_rc": 25, "tpa_wh": 20},
        "CR": {"survival": 60, "si": 115, "tpa_df": 40, "tpa_rc": 30, "tpa_wh": 15},
        "CS": {"survival": 68, "si": 118, "tpa_df": 50, "tpa_rc": 20, "tpa_wh": 15},
        "EC": {"survival": 72, "si": 122, "tpa_df": 55, "tpa_rc": 15, "tpa_wh": 20},
        "EM": {"survival": 66, "si": 119, "tpa_df": 60, "tpa_rc": 20, "tpa_wh": 10},
        "IE": {"survival": 70, "si": 124, "tpa_df": 50, "tpa_rc": 25, "tpa_wh": 15},
        "LS": {"survival": 65, "si": 117, "tpa_df": 45, "tpa_rc": 30, "tpa_wh": 10},
        "NC": {"survival": 75, "si": 128, "tpa_df": 55, "tpa_rc": 25, "tpa_wh": 10},
        "NE": {"survival": 68, "si": 120, "tpa_df": 50, "tpa_rc": 20, "tpa_wh": 15},
        "PN": {"survival": 70, "si": 125, "tpa_df": 60, "tpa_rc": 15, "tpa_wh": 20},
        "SN": {"survival": 66, "si": 123, "tpa_df": 55, "tpa_rc": 25, "tpa_wh": 10},
        "SO": {"survival": 72, "si": 126, "tpa_df": 50, "tpa_rc": 30, "tpa_wh": 10},
        "TT": {"survival": 65, "si": 119, "tpa_df": 45, "tpa_rc": 20, "tpa_wh": 15},
        "UT": {"survival": 70, "si": 121, "tpa_df": 55, "tpa_rc": 15, "tpa_wh": 20},
        "WC": {"survival": 68, "si": 124, "tpa_df": 50, "tpa_rc": 25, "tpa_wh": 10},
        "WS": {"survival": 66, "si": 122, "tpa_df": 60, "tpa_rc": 20, "tpa_wh": 15}
    }

    variant = st.session_state.get("selected_variant", "PN")
    st.markdown(f"**FVS Variant:** {variant}")
    preset = variant_presets.get(variant, variant_presets["PN"])

    # Sliders
    st.session_state["survival"] = st.slider("Survival Percentage", 40, 90, preset["survival"])
    st.session_state["si"] = st.slider("Site Index", 96, 137, preset["si"])

    st.markdown("🌲 Species Mix (TPA)")
    st.session_state["tpa_df"] = st.slider("Douglas Fir", 0, 435, preset["tpa_df"])
    st.session_state["tpa_rc"] = st.slider("Red Cedar", 0, 436 - st.session_state["tpa_df"], preset["tpa_rc"])
    st.session_state["tpa_wh"] = st.slider("Western Hemlock", 0, 437 - st.session_state["tpa_df"] - st.session_state["tpa_rc"], preset["tpa_wh"])
    st.markdown(f"Total TPA: {st.session_state['tpa_df'] + st.session_state['tpa_rc'] + st.session_state['tpa_wh']}")

# @st.fragment
def carbon_chart_fragment():
    # Ensure the sliders have been set
    if not all(k in st.session_state for k in ["tpa_df", "tpa_rc", "tpa_wh", "survival", "si"]):
        st.info("Adjust sliders above to see the carbon output.")
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
map_tab, plant_tab = st.tabs(["Site Selection Map", "Planting Sliders and Carbon Charts"])

# Load Shapefile / GeoJSON
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")

st.set_page_config(layout="wide", page_title="Site Selection and Planting Scenario", page_icon="🌲")

with map_tab:
    st.title("🌲 Site Selection")
    st.subheader("Select FVS Variant")

    geojson_str, tooltip_fields = load_geojson_fragment(simplified_geojson, local_shapefile)
    st.session_state.setdefault("map_view", {"center": [37.8, -96.9], "zoom": 5})

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

    with st.form("map_select_form"):
        submitted = st.form_submit_button("Select Variant")
        if submitted:
            if "selected_variant" in st.session_state:
                st.success(f"Selected Variant: {st.session_state['selected_variant']}")
            else:
                st.info("Click a feature on the map first.")

with plant_tab:
    st.title("🌲 Planting Scenario")
    st.subheader("Planting Scenario")
    run_chart()
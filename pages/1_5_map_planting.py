import streamlit as st
import json
import pandas as pd
import os
import numpy as np
import geopandas as gpd
import folium
from pathlib import Path
from streamlit_folium import st_folium
import altair as alt

st.set_page_config(layout="wide", page_title="Site Selection & Planting Scenario", page_icon="🌲")
st.title("🌲 Site Selection & Planting Scenario")

# -----------------------------
# Load Shapefile / GeoJSON
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")

@st.cache_data
def read_geojson_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")

@st.cache_data
def simplify_geojson(path: Path, tolerance_deg: float = 0.001) -> str:
    gdf = gpd.read_file(path)
    gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)
    keep = [c for c in ["FVSVariant", "FVSVarName", "FVSLocName"] if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]] if keep else gdf[["geometry"]]
    return gdf.to_json(na="drop")

# Load GeoJSON
if os.path.exists(simplified_geojson):
    geojson_str = read_geojson_text(simplified_geojson)
    # Optionally infer fields from the first feature for tooltips:
    try:
        feat0_props = json.loads(geojson_str)["features"][0]["properties"]
        st.success(f'GeoJSON loaded successfully')
        tooltip_fields = list(feat0_props.keys())[:3]  # keep it light
    except Exception:
        tooltip_fields = None
else:
    try:
        geojson_str = simplify_geojson(local_shapefile, tolerance_deg=0.001)
        try:
            feat0_props = json.loads(geojson_str)["features"][0]["properties"]
            tooltip_fields = list(feat0_props.keys())[:3] 
        except Exception:
            tooltip_fields = None
    except Exception as e:
        st.error(f"Failed to load shapefile: {e}")
        st.stop()

# -----------------------------
# Build the map
# -----------------------------
def build_map(geojson_str, center=(37.8, -96.9), zoom=5, tooltip_fields=None):
    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB positron")
    gj = folium.GeoJson(
        data=geojson_str,
        name="FVS Variants",
        style_function=lambda x: {"fillColor": "blue", "color": "black", "weight": 1, "fillOpacity": 0.3},
        highlight_function=lambda x: {"fillColor": "yellow", "color": "red", "weight": 2, "fillOpacity": 0.6},
    )
    if tooltip_fields:
        gj.add_child(folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_fields, sticky=True))
    gj.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    return m

# Infer tooltip fields
try:
    feat0_props = json.loads(geojson_str)["features"][0]["properties"]
    tooltip_fields = list(feat0_props.keys())[:3]
except Exception:
    tooltip_fields = None

# Render map
st.subheader("Step 1: Select FVS Variant")
st.session_state.setdefault("map_view", {"center": [37.8, -96.9], "zoom": 5})
m = build_map(geojson_str, center=tuple(st.session_state["map_view"]["center"]), zoom=int(st.session_state["map_view"]["zoom"]), tooltip_fields=tooltip_fields)
map_data = st_folium(m, key="fvs_map", height=500, use_container_width=True)

# Capture clicked variant
if map_data and map_data.get("last_active_drawing"):
    clicked = map_data["last_active_drawing"].get("properties", {})
    if clicked:
        st.session_state["selected_variant"] = clicked.get("FVSVariant", "PN")
        st.subheader("Selected Feature Info")
        # Define mapping for display names
        pretty_names = {
            "FVSLocCode": "FVS Location Code",
            "FVSLocName": "FVS Location Name",
            "FVSVarName": "FVS Variant Name",
            "FVSVariant": "FVS Variant",
        }

        # Filter out unwanted keys
        skip_keys = {"Shape_Area", "Shape_Leng"}

        for key, value in clicked.items():
            if key in skip_keys:
                continue
            display_key = pretty_names.get(key, key)  # use mapping if available
            st.markdown(f"**{display_key}:** {value}")

# -----------------------------
# Planting Scenario
# -----------------------------
st.subheader("Step 2: Planting Scenario")

# Variant presets (fixed placeholder values)
variant_options = [
    "AK","BM","CA","CI","CR","CS","EC","EM","IE","LS","NC",
    "NE","PN","SN","SO","TT","UT","WC","WS"
]
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

# Use selected variant
variant = st.session_state.get("selected_variant", "PN")
st.markdown(f"**FVS Variant:** {variant}")
preset = variant_presets.get(variant, variant_presets["PN"])

# Sliders
survival = st.slider("Survival Percentage", 40, 90, preset["survival"])
si = st.slider("Site Index", 96, 137, preset["si"])

st.subheader("🌲 Species Mix (TPA)")
tpa_df = st.slider("Douglas Fir", 0, 435, preset["tpa_df"])
tpa_rc = st.slider("Red Cedar", 0, 436 - tpa_df, preset["tpa_rc"])
tpa_wh = st.slider("Western Hemlock", 0, 437 - tpa_df - tpa_rc, preset["tpa_wh"])
tpa_total = tpa_df + tpa_rc + tpa_wh
st.markdown(f"Total TPA: {tpa_total}")

# Carbon Score Calculation
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

st.success(f"Final Carbon Output (year {max(df['Year'])}): {df['C_Score'].iloc[-1]:.2f}")
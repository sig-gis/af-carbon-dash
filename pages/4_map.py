import streamlit as st
import geopandas as gpd
import folium
import os
from streamlit_folium import st_folium

st.set_page_config(layout="wide")
st.title("Local Shapefile + Streamlit")

# -------------------------
# Load Shapefile
# -------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")

try:
    gdf = gpd.read_file(local_shapefile)
    st.success("Shapefile loaded successfully")
except Exception as e:
    st.error(f"Error loading shapefile: {e}")
    gdf = None
# -------------------------
# Map
# -------------------------
if gdf is not None:
    m = folium.Map(zoom_start=10)

    def style_function(x):
        return {
            "fillColor": "blue",
            "color": "black",
            "weight": 1,
            "fillOpacity": 0.3,
        }

    def highlight_style(x):
        return {
            "fillColor": "yellow",
            "color": "red",
            "weight": 2,
            "fillOpacity": 0.6,
        }

    # Add GeoJson with popup for click events
    folium.GeoJson(
        gdf,
        name="FVS Variants",
        style_function=style_function,
        highlight_function=highlight_style,
        tooltip=folium.GeoJsonTooltip(
            fields=[c for c in gdf.columns if c != "geometry"],
            aliases=[c for c in gdf.columns if c != "geometry"],
            sticky=True,
        ),
        popup=folium.GeoJsonPopup(
            fields=[c for c in gdf.columns if c != "geometry"],
            aliases=[c for c in gdf.columns if c != "geometry"],
        )
    ).add_to(m)

    folium.LayerControl().add_to(m)

    # Capture map interactions
    map_data = st_folium(m, use_container_width=True, height=600)

    # -------------------------
    # Show clicked feature info
    # -------------------------
    if map_data and map_data.get("last_active_drawing"):
        clicked = map_data["last_active_drawing"]["properties"]
        st.subheader("Selected Feature Info")
        st.json(clicked)
import json
import os
from pathlib import Path
import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium

st.set_page_config(layout="wide", page_title="Site Selection Map", page_icon="🗺️")
st.title("🗺️ Site Selection Map")

st.markdown("""
### Where is your project?
            
The map below shows FVS Variant Locations. Select the Location which includes the majority of your project.

Your selection will give you a head start designing your 🌲 Planting Scenario by 
            selecting the appropriate FVS variant, 
            presetting reasonable defaults for Site Index, 
            and narowing down the species mix options.
            
You can still adjust these parameters manually in the 🌲 Planting Scenario page.
""")


# -------------------------------------------------
# Load Shapefile
# -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
# placeholder for a pre-simplified geojson file to speed up loading
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")


# Caching helps with performance
@st.cache_data(show_spinner=False)
def read_geojson_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")

@st.cache_data(show_spinner=False)
def simplify_geojson(path: Path, tolerance_deg: float = 0.001) -> str:
    """
    Fallback if simplified file doesn't exist.
    NOTE: This simplifies in degrees (WGS84); TODO: replace with precomputed simplified geojson.
    """
    gdf = gpd.read_file(path)
    gdf = gdf.copy()
    gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)
    # Keep just a couple fields to shrink payload; adjust to your schema
    keep = [c for c in ["FVSVariant", "FVSVarName", "FVSLocName"] if c in gdf.columns]
    gdf = gdf[keep + ["geometry"]] if keep else gdf[["geometry"]]
    return gdf.to_json(na="drop")

def build_map(geojson_str: str, center=(37.8, -96.9), zoom=5,
              tooltip_fields=None, tooltip_aliases=None) -> folium.Map:
    """Build a fresh folium.Map every run (cheap since geojson_str is cached)."""
    m = folium.Map(location=center, zoom_start=zoom, tiles="CartoDB positron")

    gj = folium.GeoJson(
        data=geojson_str,
        name="FVS Variants",
        style_function=lambda x: {"fillColor": "blue", "color": "black", "weight": 1, "fillOpacity": 0.3},
        highlight_function=lambda x: {"fillColor": "yellow", "color": "red", "weight": 2, "fillOpacity": 0.6},
    )
    if tooltip_fields:
        gj.add_child(folium.GeoJsonTooltip(fields=tooltip_fields,
                                           aliases=(tooltip_aliases or tooltip_fields),
                                           sticky=True))
    gj.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m

# -------------------------------------------------
# Load GeoJSON (prefer pre-simplified file)
# -------------------------------------------------
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

# -------------------------------------------------
# Map
# -------------------------------------------------
st.session_state.setdefault("map_view", {"center": [37.8, -96.9], "zoom": 5})

# Build a map
m = build_map(
    geojson_str,
    center=tuple(st.session_state["map_view"]["center"]),     # [lat, lng] -> (lat, lng)
    zoom=int(st.session_state["map_view"]["zoom"]),           # ensure int
    tooltip_fields=tooltip_fields,
)

# Render with a stable key to avoid remount thrash
map_data = st_folium(m, key="fvs_map", use_container_width=True, height=600)

# Attempt to Persist view state (center/zoom) so the map feels sticky
# Save latest center/zoom for next rerun
if map_data:
    c = map_data.get("center")
    if isinstance(c, dict) and c:
        st.session_state["map_view"]["center"] = [
            float(c.get("lat", 37.8)),
            float(c.get("lng", -96.9)),
        ]

    z = map_data.get("zoom")
    if z is not None:
        st.session_state["map_view"]["zoom"] = int(z)

# Optional: show clicked feature props
if map_data and map_data.get("last_active_drawing"):
    clicked = map_data["last_active_drawing"].get("properties", {})
    if clicked:
        st.subheader("Selected Feature Info")
        st.json(clicked)

        variant_value = clicked.get("FVSVariant")
        if variant_value:
            st.session_state["selected_variant"] = variant_value
            st.success(f"Variant '{variant_value}' selected! Go to the 🌲 Planting Scenario page.")

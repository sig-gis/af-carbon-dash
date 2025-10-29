import socket
import threading
import nest_asyncio
import uvicorn
from fastapi import FastAPI
from titiler.core.factory import TilerFactory
from starlette.middleware.cors import CORSMiddleware
import streamlit as st
import folium
from streamlit_folium import st_folium
from rio_tiler.io import COGReader
from pyproj import Transformer
from branca.element import Template, MacroElement

PORT = 8000
HOST = "127.0.0.1"
BASE = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
DATASET = "sentinel-s2-l2a-cogs"
# -------------------------------
# Function to check if port is in use
# -------------------------------
@st.fragment()
def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        try:
            s.connect((host, port))
            return True
        except (ConnectionRefusedError, OSError):
            return False

# -------------------------------
# Start TiTiler only if not running
# -------------------------------
if not is_port_open(HOST, PORT):
    app = FastAPI()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    cog = TilerFactory()
    app.include_router(cog.router, tags=["Cloud Optimized GeoTIFF"])

    @app.get("/")
    def read_index():
        return {"message": "Welcome to TiTiler"}

    nest_asyncio.apply()

    def run_titiler():
        uvicorn.run(app, host=HOST, port=PORT)

    thread = threading.Thread(target=run_titiler, daemon=True)
    thread.start()
    st.write(f"TiTiler server started at http://{HOST}:{PORT}")
else:
    st.write(f"TiTiler already running at http://{HOST}:{PORT}")

@st.cache_data()
def get_cog_bounds(url):
    with COGReader(url) as cog:
        bounds = cog.bounds
        src_crs = cog.crs
    return bounds, src_crs

@st.cache_data()
def transform_bounds(bounds, _src_crs):
    transformer = Transformer.from_crs(_src_crs, "EPSG:4326", always_xy=True)
    min_lon, min_lat = transformer.transform(bounds[0], bounds[1])
    max_lon, max_lat = transformer.transform(bounds[2], bounds[3])
    return min_lon, min_lat, max_lon, max_lat

@st.cache_data()
def getLatLon(min_lon, min_lat, max_lon, max_lat):
    center_lat = (min_lat + max_lat) / 2
    center_lon = (min_lon + max_lon) / 2
    return center_lat, center_lon
# -------------------------------
# Streamlit UI
# -------------------------------
st.set_page_config(layout="wide", page_title="Dynamic COG Viewer")

st.sidebar.header("🛰️ COG Layer Controls")

# Year selector (only part being varied)
utm = st.sidebar.selectbox("Select UTM", [36, 37, 38], index=2)
add_layer = st.sidebar.button("Add Sentinel-2 Layer")

# -------------------------------
# Initialize map (once)
# -------------------------------
if "map" not in st.session_state:
    # Initial view can be anything; we'll recenter when a layer is added
    st.session_state.map = folium.Map(location=[35.5, -80], zoom_start=7)
    st.session_state.layers = set()

# -------------------------------
# Add layer dynamically
# -------------------------------
if add_layer:
    cog_url = f"{BASE}/{DATASET}/{utm}/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif"
    tile_url = f"http://{HOST}:{PORT}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={cog_url}"

    bounds, src_crs = get_cog_bounds(cog_url)
    min_lon, min_lat, max_lon, max_lat = transform_bounds(bounds, src_crs)
    center_lat, center_lon = getLatLon(min_lon, min_lat, max_lon, max_lat)
    bounds_coords = [[min_lat, min_lon], [max_lat, max_lon]]

    layer_name = f"Sentinel-2 {utm}"

    if layer_name not in st.session_state.layers:
        folium.TileLayer(
            tiles=tile_url,
            attr="Sentinel-2 via local TiTiler",
            name=layer_name,
            overlay=True,
            control=True
        ).add_to(st.session_state.map)

        folium.Rectangle(
            bounds=bounds_coords,
            color="red",
            weight=2,
            fill=False,
            popup=f"{layer_name} Bounds"
        ).add_to(st.session_state.map)

        st.session_state.layers.add(layer_name)

        # Recenter map
        st.session_state.map.location = [center_lat, center_lon]
        st.session_state.map.zoom_start = 10

        legend_template_cat = """
            {% macro html(this, kwargs) %}
            <div id='maplegend_cat' class='maplegend' 
                style='position: absolute; z-index: 9999; background-color: rgba(255, 255, 255, 0.5);
                border-radius: 6px; padding: 10px; font-size: 10.5px; right: 20px; top: 20px;'>     
            <div class='legend-scale'>
            <ul class='legend-labels'>
                <li><span style='background: green; opacity: 0.75;'></span>Wind speed <= 55.21</li>
                <li><span style='background: yellow; opacity: 0.75;'></span>55.65 <= Wind speed <= 64.29</li>
                <li><span style='background: orange; opacity: 0.75;'></span>64.50 <= Wind speed <= 75.76</li>
                <li><span style='background: red; opacity: 0.75;'></span>75.90 <= Wind speed <= 90.56</li>
                <li><span style='background: purple; opacity: 0.75;'></span>Wind speed >= 91.07</li>
            </ul>
            </div>
            </div> 
            <style type='text/css'>
            .maplegend .legend-scale ul {margin: 0; padding: 0; color: #0f0f0f;}
            .maplegend .legend-scale ul li {list-style: none; line-height: 18px; margin-bottom: 1.5px;}
            .maplegend ul.legend-labels li span {float: left; height: 16px; width: 16px; margin-right: 4.5px;}
            </style>
            {% endmacro %}
            """
        
        legend_template_con = """
            {% macro html(this, kwargs) %}
            <div id='maplegend-con' class='maplegend'
                style='position: absolute; z-index:9999; background-color: rgba(255,255,255,0.7);
                border-radius:6px; padding:5px; font-size:10.5px; right:20px; top:140px;'>     

            <div class='legend-title'>Wind Speed (m/s)</div>

            <!-- Legend container -->
            <div class='legend-row'>
            <span class='legend-min'>≤ 55</span>
            <div class='legend-bar'></div>
            <span class='legend-max'>90+</span>
            </div>

            </div>

            <style type='text/css'>
            .maplegend .legend-title {
                text-align: left;
                margin-bottom: 5px;
                font-weight: bold;
                font-size: 11px;
            }

            .maplegend .legend-row {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 6px;
            }

            .maplegend .legend-bar {
                height: 12px;
                width: 120px;
                background: linear-gradient(to right, green, yellow, orange, red, purple);
                border-radius: 3px;
            }

            .maplegend .legend-min,
            .maplegend .legend-max {
                font-size: 10px;
                color: #0f0f0f;
                min-width: 25px;
                text-align: center;
            }
            </style>
            {% endmacro %}
            """

        macro_cat = MacroElement()
        macro_cat._template = Template(legend_template_cat)

        macro_con = MacroElement()
        macro_con._template = Template(legend_template_con)

        st.session_state.map.get_root().add_child(macro_cat)
        st.session_state.map.get_root().add_child(macro_con)
# -------------------------------
# Display the map
# -------------------------------
st_folium(st.session_state.map, width=1200, height=800, use_container_width=True)
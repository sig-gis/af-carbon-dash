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

PORT = 8000
HOST = "127.0.0.1"

# -------------------------------
# Function to check if port is in use
# -------------------------------
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

# -------------------------------
# Folium Map
# -------------------------------
cog_url = "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/36/Q/WD/2020/7/S2A_36QWD_20200701_0_L2A/TCI.tif"
tile_url = f"http://{HOST}:{PORT}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={cog_url}"

with COGReader(cog_url) as cog:
    bounds = cog.bounds  # (left, bottom, right, top)
    src_crs = cog.crs    # could be UTM

# Transform bounds to EPSG:4326
transformer = Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
min_lon, min_lat = transformer.transform(bounds[0], bounds[1])
max_lon, max_lat = transformer.transform(bounds[2], bounds[3])

# Center coordinates
center_lat = (min_lat + max_lat) / 2
center_lon = (min_lon + max_lon) / 2

m = folium.Map(location=[center_lat, center_lon], zoom_start=10)

folium.TileLayer(
    tiles=tile_url,
    attr="Sentinel-2 via local TiTiler",
    name="Sentinel-2 TCI",
    overlay=True,
    control=True
).add_to(m)

folium.LayerControl().add_to(m)

st.set_page_config(layout="wide")
st_folium(m, width=1200, height=800, use_container_width=True)
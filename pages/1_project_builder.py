import streamlit as st
import folium
from streamlit_folium import st_folium
import json
import geopandas as gpd
import os
import tempfile
import numpy as np
from pathlib import Path
from shapely.geometry import shape, Point, box
import zipfile
from geopy.geocoders import Nominatim

from utils.functions.helper import  H
from utils.functions.site_select import load_geojson_fragment, load_geojson_or_shapefile, build_map, show_clicked_variant, display_selected_info
from utils.functions.plant_design import run_chart

# Page Configuration
st.set_page_config(layout="wide", page_title="Project Builder", page_icon="🌲")

# Initialize Session State 
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Site Selection Map"

# File Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")

# Sidebar: Project Workflow
st.sidebar.markdown("## Project Workflow")

with open(os.path.join(BASE_DIR, "conf/base/workflow_steps.json"), "r", encoding="utf-8") as f:
    workflow_steps = json.load(f)

# Custom CSS for sidebar step styling
st.sidebar.markdown("""
    <style>
    .workflow-step {
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
    }
    .active-step {
        background-color: #dffde9; /* light green background */
        border-left: 5px solid #177233; /* green accent bar */
        font-weight: 600;
        color: #177233;
    }
    .inactive-step {
        color: #555;
    }
    </style>
""", unsafe_allow_html=True)

# Render each step with highlight plus caption under the correct one
for step in workflow_steps:
    is_active = st.session_state.active_tab == step["tab"]
    step_class = "active-step" if is_active else "inactive-step"

    # Step title
    st.sidebar.markdown(
        f'<div class="workflow-step {step_class}">{step["label"]}</div>',
        unsafe_allow_html=True
    )

    # Step caption (only for the active step), split by line
    if is_active:
        for line in step["caption"].split("\n"):
            if line.strip():  # skip empty lines
                st.sidebar.caption(line.strip())

st.sidebar.markdown("---")
st.sidebar.info("Having Trouble? Visit the FAQ page above for more information.")

if st.session_state.active_tab == "Site Selection Map":
    col1, col2 = st.columns([8, 3])

    with col1:
        st.title(
            "🗺️ Site Selection",
            anchor=None,
            help=H("site.title"),
        )

    with col2:
        # Only show the "Continue" button if a variant is selected
        if st.session_state.get("selected_variant"):
            if st.button(
                "➡️ Planting Design",
                use_container_width=True,
                help=H("site.button_forward_to_planting"),
                type='primary'
            ):
                st.session_state.active_tab = "Planting Design"
                st.rerun()
        else:
            st.empty()

    if "points" not in st.session_state:
        st.session_state.points = []

    if "upload_file" not in st.session_state:
        st.session_state.upload_file = []
        
    with st.expander(label="Add Point by latitude/longitude or look up an address", expanded=False):
        st.subheader("Go to Lat/Lon") 
        col1, col2, col3, col4, col5, col6, col7, col8, col9, col10 = st.columns([1, 1, 1, 1, 1, 1, 1, 1, 1, 1])

        with col1:
            lat = st.number_input("Latitude", value=45.5, format="%.3f", help=None, width=200)
        with col2:
            lon = st.number_input("Longitude", value=-118.0, format="%.3f", help=None, width=200)

        add_point_button = st.button("Add Point to Map")

        st.subheader("Go to Address")        
        col1_r2, col2_r2, col3_r2, col4_r2, col5_r2, col6_r2, col7_r2, col8_r2, col9_r2 = st.columns([1, 1, 1, 1, 1, 1, 1, 1, 1])

        with col1_r2:
            street = st.text_input("Street Address")
        with col2_r2:
            city = st.text_input("City/Town")
        with col3_r2:
            state = st.text_input("State")
        
        go_address_button = st.button("Go to Address")

    if add_point_button:
        new_pt = Point(lon, lat)
        st.session_state.points.append(new_pt)

        # Track this as the last added type
        st.session_state["last_added_type"] = "point"
        st.session_state["last_point"] = new_pt

    # Geocode address if button pressed
    if go_address_button:
        full_address = ", ".join(filter(None, [street, city, state]))
        if full_address:
            geolocator = Nominatim(user_agent="streamlit_map_app")
            location = geolocator.geocode(full_address)
            if location:
                new_pt = Point(location.longitude, location.latitude)
                st.session_state.points.append(new_pt)

                # Track last added
                st.session_state["last_added_type"] = "point"
                st.session_state["last_point"] = new_pt
            else:
                st.error("Address not found.")
        else:
            st.error("Enter at least one field for address, city, or state.")

    with st.expander(label="Upload GeoJSON/Shapefile", expanded=False):
        uploaded_files = st.file_uploader(
            "Upload GeoJSON or all shapefile components seperatly (.shp, .shx, .dbf, .prj, .cpg) or zipped (.zip)",
            accept_multiple_files=True,
            type=["geojson", "shp", "shx", "dbf", "prj", "cpg", "zip"],
            width = 600
        )

        upload_button = st.button("Upload file to map")
        reset_button = st.button("Reset file uploads")

    if upload_button:
        for key in ["upload_file", "uploaded_geojson_str", "uploaded_tooltip_fields"]:
            if key in st.session_state:
                del st.session_state[key]

        if uploaded_files:
            if len(uploaded_files) == 1 and uploaded_files[0].name.lower().endswith(".zip"):
                st.write("ZIP file detected!")
                uploaded_file = uploaded_files[0]

                tmpdir = tempfile.mkdtemp()

                zip_path = os.path.join(tmpdir, uploaded_file.name)
                with open(zip_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(tmpdir)

                extracted_files = os.listdir(tmpdir)
                print("Extracted files:", extracted_files)

                extracted_full_paths = [os.path.join(tmpdir, f) for f in extracted_files]

                target = next((f for f in extracted_full_paths if f.lower().endswith((".shp", ".geojson"))), None)
                if target:
                    st.session_state.upload_file = [target]  # Wrap in list to match function signature
                else:
                    st.error("No .shp or .geojson file found inside ZIP.")
            else:
                st.write("Not a ZIP file or multiple files uploaded.")
                st.session_state.upload_file = uploaded_files
        
    uploaded_geojson_str, uploaded_tooltip_fields = None, None
    if st.session_state.upload_file:
        uploaded_geojson_str, uploaded_tooltip_fields = load_geojson_or_shapefile(
            st.session_state.upload_file
        )

        # Track last added
        st.session_state["last_added_type"] = "upload"
        st.session_state["last_upload"] = uploaded_geojson_str

    st.subheader(
        "Select FVS Variant",
        anchor=None,
        divider=False,
        help=H("site.subheader_select_variant")
    )

    # Load GeoJSON and Map
    geojson_str, tooltip_fields = load_geojson_fragment(simplified_geojson, local_shapefile)
    st.session_state.setdefault("map_view", {"center": [45.5, -118], "zoom": 6})

    m = build_map(
        geojson_str,
        points=st.session_state.points,
        upload = uploaded_geojson_str,
        center=tuple(st.session_state["map_view"]["center"]),
        zoom=int(st.session_state["map_view"]["zoom"]),
        tooltip_fields=tooltip_fields,
        highlight_feature=st.session_state.get("clicked_feature")
    )

    map_data = st_folium(
        m,
        key="fvs_map",
        height=500,
        use_container_width=True,
    )

    show_clicked_variant(map_data)
    display_selected_info()

    if reset_button:
        # Remove from session state
        for key in ["upload_file", "uploaded_geojson_str", "uploaded_tooltip_fields"]:
            if key in st.session_state:
                del st.session_state[key]
        
        st.rerun()
else:

    col1, col2 = st.columns([8, 3]) 

    with col1:
        st.title("🌲 Planting Design", anchor=None, help=H("planting.title"))

    with col2:
        if st.button("⬅️ Site Selection", use_container_width=True, help=H("planting.button_back_to_site"), type='primary'):
            st.session_state.active_tab = "Site Selection Map"
            st.rerun()

    run_chart()

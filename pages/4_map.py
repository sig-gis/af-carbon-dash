import streamlit as st
import ee
import geemap.foliumap as geemap
from streamlit_folium import st_folium
import geopandas as gpd
import folium
import tempfile, zipfile, os, sys

# -------------------------
# Initialize Earth Engine
# -------------------------
try:
    ee.Initialize()
except Exception:
    ee.Authenticate()
    ee.Initialize()

st.set_page_config(layout="wide")
st.title("Earth Engine Zonal Analysis + Streamlit")

# -------------------------
# Functions
# -------------------------
def add_legend(m, title, colors, labels):
    """Add a legend to a folium map with black text."""
    legend_html = f"""
     <div style="
     position: fixed; 
     bottom: 50px; left: 50px; width: 150px; height: {40 + 25*len(colors)}px; 
     border:2px solid black; z-index:9999; font-size:14px;
     background-color:white;
     padding: 10px;
     color: black;
     ">
     <b>{title}</b><br>
    """
    for color, label in zip(colors, labels):
        legend_html += f"""
        <i style="background:{color};width:18px;height:18px;float:left;margin-right:8px;opacity:0.7;"></i>
        <span style="color: black;">{label}</span><br>
        """
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

# -------------------------
# Session State
# -------------------------
for key in ["geometry", "zonal_stats", "state_stats", "selected_state", "uploaded_geom"]:
    if key not in st.session_state:
        st.session_state[key] = None

# -------------------------
# US states dataset (EE)
# -------------------------
state_fc = ee.FeatureCollection("TIGER/2018/States")
state_list = state_fc.aggregate_array("NAME").getInfo()

# -------------------------
# Layout
# -------------------------
col_panel, col_map = st.columns([1, 3])

# -------------------------
# Right Panel
# -------------------------
with col_panel:
    st.header("Zonal Analysis Options")

    # Determine which modes are active
    has_upload = st.session_state.uploaded_geom is not None
    has_state = st.session_state.selected_state is not None
    has_draw = st.session_state.geometry is not None

    # ---- State Selection ----
    st.subheader("State Zonal Stats")
    disabled_state = has_upload or has_draw

    # Determine default value for selectbox
    default_state = st.session_state.selected_state if st.session_state.selected_state else "--None--"

    options = ["--None--"] + state_list

    # Determine index
    if default_state == "--None--" or default_state not in state_list:
        default_index = 0
    else:
        default_index = options.index(default_state)

    selected_state = st.selectbox(
        "Select a state",
        options,
        index=default_index,
        disabled=disabled_state
    )

    # Only update session state if a valid selection
    if selected_state != "--None--" and not disabled_state:
        st.session_state.selected_state = selected_state
    elif not disabled_state:
        st.session_state.selected_state = None

    # ---- Upload Geometry ----
    st.subheader("Upload Geometry")
    disabled_upload = has_state or has_draw
    uploaded_file = st.file_uploader(
        "Upload Shapefile (.zip), GeoJSON (.geojson), or KML (.kml)",
        type=["zip", "geojson", "kml"],
        disabled=disabled_upload
    )

    if uploaded_file is not None and not disabled_upload:
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.read())

            gdf = None
            try:
                if uploaded_file.name.endswith(".zip"):
                    with zipfile.ZipFile(file_path, "r") as zip_ref:
                        zip_ref.extractall(tmpdir)
                    shp_files = [f for f in os.listdir(tmpdir) if f.endswith(".shp")]
                    if shp_files:
                        gdf = gpd.read_file(os.path.join(tmpdir, shp_files[0]))
                else:
                    gdf = gpd.read_file(file_path)

                if gdf is not None and not gdf.empty:
                    gdf = gdf.to_crs(epsg=4326)
                    geojson = gdf.__geo_interface__
                    st.session_state.uploaded_geom = geojson
                    st.success("Uploaded file processed successfully.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    # ---- Reset Button ----
    if st.button("Reset Map"):
        for key in ["geometry", "zonal_stats", "state_stats", "selected_state", "uploaded_geom"]:
            st.session_state[key] = None
        # Streamlit will rerun automatically


# -------------------------
# Map & Zonal Stats
# -------------------------
with col_map:
    dataset = ee.Image("CGIAR/SRTM90_V4")

    # Default map center
    center = [39.5, -98.35]
    zoom = 5
    dataset_clipped = dataset
    geom_state = None

    # Determine which geometry to use
    if st.session_state.uploaded_geom:
        geom = ee.Geometry(st.session_state.uploaded_geom["features"][0]["geometry"])
        dataset_clipped = dataset.clip(geom)
        center = geom.centroid().coordinates().getInfo()[::-1]
        zoom = 6
    elif st.session_state.selected_state:
        state_feat = state_fc.filter(ee.Filter.eq("NAME", st.session_state.selected_state)).first()
        geom_state = state_feat.geometry()
        dataset_clipped = dataset.clip(geom_state)
        center = geom_state.centroid().coordinates().getInfo()[::-1]
        zoom = 6

    # Visualization
    vis_params = {"min": 0, "max": 3000, "palette": ["blue", "green", "yellow", "red"]}
    m = geemap.Map(center=center, zoom=zoom, draw_export=True)
    m.addLayer(dataset_clipped, vis_params, "Elevation")
    m.addLayer(state_fc.style(**{"color": "black", "fillColor": "00000000"}), {}, "US States")

    # Define legend colors and labels
    palette = ["blue", "green", "yellow", "red"]
    labels = ["0-750 m", "751-1500 m", "1501-2250 m", "2251-3000 m"]

    # Add legend to map
    add_legend(m, "Elevation (m)", palette, labels)

    # Uploaded geometry
    if st.session_state.uploaded_geom:
        folium.GeoJson(
            st.session_state.uploaded_geom,
            name="Uploaded Geometry",
            style_function=lambda x: {
                "fillColor": "none",
                "color": "blue",
                "weight": 2,
            },
        ).add_to(m)

    m.addLayerControl()

    # Handle drawn geometry (mutually exclusive)
    allow_draw = not has_state and not has_upload
    output = st_folium(m, use_container_width=True, height=600)
    if allow_draw and output and output.get("last_active_drawing"):
        geom_geojson = output["last_active_drawing"]["geometry"]
        if geom_geojson:
            st.session_state.geometry = geom_geojson

    # -------------------------
    # Zonal stats
    # -------------------------
    # Drawn polygon stats
    if st.session_state.geometry:
        geom = ee.Geometry(st.session_state.geometry)
        mean_dict = dataset.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=90,
            maxPixels=1e13
        )
        st.session_state.zonal_stats = mean_dict.getInfo()

    # State stats
    elif st.session_state.selected_state:
        mean_state = dataset.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom_state,
            scale=90,
            maxPixels=1e13
        )
        st.session_state.state_stats = mean_state.getInfo()

    # Uploaded polygon stats
    elif st.session_state.uploaded_geom:
        geom = ee.Geometry(st.session_state.uploaded_geom["features"][0]["geometry"])
        mean_upload = dataset.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=90,
            maxPixels=1e13
        )
        st.session_state.zonal_stats = mean_upload.getInfo()

# -------------------------
# Display Results
# -------------------------
with col_panel:
    st.subheader("Zonal Statistics")

    if st.session_state.zonal_stats:
        if st.session_state.geometry:
            st.write("**Drawn Geometry**")
        elif st.session_state.uploaded_geom:
            st.write("**Uploaded Geometry**")
        st.json(st.session_state.zonal_stats)
    elif st.session_state.state_stats:
        st.write(f"**State:** {st.session_state.selected_state}")
        st.json(st.session_state.state_stats)
    else:
        st.info("Draw a polygon, select a state, or upload a file to calculate stats.")
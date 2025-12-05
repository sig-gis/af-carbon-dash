import streamlit as st
import folium
import json
import geopandas as gpd
import os
import tempfile
import numpy as np
from pathlib import Path
import io
from shapely.geometry import shape, box

@st.fragment
def load_geojson_fragment(simplified_geojson_path, shapefile_path, tolerance_deg=0.001, skip_keys={"Shape_Area", "Shape_Leng"}, max_tooltip_fields=4):
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

@st.cache_data
def load_geojson_or_shapefile(uploaded_files, tolerance_deg=0.001,
                              skip_keys={"Shape_Area", "Shape_Leng"}, max_tooltip_fields=3):
    """Load either a GeoJSON, shapefile, or zipped folder containing either file type.
       Automatically checks CRS and reprojects to EPSG:4326 if needed.
    """

    # Normalize input: if single file, wrap in list
    if isinstance(uploaded_files, (str, bytes)):
        uploaded_files = [uploaded_files]

    # Try to detect a GeoJSON file
    geojson_file = next(
        (f for f in uploaded_files
         if (hasattr(f, "name") and f.name.lower().endswith(".geojson"))
         or (isinstance(f, str) and f.lower().endswith(".geojson"))),
        None
    )

    #  GEOJSON
    if geojson_file:
        if isinstance(geojson_file, str):
            with open(geojson_file, "r", encoding="utf-8") as f:
                geojson_str = f.read()
        else:
            geojson_str = geojson_file.getvalue().decode("utf-8")

        gdf = gpd.read_file(io.StringIO(geojson_str))

        # CRS handling
        if gdf.crs is None:
            st.warning("GeoJSON has no CRS defined. Assuming EPSG:4326.")
            gdf = gdf.set_crs("EPSG:4326")

        else:
            if gdf.crs.to_string() == "EPSG:4326":
                st.success("GeoJSON CRS is already EPSG:4326.")
            else:
                st.info(f"Reprojecting GeoJSON from {gdf.crs} to EPSG:4326...")
                gdf = gdf.to_crs("EPSG:4326")
                st.success("GeoJSON successfully reprojected to EPSG:4326.")

        gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)
        geojson_str = gdf.to_json(na="drop")

        st.success("GeoJSON file loaded successfully!")

    # SHAPEFILE
    else:
        with tempfile.TemporaryDirectory() as tmpdir:
            for f in uploaded_files:
                if isinstance(f, str):
                    fname = os.path.basename(f)
                    with open(os.path.join(tmpdir, fname), "wb") as out:
                        out.write(open(f, "rb").read())
                else:
                    with open(os.path.join(tmpdir, f.name), "wb") as out:
                        out.write(f.getbuffer())

            shp_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.lower().endswith(".shp")]
            if not shp_files:
                st.error("No .shp file found among uploaded files.")
                return None, None

            shp_path = shp_files[0]
            gdf = gpd.read_file(shp_path)

            # CRS handling
            if gdf.crs is None:
                st.warning("Shapefile has no CRS defined. Assuming EPSG:4326.")
                gdf = gdf.set_crs("EPSG:4326")

            else:
                if gdf.crs.to_string() == "EPSG:4326":
                    st.success("Shapefile CRS is already EPSG:4326.")
                else:
                    st.info(f"Reprojecting shapefile from {gdf.crs} to EPSG:4326...")
                    gdf = gdf.to_crs("EPSG:4326")
                    st.success("Shapefile successfully reprojected to EPSG:4326.")

            gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)

            # Keep selected fields
            keep = [c for c in ["FVSVariant", "FVSVarName", "FVSLocName"] if c in gdf.columns]
            gdf = gdf[keep + ["geometry"]] if keep else gdf[["geometry"]]

            geojson_str = gdf.to_json(na="drop")

            st.success("Shapefile loaded successfully!")

    # Extract tooltip fields
    try:
        feat0_props = json.loads(geojson_str)["features"][0]["properties"]
        tooltip_fields = [k for k in feat0_props.keys() if k not in skip_keys][:max_tooltip_fields]
    except Exception:
        tooltip_fields = None

    return geojson_str, tooltip_fields

@st.fragment
def build_map(geojson_str, points=None, upload=None, center=(37.8, -96.9), zoom=5, tooltip_fields=None, highlight_feature=None):
    """
    Build and return a Folium map. Determines center/zoom based on user
    interactions, filters base GeoJSON to uploaded geometry bounds, renders
    uploaded layers, highlights selected features, and places point markers.
    """
    # Determine map center based on last added
    last_center = None
    last_zoom = 5

    last_type = st.session_state.get("last_added_type", None)

    if last_type == "upload" and upload:
        try:
            if isinstance(upload, str):
                upload_json = json.loads(upload)
            else:
                upload_json = upload

            upload_bounds = None
            for feat in upload_json["features"]:
                geom = shape(feat["geometry"])
                if upload_bounds is None:
                    upload_bounds = geom.bounds
                else:
                    minx, miny, maxx, maxy = upload_bounds
                    ux_min, uy_min, ux_max, uy_max = geom.bounds
                    upload_bounds = (
                        min(minx, ux_min), min(miny, uy_min),
                        max(maxx, ux_max), max(maxy, uy_max)
                    )
            minx, miny, maxx, maxy = upload_bounds
            last_center = ((miny + maxy) / 2, (minx + maxx) / 2)
            last_zoom = 10
        except Exception:
            pass

    elif last_type == "point" and points:
        # Center on last clicked point
        last_point = points[-1]
        last_center = (last_point.y, last_point.x)
        last_zoom = 12

    # Fallbacks
    if last_center is None:
        if geojson_str:
            try:
                gjson = json.loads(geojson_str)
                feat0 = gjson["features"][0]["geometry"]["coordinates"]
                if isinstance(feat0[0], list):
                    last_center = (feat0[0][0][1], feat0[0][0][0])
                else:
                    last_center = (feat0[1], feat0[0])
            except Exception:
                last_center = (37.8, -96.9)
        else:
            last_center = (37.8, -96.9)

    m = folium.Map(location=last_center, zoom_start=last_zoom, tiles="CartoDB positron")

    filtered_geojson = geojson_str

    # Filter geojson_str to bounds of upload if provided
    if upload and geojson_str:
        try:
            if isinstance(upload, str):
                upload_json = json.loads(upload)
            else:
                upload_json = upload

            upload_bounds = None
            for feat in upload_json["features"]:
                geom = shape(feat["geometry"])
                if upload_bounds is None:
                    upload_bounds = geom.bounds
                else:
                    minx, miny, maxx, maxy = upload_bounds
                    ux_min, uy_min, ux_max, uy_max = geom.bounds
                    upload_bounds = (
                        min(minx, ux_min), min(miny, uy_min),
                        max(maxx, ux_max), max(maxy, uy_max)
                    )

            original_json = json.loads(geojson_str)
            minx, miny, maxx, maxy = upload_bounds
            bbox = box(minx, miny, maxx, maxy)

            filtered_features = [
                feat for feat in original_json["features"]
                if bbox.intersects(shape(feat["geometry"]))
            ]

            if not filtered_features:
                # No intersection: show full geojson and display a warning
                st.warning(
                    "Uploaded file geometry does not intersect any of the currently supported FVS variants."
                )
                filtered_geojson = geojson_str
            else:
                filtered_geojson = json.dumps({"type": "FeatureCollection", "features": filtered_features})
                st.success(
                    f"{len(filtered_features)} FVS variant(s) within bounds of uploaded geometry."
                )
                st.success(
                    f"Select the FVS variant that is best suited for your project and continue to the Planting Design."
                )

        except Exception as e:
            st.warning(f"Error: {e}.")
            st.warning(f"Showing currently supported FVS variants.")
            filtered_geojson = geojson_str

    # Add uploaded file
    if upload:
        folium.GeoJson(
            data=upload,
            name="Uploaded File",
            style_function=lambda x: {"fillColor": "green", "color": "black", "weight": 1, "fillOpacity": 0.3},
        ).add_to(m)

    # Add filtered base layer
    if filtered_geojson:
        gj = folium.GeoJson(
            data=filtered_geojson,
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

    # Add points
    if points:
        for pt in points:
            folium.Marker(location=[pt.y, pt.x], icon=folium.Icon(color="red")).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    return m

@st.fragment
def get_tooltip_fields(geojson_str, skip_keys={"Shape_Area", "Shape_Leng"}, max_fields=4):
    """
    Extract tooltip fields from a GeoJSON string, filtering out unwanted keys
    and limiting the number of fields displayed.
    """
    try:
        feat0_props = json.loads(geojson_str)["features"][0]["properties"]
        # Filter out unwanted keys
        tooltip_fields = [k for k in feat0_props.keys() if k not in skip_keys][:max_fields]
    except Exception:
        tooltip_fields = None
    return tooltip_fields

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
                st.session_state["FVSLocCode"] = _loccode_str(props.get("FVSLocCode"))
                st.rerun()

@st.fragment
def display_selected_info():
    """
    Display the selected variant's properties in the UI, filtering out internal
    fields and formatting readable labels.
    """
    if "clicked_props" in st.session_state:
        props = st.session_state["clicked_props"]

        # st.subheader("Selected Feature Info", anchor=None, help=H("site.subheader_selected_feature_info"), divider=False, width="stretch")
        pretty_names = {
            # "FVSLocCode": "FVS Location Code",
            # "FVSLocName": "FVS Location Name",
            # "FVSVarName": "FVS Variant Name",
            "FVSVariant": "FVS Variant",
        }
        skip_keys = {"Shape_Area", "Shape_Leng", 'FVSVariantLoc', 'FVSLocCode', 'FVSLocName', 'FVSVarName'}

        for key, value in props.items():
            if key not in skip_keys:
                display_key = pretty_names.get(key, key)
                st.success(f"Successfully selected **{display_key}:** {value}")
                # st.success(f"Please continue to Planting Design, or select a different variant.")

@st.fragment
def submit_map(map_data):
    """
    Update session state with the variant selected from the map and store its
    FVS variant code.
    """
    if map_data and map_data.get("last_active_drawing"):
        clicked = map_data["last_active_drawing"].get("properties", {})
        if clicked:
            st.session_state["selected_variant"] = clicked.get("FVSVariant", "PN")
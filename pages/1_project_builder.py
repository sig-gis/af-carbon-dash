import streamlit as st
import json
import pandas as pd
import os
import tempfile
import numpy as np
import geopandas as gpd
import folium
from pathlib import Path
from streamlit_folium import st_folium
from scipy.interpolate import make_interp_spline
import altair as alt
import numpy_financial as npf
from shapely.geometry import shape, Point
from shapely.geometry import shape, box
from geopy.geocoders import Nominatim
import tempfile
import zipfile

# -----------------------------
# Functions
# -----------------------------

# ---------- Help Text ----------
@st.cache_data
def load_help(path: str = "conf/base/help_text.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
    
# access HELP text
HELP = load_help()
def H(key: str) -> str:
    """
    Safe accessor for help text loaded from conf/base/helptext.json.
    Returns empty string if key is missing to avoid runtime errors.
    """
    entry = HELP.get(key)
    if isinstance(entry, dict) and "help" in entry:
        return entry["help"]
    return ""

# ---------- Site Selection Map ----------
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
# def load_geojson_or_shapefile(uploaded_files, tolerance_deg=0.001,
#                               skip_keys={"Shape_Area", "Shape_Leng"}, max_tooltip_fields=3):
#     geojson_file = next((f for f in uploaded_files if f.name.endswith(".geojson")), None)
#     if geojson_file:
#         geojson_str = geojson_file.getvalue().decode("utf-8")
#     else:
#         with tempfile.TemporaryDirectory() as tmpdir:
#             for f in uploaded_files:
#                 with open(os.path.join(tmpdir, f.name), "wb") as out:
#                     out.write(f.getbuffer())
#             shp_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.endswith(".shp")]
#             if not shp_files:
#                 st.error("No .shp file found among uploaded files.")
#                 return None, None
#             shp_path = shp_files[0]
#             gdf = gpd.read_file(shp_path)
#             gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)
#             keep = [c for c in ["FVSVariant", "FVSVarName", "FVSLocName"] if c in gdf.columns]
#             gdf = gdf[keep + ["geometry"]] if keep else gdf[["geometry"]]
#             geojson_str = gdf.to_json(na="drop")

#     try:
#         feat0_props = json.loads(geojson_str)["features"][0]["properties"]
#         tooltip_fields = [k for k in feat0_props.keys() if k not in skip_keys][:max_tooltip_fields]
#     except Exception:
#         tooltip_fields = None

#     return geojson_str, tooltip_fields

def load_geojson_or_shapefile(uploaded_files, tolerance_deg=0.001,
                              skip_keys={"Shape_Area", "Shape_Leng"}, max_tooltip_fields=3):
    """Load either a GeoJSON or Shapefile, supporting both Streamlit UploadedFile objects and file paths."""
    
    # Normalize input: if single file, wrap in list
    if isinstance(uploaded_files, (str, bytes)):
        uploaded_files = [uploaded_files]
    
    # Try to detect a GeoJSON file (either UploadedFile or path)
    geojson_file = next(
        (f for f in uploaded_files 
         if (hasattr(f, "name") and f.name.lower().endswith(".geojson")) 
         or (isinstance(f, str) and f.lower().endswith(".geojson"))),
        None
    )
    
    if geojson_file:
        if isinstance(geojson_file, str):
            # Local path
            with open(geojson_file, "r", encoding="utf-8") as f:
                geojson_str = f.read()
        else:
            # UploadedFile object
            geojson_str = geojson_file.getvalue().decode("utf-8")

    else:
        # Handle shapefiles (UploadedFile objects or file paths)
        with tempfile.TemporaryDirectory() as tmpdir:
            for f in uploaded_files:
                if isinstance(f, str):
                    # Copy from local path
                    fname = os.path.basename(f)
                    with open(os.path.join(tmpdir, fname), "wb") as out:
                        out.write(open(f, "rb").read())
                else:
                    # Copy from UploadedFile
                    with open(os.path.join(tmpdir, f.name), "wb") as out:
                        out.write(f.getbuffer())
            
            # Find shapefile inside tempdir
            shp_files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.lower().endswith(".shp")]
            if not shp_files:
                st.error("No .shp file found among uploaded files.")
                return None, None

            shp_path = shp_files[0]
            gdf = gpd.read_file(shp_path)
            gdf["geometry"] = gdf.geometry.simplify(tolerance_deg, preserve_topology=True)

            keep = [c for c in ["FVSVariant", "FVSVarName", "FVSLocName"] if c in gdf.columns]
            gdf = gdf[keep + ["geometry"]] if keep else gdf[["geometry"]]
            geojson_str = gdf.to_json(na="drop")

    # Extract tooltip fields
    try:
        feat0_props = json.loads(geojson_str)["features"][0]["properties"]
        tooltip_fields = [k for k in feat0_props.keys() if k not in skip_keys][:max_tooltip_fields]
    except Exception:
        tooltip_fields = None

    return geojson_str, tooltip_fields

@st.fragment
def build_map(
    geojson_str,
    points=None,
    upload=None,
    center=(37.8, -96.9),
    zoom=5,
    tooltip_fields=None,
    highlight_feature=None
):
    # Determine map center based on last added
    last_center = None
    last_zoom = 5

    last_type = st.session_state.get("last_added_type", None)

    if last_type == "upload" and upload:
        # Center on uploaded geometry
        try:
            if isinstance(upload, str):
                upload_json = json.loads(upload)
            else:
                upload_json = upload

            # Compute bounds
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

            # Compute bounds of uploaded features
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

            # Filter original GeoJSON
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
    if map_data and map_data.get("last_active_drawing"):
        clicked = map_data["last_active_drawing"].get("properties", {})
        if clicked:
            st.session_state["selected_variant"] = clicked.get("FVSVariant", "PN")

# ---------- Helper functions ----------
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

# ---------- Statefulness functions ----------
def _planting_keys():
    """
    Return list of planting session state keys
    """
    return [k for k in list(st.session_state.keys()) if k.startswith("tpa_") or k in ("survival", "si", "net_acres")]

def _carbon_units_keys() -> list[str]:
    """
    Return the set of session-state keys that should persist for the Carbon Units section.
    We keep this intentionally small to avoid backing up large result dataframes.
    """
    return ["carbon_units_protocols", "carbon_units_inputs"]

def _credits_keys(prefix: str = "credits_") -> list[str]:
    """
    Return all proforma input keys (prefixed) that should persist for the Credits section.
    Uses the JSON defaults as the source of truth for which keys exist.
    """
    defaults = _load_proforma_defaults()
    return [prefix + k for k in defaults.keys()]

def _init_planting_state(variant: str, preset: dict):
    """
    Seed/clear planting slider state ONLY when the selected variant changes.
    Otherwise, leave the user's inputs intact across page switches.
    """
    last_variant = st.session_state.get("_last_variant")
    if last_variant == variant:
        return  # nothing to do — don't reset user inputs

    for k in _planting_keys():
        st.session_state.pop(k, None)

    # Seed base defaults if missing
    st.session_state["survival"] = preset.get("survival", st.session_state.get("survival", 70))
    st.session_state["si"]       = preset.get("si",       st.session_state.get("si", 120))
    # net_acres input in planting params for organization (top of page), but not in FVSVariant_presets.json
    st.session_state["net_acres"] = st.session_state.get("net_acres", 10000)

    # Seed species defaults if missing
    for spk in _species_keys(preset):
        st.session_state.setdefault(spk, int(preset.get(spk, 0)))

    st.session_state["_last_variant"] = variant

def _init_carbon_units_state():
    """
    Initialize Carbon Units inputs ONLY if missing.
    Does NOT overwrite existing user selections.
    """
    # canonical default protocols
    default_protocols = ["ACR/CAR/VERRA"]

    # initialize the mapping dict used downstream
    if "carbon_units_inputs" not in st.session_state:
        st.session_state["carbon_units_inputs"] = {"protocols": default_protocols}

    # ensure the widget-backed list key exists as well
    if "carbon_units_protocols" not in st.session_state:
        st.session_state["carbon_units_protocols"] = st.session_state["carbon_units_inputs"].get("protocols", default_protocols)

def _backup_keys(keys, backup_name: str = "_planting_backup"):
    """
    Persist the current values for the given session-state keys to a small
    backup dict stored under `backup_name` in `st.session_state`.
    Helpful when Streamlit drops a widget's state when navigating back and forth between content. 

    Parameters
    ----------
    keys : Iterable[str]
        The session-state keys you want to persist (e.g., ["survival", "si", *species_keys]).
    backup_name : str, optional
        The session-state key under which the backup is stored. Default: "_planting_backup".

    Notes
    -----
    - Call this *after* rendering widgets so the latest user inputs are captured.
    - Only keys present in `st.session_state` are saved; missing keys are ignored.
    """
    backup = {}
    for k in keys:
        if k in st.session_state:
            # Cast to int for sliders; adapt if you have non-int widgets
            val = st.session_state[k]
            backup[k] = int(val) if isinstance(val, (int, float, str)) and str(val).isdigit() else val
    st.session_state[backup_name] = backup
    return backup

def _restore_backup(keys, backup_name: str = "_planting_backup"):
    """
    Restore any *missing* session-state keys from a previously saved backup.

    Parameters
    ----------
    keys : Iterable[str]
        The session-state keys you want to ensure are present (e.g., ["survival", "si", *species_keys]).
    backup_name : str, optional
        The session-state key where the backup dict is stored. Default: "_planting_backup".

    Behavior
    --------
    - If a key is already present in `st.session_state`, it is left untouched.
    - If a key is missing and present in the backup, it is restored from backup.
    - If no backup exists, this is a no-op.
    """
    backup = st.session_state.get(backup_name, {})
    if not backup:
        return

    for k in keys:
        if k not in st.session_state and k in backup:
            st.session_state[k] = backup[k]


# ---------- Planting Design ----------
def planting_sliders():
    presets = load_variant_presets()
    variant = st.session_state.get("selected_variant", "PN")

    if variant not in presets:
        st.warning(f"Variant '{variant}' not found in presets. Falling back to 'PN'.")
    preset = presets.get(variant, presets.get("PN", {}))

    st.markdown(f"**FVS Variant:** {variant}", unsafe_allow_html=False, help=H("planting.variant_label"), width="stretch")

    species_keys = _species_keys(preset)
    
    # restore any missing keys from previous interaction with page (in case widgets were unmounted on the other page)
    _restore_backup(["survival", "si", "net_acres", *species_keys])

    # Initialize presets ONLY if the variant truly changed
    _init_planting_state(variant, preset)  # must not overwrite existing keys unless variant changed

    # Render widgets (key only; no value) so existing state is used
    # net_acres input in planting params for organization (top of page), but not in FVSVariant_presets.json
    st.number_input(
    "Net Acres:",
    min_value=1,
    step=100,
    key="net_acres",
    help=H("number.inputs.acres")
    )
    st.slider("Survival Percentage", 40, 90, key="survival", help=H("planting.slider_survival"))
    st.slider("Site Index", 96, 137, key="si", help=H("planting.slider_si"))

    st.markdown("🌲 Species Mix (TPA)", unsafe_allow_html=False, help=H("planting.species_mix_header"), width="stretch")
    tpa_cap = preset.get("_tpa_cap", 435)
    for spk in species_keys:
        st.slider(_label_for(spk), 0, tpa_cap, key=spk)

    # Summary 
    total_tpa = sum(int(st.session_state.get(k, 0)) for k in species_keys)
    st.markdown(f"**Total TPA:** {total_tpa}", unsafe_allow_html=False, help=H("planting.total_tpa_label"), width="stretch")
    if total_tpa > tpa_cap:
        st.warning(f"Total initial TPA exceeds {tpa_cap} and may present an unrealistic scenario. Consider adjusting sliders.")

    st.session_state["species_mix"] = {k: int(st.session_state.get(k, 0)) for k in species_keys}

    # Backup latest values so they're available if user navigates away and back
    _backup_keys(["survival", "si", "net_acres", *species_keys])

def carbon_chart():
    # Ensure the sliders have been set
    if not all(k in st.session_state for k in ["tpa_df", "tpa_rc", "tpa_wh", "survival", "si", "net_acres"]):
        st.info("Adjust Planting Design sliders to see the carbon output.")
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
    
    year_0 = pd.DataFrame({"Year": [2024], "C_Score": [0], "Annual_C_Score": [0]})
    df = pd.DataFrame({"Year": years, "C_Score": c_scores, "Annual_C_Score": ann_c_scores})
    df = pd.concat([year_0, df])
    st.session_state.carbon_df = df

    toggle_oc = st.toggle('Show Project Acreage', True, 'toggle_oc', H("toggle.inputs.acres"))

    chart_title = "Onsite Carbon (tons/project)" if toggle_oc else "Onsite Carbon (tons/acre)"

     # Determine chart data
    plot_df = df.copy()
    if toggle_oc:
        plot_df["C_Score"] = plot_df["C_Score"] * st.session_state["net_acres"]
        plot_df["Annual_C_Score"] = plot_df["Annual_C_Score"] * st.session_state["net_acres"]

    # Determine chart title
    chart_title = "Onsite Carbon (tons/project)" if toggle_oc else "Onsite Carbon (tons/acre)"

    # Plot chart
    line = alt.Chart(plot_df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('C_Score:Q', title=chart_title),
        tooltip=['Year', 'C_Score']
    ).properties(
        title="Cumulative " + chart_title,
        width=600,
        height=400
    )

    st.altair_chart(line, use_container_width=True)
    st.success(f"Final Carbon Output (year {max(plot_df['Year'])}): {plot_df['C_Score'].iloc[-1]:.2f}")

# ---------- Carbon Units ----------
def carbon_units():
    if "carbon_df" not in st.session_state:
            st.error("No carbon data found. Adjust sliders first.")
            st.stop()

    df = st.session_state.carbon_df.copy()

    # Read multiple protocols
    inputs = st.session_state.get("carbon_units_inputs", {"protocols": ["ACR/CAR/VERRA"]})
    protocols = inputs["protocols"]

    all_protocol_dfs = []
    
    for protocol in protocols:
        df_base = df.copy()
        df_base['Onsite Total CO2'] = df_base['C_Score'] * 3.667

        # ----------------------------------
        # Protocol-specific calculations
        # ----------------------------------
        if protocol == "ACR/CAR/VERRA": 
            BUF = 0.20
            coeff = 1.0
            apply_buf = True
        elif protocol == "GS": #no buffer value
            coeff = 1.0
            apply_buf = False
        elif protocol == "ISO":
            BUF = 0.25 #dummy value
            coeff = 1.0
            apply_buf = True
        else:
            BUF = 0.20
            coeff = 1.0
            apply_buf = True

        df_base['Onsite Total CO2'] = df_base['Onsite Total CO2'] * coeff

        # Interpolation
        df_poly = df_base[['Year', 'Onsite Total CO2']].sort_values('Year')
        X = df_poly['Year'].values
        y = df_poly['Onsite Total CO2'].values
        spline = make_interp_spline(X, y, k=3)

        years_interp = np.arange(df_poly['Year'].min(), df_poly['Year'].max() + 1)
        y_interp = spline(years_interp)

        df_interp = pd.DataFrame({
            'Year': years_interp,
            'Onsite Total CO2_interp': y_interp,
            'ModelType': 'Project',
            'Protocol': protocol
        })

        baseline_df = pd.DataFrame({
            'Year': years_interp,
            'Onsite Total CO2_interp': 0,
            'ModelType': 'Baseline',
            'Protocol': protocol
        })

        baseline_df['delta_C_baseline'] = baseline_df['Onsite Total CO2_interp'].diff()
        df_interp['delta_C_project'] = df_interp['Onsite Total CO2_interp'].diff()

        merged_df = pd.merge(
            baseline_df[['Year', 'delta_C_baseline']],
            df_interp[['Year', 'delta_C_project']],
            on='Year'
        )

        # Compute CU only if buffer applies
        if apply_buf:
            merged_df['C_total'] = merged_df['delta_C_project'] - merged_df['delta_C_baseline']
            merged_df['BUF'] = merged_df['C_total'] * BUF
            merged_df['CU'] = merged_df['C_total'] - merged_df['BUF']
        else:
            merged_df['C_total'] = merged_df['delta_C_project'] - merged_df['delta_C_baseline']
            merged_df['BUF'] = 0.0
            merged_df['CU'] = merged_df['C_total']

        merged_df['Protocol'] = protocol

        for col in ['delta_C_project', 'delta_C_baseline', 'C_total', 'BUF', 'CU']:
            merged_df[col] = merged_df[col].round(2)

        # Append each protocol's results to the list
        all_protocol_dfs.append(merged_df)

    # Combine results
    if all_protocol_dfs:
        final_df = pd.concat(all_protocol_dfs)
        st.session_state.merged_df = final_df
    else:
        st.error("No protocols selected or no data available to plot.")
        return

    toggle_ce = st.toggle('Show Project Acreage', True, 'toggle_ce', H("toggle.inputs.acres"))

    # Adjust chart values based on toggle
    plot_df = final_df.copy()
    if toggle_ce:
        plot_df['CU'] = plot_df['CU'] * st.session_state["net_acres"]

    chart_title = "(tons/project)" if toggle_ce else "(tons/acre)"

    # Plot chart with Protocol color encoding
    CU_chart = alt.Chart(plot_df).mark_line(point=True).encode(
        x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)),
        y=alt.Y('CU:Q', title='CUs ' + chart_title),
        color='Protocol:N',
        tooltip=['Year', 'CU', 'Protocol']
    ).properties(
        title='Annual CU Estimates ' + chart_title,
        width=600,
        height=400
    ).configure_axis(grid=True, gridOpacity=0.3)

    st.altair_chart(CU_chart, use_container_width=True)

# ---------- Project Financials ----------
@st.cache_data
def _load_proforma_defaults() -> dict:
    with open("conf/base/proforma_presets.json") as f:
        return json.load(f)

def _seed_defaults(prefix: str = "credits_"):
    defaults = _load_proforma_defaults()
    # store under prefixed keys to avoid collisions
    for k, v in defaults.items():
        st.session_state.setdefault(prefix + k, v)

def credits_inputs(prefix: str = "credits_") -> dict:
    """
    Render Proforma inputs in the current container and return a dict of typed values.
    """
    # restore backup so users keep their previous values after navigation
    _restore_backup(_credits_keys(prefix), backup_name="_credits_backup")
    
    # seed defaults (setdefault) will not overwrite restored/user values
    _seed_defaults(prefix)
    
    st.markdown("Financial Options", help=None)
    container = st.container(height=600)
    with container:
        # net_acres              = st.number_input("Net Acres:", min_value=1, step=100, key=prefix+"net_acres", help=H("credits.inputs.net_acres"))
        num_plots              = st.number_input("# Plots:", min_value=1, key=prefix+"num_plots", help=H("credits.inputs.num_plots"))
        cost_per_cfi_plot      = st.number_input("Cost/CFI Plot, $:", min_value=1, key=prefix+"cost_per_cfi_plot", help=H("credits.inputs.cost_per_cfi_plot"))
        price_per_ert_initial  = st.number_input("Initial Price/CU, $:", min_value=1.0, key=prefix+"price_per_ert_initial", help=H("credits.inputs.price_per_ert_initial"))
        credit_price_increase_perc = st.number_input("Credit Price Increase, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"credit_price_increase", help=H("credits.inputs.credit_price_increase"))
        registry_fees              = st.number_input("Registry Fees, $:", min_value=1, key=prefix+"registry_fees", help=H("credits.inputs.registry_fees"))
        validation_cost            = st.number_input("Validation Cost, $:", min_value=1, key=prefix+"validation_cost", help=H("credits.inputs.validation_cost"))
        verification_cost          = st.number_input("Verification Cost, $:", min_value=1, key=prefix+"verification_cost", help=H("credits.inputs.verification_cost"))
        issuance_fee_per_ert       = st.number_input("Issuance Fee per CU, $:", min_value=0.0, step=0.01, format="%.2f", key=prefix+"issuance_fee_per_ert", help=H("credits.inputs.issuance_fee_per_ert"))
        anticipated_inflation_perc = st.number_input("Anticipated Inflation, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"anticipated_inflation", help=H("credits.inputs.anticipated_inflation"))
        discount_rate_perc         = st.number_input("Discount Rate, %:", min_value=0.0, step=1.0, format="%.1f", key=prefix+"discount_rate", help=H("credits.inputs.discount_rate"))
        planting_cost              = st.number_input("Initial Planting Cost, $:", min_value=0, key=prefix+"planting_cost", help=H("credits.inputs.planting_cost"))
        seedling_cost              = st.number_input("Initial Seedling Cost, $:", min_value=0, key=prefix+"seedling_cost", help=H("credits.inputs.seedling_cost"))

    # backup inputs so the latest entries persist across navigation
    _backup_keys(_credits_keys(prefix), backup_name="_credits_backup")

    # constants (constrained by modeling backend)
    year_start     = 2024
    years_advance  = 35
    net_acres = st.session_state["net_acres"]

    return {
        "net_acres": net_acres,
        "num_plots": num_plots,
        "cost_per_cfi_plot": cost_per_cfi_plot,
        "price_per_ert_initial": float(price_per_ert_initial),
        "credit_price_increase": float(credit_price_increase_perc) / 100.0,
        "registry_fees": registry_fees,
        "validation_cost": validation_cost,
        "verification_cost": verification_cost,
        "issuance_fee_per_ert": float(issuance_fee_per_ert),
        "anticipated_inflation": float(anticipated_inflation_perc) / 100.0,
        "discount_rate": float(discount_rate_perc) / 100.0,
        "planting_cost": planting_cost,
        "seedling_cost": seedling_cost,
        "year_start": year_start,
        "years_advance": years_advance,
    }

def _compute_proforma(df_ert_ac: pd.DataFrame, p: dict) -> pd.DataFrame:
    """
    df_ert_ac: DataFrame with ['Year','CU','Protocol'] where CU is per-acre
    p: params dict from credits_inputs()
    returns full proforma DataFrame with costs, revenue, net revenue for each protocol
    """
    results = []
    for protocol, subdf in df_ert_ac.groupby("Protocol"):
        df = subdf[['Year', 'CU']].copy()
        df = df.rename(columns={'CU': 'CU_ac'})
        df['Project_acres'] = p['net_acres']
        df['CU'] = df['CU_ac'] * p['net_acres']

        # credit volume: sell every 5th year including start year
        df['CUs_Sold'] = 0.0
        for i, row in df.iterrows():
            if row['Year'] == p['year_start'] or ((row['Year'] - p['year_start']) % 5 == 0 and row['Year'] > p['year_start']):
                df.loc[i, 'CUs_Sold'] = df.loc[max(0, i-4):i, 'CU'].sum()

        # revenue
        df['CU_Credit_Price'] = p['price_per_ert_initial'] * ((1 + p['credit_price_increase']) ** (df['Year'] - p['year_start']))
        df['Total_Revenue'] = df['CUs_Sold'] * df['CU_Credit_Price']

        # costs
        df['Validation_and_Verification'] = 0
        df.loc[df['Year'] == p['year_start'], 'Validation_and_Verification'] = p['validation_cost']
        df.loc[(df['Year'] > p['year_start']) & ((df['Year'] - p['year_start']) % 5 == 0), 'Validation_and_Verification'] = p['verification_cost']

        df['Survey_Cost'] = 0
        df.loc[(df['Year'] - p['year_start']) % 5 == 4, 'Survey_Cost'] = p['num_plots'] * p['cost_per_cfi_plot'] * (1 + p['anticipated_inflation'])

        df['Registry_Fees'] = p['registry_fees']
        df['Issuance_Fees'] = df['CUs_Sold'] * p['issuance_fee_per_ert']
        df['Planting_Cost'] = p['planting_cost']
        df['Seedling_Cost'] = p['seedling_cost']

        df['Total_Costs'] = (
            df['Validation_and_Verification'] +
            df['Survey_Cost'] +
            df['Registry_Fees'] +
            df['Issuance_Fees'] +
            df['Planting_Cost'] +
            df['Seedling_Cost']
        )
        df['Net_Revenue'] = df['Total_Revenue'] - df['Total_Costs']
        df['Protocol'] = protocol
        results.append(df)

    return pd.concat(results, ignore_index=True)

def credits_results(params: dict, prefix: str = "credits_") -> dict:
    if "merged_df" not in st.session_state:
        st.error("No carbon data found. Return to the Carbon Units Estimate section first.")
        st.stop()

    # Extract merged CU data per protocol
    df_ert_ac = st.session_state.merged_df[['Year', 'CU', 'Protocol']].copy()

    # Compute full proforma table per protocol
    df_pf = _compute_proforma(df_ert_ac, params)

    # Drop rows with NaN Net_Revenue to avoid chart issues
    df_pf = df_pf.dropna(subset=['Net_Revenue'])

    # Summary metrics per protocol
    year_start = params['year_start']
    year_stop = int(df_pf['Year'].max())

    summaries = []
    for protocol, subdf in df_pf.groupby("Protocol"):
        total_net = subdf['Net_Revenue'].sum()
        npv_yr20 = float(npf.npv(
            params['anticipated_inflation'] + params['discount_rate'],
            subdf[subdf['Year'] <= (year_start + 20)]['Net_Revenue']
        ))
        npv_per_acre = npv_yr20 / params['net_acres']
        summaries.append({
            "Protocol": protocol,
            "total_net": total_net,
            "npv_yr20": npv_yr20,
            "npv_per_acre": npv_per_acre
        })
    summaries_df = pd.DataFrame(summaries)

    # Filter chart to every 5 years (optional)
    include_years = np.arange(year_start, year_stop + 5, 5)
    df_chart = df_pf[df_pf['Year'].isin(include_years)]

    plot_df = df_chart.copy()

    toggle_nr = st.toggle('Show Project Acreage', True, 'toggle_nr', H("toggle.inputs.acres"))

    # Apply toggle logic
    if toggle_nr:
        plot_df['Net_Revenue'] = plot_df['Net_Revenue']
    else :
        plot_df['Net_Revenue'] = plot_df['Net_Revenue'] / params["net_acres"]

    chart_title = "Total" if toggle_nr else "Per Acre"

    chart = (
        alt.Chart(plot_df)
        .mark_line(point=True)
        .encode(
            x=alt.X('Year:O', title='Year', axis=alt.Axis(labelAngle=30)), 
            y=alt.Y('Net_Revenue:Q', title= chart_title + ' Net Revenue'),
            color=alt.Color('Protocol:N', title='Protocol'),
            tooltip=['Year', 'Net_Revenue', 'Protocol']
        )
        .properties(
            title= chart_title + f' Estimated Credits for {params["net_acres"]} Acre Project',
            width=600,
            height=400
        )
        .configure_axis(grid=True, gridOpacity=0.3)
    )

    st.altair_chart(chart, use_container_width=True)

    # Show summary metrics
    summaries_df_display = summaries_df.copy()
    summaries_df_display['Total Net Revenue, $'] = summaries_df_display['total_net'].map('${:,.2f}'.format)
    summaries_df_display['NPV (Year 20)'] = summaries_df_display['npv_yr20'].map('${:,.2f}'.format)
    summaries_df_display['NPV / Acre'] = summaries_df_display['npv_per_acre'].map('${:,.2f}'.format)

    # Keep only the columns to show
    summaries_df_display = summaries_df_display[['Protocol', 'Total Net Revenue, $', 'NPV (Year 20)', 'NPV / Acre']]

    # Display as a table
    st.subheader("Project Financials Summary", anchor=None, help=H("credits.summary_subheader"), divider=False, width="stretch")
    st.table(summaries_df_display.set_index('Protocol'))

    # CSV download
    st.download_button(
        label="⬇️ Download Proforma table (CSV)",
        data=df_pf.to_csv(index=False).encode("utf-8"),
        file_name="credits_proforma.csv",
        mime="text/csv",
        use_container_width=True,
        help=H("credits.download_button")
    )

# ---------- Render all sections with expanders ----------
@st.fragment
def run_chart():
    # Row 1: Planting sliders | Carbon chart
    with st.expander(label="Planting Parameters", expanded=True):
        col1, col2 = st.columns([1,2], gap="large")
        with col1:
            planting_sliders()
        with col2:
            carbon_chart()

    # Row 2: Acreage & Protocol | Carbon units chart
    with st.expander(label="Carbon Estimates", expanded=True):
        col3, col4 = st.columns([1,2], gap="large")
        with col3:
            if "carbon_df" not in st.session_state:
                st.error("No carbon data found. Adjust sliders above first.")
                st.stop()
            
            # restore backup and init state for carbon units
            _restore_backup(_carbon_units_keys(), backup_name="_carbon_units_backup")
            _init_carbon_units_state()

            # render widget using key only to enable restoring backups
            protocols = st.multiselect(
                "Select Protocol(s)",
                options=["ACR/CAR/VERRA", 
                         "GS",  
                         "ISO"],
                key="carbon_units_protocols",
                help=H("carbon.protocols_multiselect")
            )

            st.session_state["carbon_units_inputs"] = {"protocols": protocols}

            # backup latest selections for carbon units
            _backup_keys(_carbon_units_keys(), backup_name="_carbon_units_backup")

        with col4:
            carbon_units() 

    # Row 3: Proforma inputs | Credits chart + summary
    with st.expander(label="Project Financials", expanded=True):
        col5, col6 = st.columns([1,2], gap="large")
        with col5:
            proforma_params = credits_inputs(prefix="credits_")
        with col6:
            credits_results(proforma_params) 

########################################################################################################################################################################################
# -----------------------------
# Main
# -----------------------------

# Page Config
st.set_page_config(layout="wide", page_title="Project Builder", page_icon="🌲")

# Initialize Session State 
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Site Selection Map"

# File Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp")
simplified_geojson = os.path.join(BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326_simplified.geojson")

# -----------------------------
# Sidebar: Workflow Overview
# -----------------------------
st.sidebar.markdown("## Project Workflow")

workflow_steps = [
    {
        "label": "1. Site Selection",
        "tab": "Site Selection Map",
        "caption": "Select the FVS Variant Location geometry which contains your project location.",
    },
    {
        "label": "2. Planting Design",
        "tab": "Planting Design",
        "caption": (
            "Estimate certified carbon units under different protocols.\n\n"
            "*1. Planting Parameters*: Design your reforestation plan and estimate FVS results in real time.\n"
            "*2. Carbon Estimates*: Estimate carbon units (CUs)(tons CO₂e/acre) under different protocols.\n"
            "*3. Credits*: Customize financial factors to estimate net project revenue."
        ),
    },
]

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

# Render each step with highlight + caption under the correct one
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

# Conditional Layout (acts like tabs)
if st.session_state.active_tab == "Site Selection Map":
    # Site Selection Map View
    # Title Row (conditionally shows button after variant selection) 
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

                # Create a temp directory outside the "with" block so it persists
                tmpdir = tempfile.mkdtemp()

                # Save the uploaded ZIP
                zip_path = os.path.join(tmpdir, uploaded_file.name)
                with open(zip_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # Extract in place
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extractall(tmpdir)

                # Find shapefile or geojson inside
                extracted_files = os.listdir(tmpdir)
                print("Extracted files:", extracted_files)

                # Build full paths
                extracted_full_paths = [os.path.join(tmpdir, f) for f in extracted_files]

                # Find the shapefile or geojson
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

    # -----------------------------
    # Render map
    # -----------------------------
    map_data = st_folium(
        m,
        key="fvs_map",
        height=500,
        use_container_width=True,
    )

    # Display info below map
    show_clicked_variant(map_data)
    display_selected_info()

    if reset_button:
        # Remove from session state
        for key in ["upload_file", "uploaded_geojson_str", "uploaded_tooltip_fields"]:
            if key in st.session_state:
                del st.session_state[key]
        
        st.rerun()
else:
    # Planting Design View
    col1, col2 = st.columns([8, 3])  # adjust ratio as needed

    with col1:
        st.title("🌲 Planting Design", anchor=None, help=H("planting.title"))

    with col2:
        if st.button("⬅️ Site Selection", use_container_width=True, help=H("planting.button_back_to_site"), type='primary'):
            st.session_state.active_tab = "Site Selection Map"
            st.rerun()

    run_chart()

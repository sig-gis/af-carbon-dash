import streamlit as st
import folium
import json
import geopandas as gpd
import os
import tempfile
import numpy as np
import logging
import requests
from pathlib import Path
import io
from shapely.geometry import shape, box, Point
from shapely.ops import unary_union

from utils.config import get_api_base_url
from utils.functions.map_colors import color_for_feature
from utils.functions.helper import H

logger = logging.getLogger(__name__)


_geojson_cache: dict = {"data": None, "expires": 0}


def _fetch_geojson_from_api() -> str | None:
    """Fetch filtered GeoJSON from the API. Caches success for 5 min, retries failures every 15s."""
    import time

    now = time.time()
    if _geojson_cache["data"] is not None and now < _geojson_cache["expires"]:
        return _geojson_cache["data"]

    # Don't retry failures too aggressively
    if _geojson_cache["data"] is None and now < _geojson_cache["expires"]:
        return None

    try:
        base_url = get_api_base_url()
        resp = requests.get(f"{base_url}/geo/variants", timeout=30)
        resp.raise_for_status()
        payload = resp.json()

        # If API is healthy but returns an empty filtered feature set (common in
        # local dev before models are registered), allow downstream local-file
        # fallback by returning None.
        features = payload.get("features", []) if isinstance(payload, dict) else []
        if not features:
            logger.info(
                "API /geo/variants returned 0 features; falling back to local GeoJSON."
            )
            _geojson_cache["data"] = None
            _geojson_cache["expires"] = now + 15
            return None

        data = json.dumps(payload)
        _geojson_cache["data"] = data
        _geojson_cache["expires"] = now + 300  # cache success for 5 min
        return data
    except Exception as e:
        logger.warning("Could not fetch GeoJSON from API: %s", e)
        _geojson_cache["data"] = None
        _geojson_cache["expires"] = now + 15  # retry failures after 15s
        return None


@st.fragment
def load_geojson_fragment(simplified_geojson_path, shapefile_path, tolerance_deg=0.001, skip_keys={"Shape_Area", "Shape_Leng"}, max_tooltip_fields=4):
    """
    Loads a GeoJSON (or simplifies a shapefile if GeoJSON doesn't exist),
    returns the geojson string and filtered tooltip fields.

    Tries the API's /geo/variants endpoint first (returns GeoJSON
    dynamically filtered to registered models). Falls back to local files.
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

    # Try API first (dynamic, filtered to registered models)
    geojson_str = _fetch_geojson_from_api()

    # Fall back to local files
    if geojson_str is None:
        if os.path.exists(simplified_geojson_path):
            geojson_str = read_geojson_text(simplified_geojson_path)
        elif os.path.exists(shapefile_path):
            try:
                geojson_str = simplify_geojson(shapefile_path, tolerance_deg=tolerance_deg)
            except Exception as e:
                st.error(f"Failed to load shapefile: {e}")
                st.stop()
                return None, None
        else:
            st.warning(
                "No FVS variant data available. "
                "Upload models via the Model Management page to populate the map, "
                "or check that the API is running."
            )
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

def build_map(geojson_str, points=None, upload=None, center=(37.8, -96.9), zoom=5, tooltip_fields=None):
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

    # Fallbacks: fit map to bounding box of all features
    fit_bounds = None
    if last_center is None:
        if geojson_str:
            try:
                gjson = json.loads(geojson_str)
                all_bounds = []
                for feat in gjson["features"]:
                    geom = shape(feat["geometry"])
                    all_bounds.append(geom.bounds)  # (minx, miny, maxx, maxy)
                if all_bounds:
                    miny = min(b[1] for b in all_bounds)
                    maxy = max(b[3] for b in all_bounds)
                    minx = min(b[0] for b in all_bounds)
                    maxx = max(b[2] for b in all_bounds)
                    # Alaska's islands wrap past +180deg...
                    if maxx - minx > 180:
                        lons = [
                            (lon - 360 if lon > 0 else lon)
                            for b in all_bounds
                            for lon in (b[0], b[2])
                        ]
                        minx, maxx = min(lons), max(lons)
                    last_center = ((miny + maxy) / 2, (minx + maxx) / 2)
                    fit_bounds = [[miny, minx], [maxy, maxx]]
                else:
                    last_center = (37.8, -96.9)
            except Exception:
                last_center = (37.8, -96.9)
        else:
            last_center = (37.8, -96.9)

    m = folium.Map(
        location=last_center,
        zoom_start=last_zoom,
        tiles="OpenStreetMap",
    )
    if fit_bounds:
        m.fit_bounds(fit_bounds)

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
            style_function=lambda x: {
                "fillColor": color_for_feature(x["properties"]),
                "color": "black",
                "weight": 0.5,
                "fillOpacity": 0.3,
            },
            highlight_function=lambda x: {"fillColor": "yellow", "color": "red", "weight": 2, "fillOpacity": 0.6},
        )
        if tooltip_fields:
            gj.add_child(folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_fields, sticky=True))
        gj.add_to(m)

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


def _fetch_registry() -> list[dict]:
    """Fetch the model registry once for candidate expansion."""
    try:
        resp = requests.get(f"{get_api_base_url()}/models/registry", timeout=5)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception:
        return []


def _registry_variants(base: str, loccode: str, registry: list[dict]) -> list[str]:
    """Concrete registered variants for a (base, loccode) pair.

    Mirrors the registry half of ``plant_design._resolve_sub_variants`` but takes
    a pre-fetched registry so candidate collection makes a single HTTP call.
    """
    registered = sorted(
        {
            m["variant"]
            for m in registry
            if m.get("loccode") == loccode
            and m.get("variant")
            and (m["variant"] == base or m["variant"].startswith(base + "_"))
        }
    )
    return registered or [base]


def _variants_intersecting(test_geom, geojson_str) -> list[dict]:
    """Collect every FVS variant whose polygon intersects ``test_geom``.

    ``test_geom`` may be any shapely geometry — a clicked ``Point`` or an
    uploaded polygon. Returns a sorted, de-duplicated list of option dicts, one
    per concrete registered variant at every overlapping (base, loccode):

        {"variant", "loccode", "locname", "base", "feature"}

    Because detection is geometric, this surfaces the full overlap set — both
    same-base sub-variants (WC_1, WC_2) and unrelated bases sharing the spot
    (PN, SO) — that a single map click would otherwise hide.
    """
    if test_geom is None or not geojson_str:
        return []
    try:
        features = json.loads(geojson_str).get("features", [])
    except Exception:
        return []

    registry = _fetch_registry()
    options: dict[tuple[str, str], dict] = {}

    for feat in features:
        geom_json = feat.get("geometry")
        if not geom_json:
            continue
        try:
            geom = shape(geom_json)
        except Exception:
            continue
        if not geom.intersects(test_geom):
            continue

        props = feat.get("properties", {}) or {}
        base = props.get("FVSVariant", "PN")
        loccode = _loccode_str(props.get("FVSLocCode"))
        if loccode is None:
            continue
        locname = props.get("FVSLocName", "")

        for variant in _registry_variants(base, loccode, registry):
            key = (variant, loccode)
            options.setdefault(
                key,
                {
                    "variant": variant,
                    "loccode": loccode,
                    "locname": locname,
                    "base": base,
                    "feature": feat,
                },
            )

    return [options[k] for k in sorted(options.keys())]


def variants_at_point(point, geojson_str) -> list[dict]:
    """Collect every FVS variant whose polygon contains ``point`` (see
    ``_variants_intersecting`` for the returned shape)."""
    return _variants_intersecting(point, geojson_str)


def variants_at_geometry(uploaded_geojson_str, geojson_str) -> list[dict]:
    """Collect every FVS variant whose polygon overlaps an uploaded geometry.

    Unions all features in ``uploaded_geojson_str`` (a shapefile/GeoJSON the
    user uploaded) and returns the overlap set in the same shape as
    ``variants_at_point``. Used to auto-select the VarLoc after upload without
    requiring a manual map click (#127).
    """
    if not uploaded_geojson_str:
        return []
    try:
        feats = json.loads(uploaded_geojson_str).get("features", [])
        geoms = [shape(f["geometry"]) for f in feats if f.get("geometry")]
    except Exception:
        return []
    if not geoms:
        return []
    return _variants_intersecting(unary_union(geoms), geojson_str)


def _apply_candidate(c: dict):
    """Write a chosen variant candidate into session state (variant + location)."""
    st.session_state["active_variant"] = c["variant"]
    st.session_state["selected_variant"] = c["base"]
    st.session_state["selected_varloc_code"] = c["loccode"]
    st.session_state["FVSLocCode"] = c["loccode"]
    st.session_state["selected_varloc_name"] = c.get("locname") or ""
    st.session_state["clicked_feature"] = c["feature"]
    st.session_state["clicked_props"] = c["feature"].get("properties", {}) or {}


def _select_candidates(candidates: list[dict]) -> bool:
    """Store candidates and auto-pick the first. Returns True if any were found."""
    st.session_state["variant_candidates"] = candidates
    # New selection: reset the chooser widget so it re-defaults to the first option.
    st.session_state.pop("site_variant_choice", None)
    if not candidates:
        return False
    _apply_candidate(candidates[0])
    return True


def auto_select_variant_from_point(point, geojson_str):
    """
    Resolve and set the selected variant/session state from a lat/lon point.
    Collects every overlapping variant as a candidate, auto-selecting the first.
    Returns the selected feature's properties if found, else None.
    """
    candidates = variants_at_point(point, geojson_str)
    if not _select_candidates(candidates):
        return None
    return st.session_state["clicked_props"]


def auto_select_variant_from_latlon(lat, lon, geojson_str):
    """
    Resolve and set the selected variant/session state from user-entered
    latitude/longitude values.

    Shapely Point expects x/y order, so this creates Point(lon, lat).
    Returns the selected feature's properties if found, else None.
    """
    if lat is None or lon is None or not geojson_str:
        return None

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        st.warning("Latitude and longitude must be valid numbers.")
        return None

    point = Point(lon, lat)
    selected_props = auto_select_variant_from_point(point, geojson_str)

    if selected_props:
        st.session_state["points"] = [point]
        st.session_state["last_added_type"] = "point"
        return selected_props

    return None


def auto_select_variant_from_upload(upload_geojson, geojson_str):
    """
    Resolve and set the selected variant/session state from an uploaded
    shapefile/GeoJSON.

    Uses the uploaded geometry's representative point first, then falls back
    to intersecting the uploaded geometry against supported FVS polygons.
    Returns the selected feature's properties if found, else None.
    """
    if not upload_geojson or not geojson_str:
        return None

    try:
        upload_json = (
            json.loads(upload_geojson)
            if isinstance(upload_geojson, str)
            else upload_geojson
        )

        uploaded_geoms = [
            shape(feat["geometry"])
            for feat in upload_json.get("features", [])
            if feat.get("geometry")
        ]

        if not uploaded_geoms:
            return None

        # First try: use a representative point from the uploaded geometry.
        # This point is guaranteed to fall inside the geometry.
        point = uploaded_geoms[0].representative_point()
        candidates = variants_at_point(point, geojson_str)

        # Fallback: if the representative point does not hit a supported FVS
        # polygon, intersect the whole uploaded geometry with the FVS polygons.
        if not candidates:
            fvs_features = json.loads(geojson_str).get("features", [])
            registry = _fetch_registry()
            all_candidates = []

            for feat in fvs_features:
                geom_json = feat.get("geometry")
                if not geom_json:
                    continue

                try:
                    fvs_geom = shape(geom_json)
                except Exception:
                    continue

                if any(
                    fvs_geom.intersects(uploaded_geom)
                    for uploaded_geom in uploaded_geoms
                ):
                    all_candidates.extend(
                        _candidates_from_feature(feat, registry)
                    )

            # Deduplicate by variant + loccode.
            deduped = {}
            for c in all_candidates:
                deduped[(c["variant"], c["loccode"])] = c

            candidates = [deduped[k] for k in sorted(deduped.keys())]

        if not _select_candidates(candidates):
            return None

        st.session_state["last_added_type"] = "upload"
        return st.session_state["clicked_props"]

    except Exception as e:
        st.warning(f"Could not auto-select FVS variant from uploaded file: {e}")
        return None

def build_highlight_layer(feature: dict | None) -> folium.FeatureGroup | None:
    """Build a FeatureGroup for the selected feature highlight.

    Passed to st_folium via ``feature_group_to_add`` so the highlight
    is applied as a JS update without replacing the base map iframe.
    """
    if feature is None:
        return None
    geom = feature.get("geometry")
    if geom is None:
        return None
    fg = folium.FeatureGroup(name="Selected Boundary")
    folium.GeoJson(
        geom,
        style_function=lambda x: {
            "fillColor": "yellow",
            "color": "red",
            "weight": 3,
            "fillOpacity": 0.2,
        },
    ).add_to(fg)
    return fg


def _candidates_from_feature(feat: dict, registry: list[dict] | None = None) -> list[dict]:
    """Build candidate options from a single clicked feature (fallback path)."""
    props = feat.get("properties", {}) or {}
    base = props.get("FVSVariant", "PN")
    loccode = _loccode_str(props.get("FVSLocCode"))
    if loccode is None:
        return []
    registry = _fetch_registry() if registry is None else registry
    locname = props.get("FVSLocName", "")
    return [
        {"variant": v, "loccode": loccode, "locname": locname, "base": base, "feature": feat}
        for v in _registry_variants(base, loccode, registry)
    ]


def _process_pending_click(geojson_str: str | None = None):
    """Process a map click that was saved on the previous render.

    Call this BEFORE building the map so the highlight is included
    in the same render pass. Uses the clicked lat/lng to collect every
    overlapping variant; falls back to the clicked feature alone if the
    point misses (e.g. simplified geometry).
    """
    pending = st.session_state.pop("_pending_map_click", None)
    if pending is None:
        return False

    feat = pending.get("feature") if isinstance(pending, dict) else pending
    latlng = pending.get("latlng") if isinstance(pending, dict) else None
    if not feat:
        return False

    # Remember what was clicked so re-renders don't re-trigger processing,
    # even though the auto-picked candidate may be a different overlapping polygon.
    st.session_state["_last_click_feature"] = feat

    point = None
    if latlng and latlng.get("lat") is not None and latlng.get("lng") is not None:
        point = Point(latlng["lng"], latlng["lat"])
    else:
        try:
            point = shape(feat["geometry"]).representative_point()
        except Exception:
            point = None

    candidates = (
        variants_at_point(point, geojson_str) if (point and geojson_str) else []
    )
    if not candidates:
        candidates = _candidates_from_feature(feat)
    _select_candidates(candidates)
    return True


def show_clicked_variant(map_data):
    """Detect a new map click and queue it for processing on the next render."""
    if map_data and map_data.get("last_active_drawing"):
        feat = map_data["last_active_drawing"]
        props = feat.get("properties", {})

        if props and st.session_state.get("_last_click_feature") != feat:
            st.session_state["_pending_map_click"] = {
                "feature": feat,
                "latlng": map_data.get("last_clicked"),
            }
            st.rerun()

def display_selected_info():
    """
    Display the selected variant's properties in the UI, filtering out internal
    fields and formatting readable labels.
    """
    if "clicked_props" in st.session_state:
        props = st.session_state["clicked_props"]

        # st.subheader("Selected Feature Info", anchor=None, help=H("site.subheader_selected_feature_info"), divider=False, width="stretch")
        pretty_names = {
            "FVSVariant": "FVS Variant",
            "FVSLocName": "FVS Location Name",
            "FVSLocCode": "FVS Location Code",
        }
        skip_keys = {"Shape_Area", "Shape_Leng", 'FVSVariantLoc', 'FVSVarName'}

        for key, value in props.items():
            if key not in skip_keys:
                display_key = pretty_names.get(key, key)
                display_value = value
                # Show resolved sub-variant when available
                if key == "FVSVariant":
                    active = st.session_state.get("active_variant")
                    if active and active != value:
                        display_value = f"{active} (from {value})"
                    elif active:
                        display_value = active
                st.success(f"Successfully selected **{display_key}:** {display_value}")
                # st.success(f"Please continue to Planting Design, or select a different variant.")


def _candidate_label(c: dict) -> str:
    """Human-readable label for a variant candidate in the chooser."""
    name = c.get("locname") or ""
    if name:
        return f"{c['variant']} — {name} ({c['loccode']})"
    return f"{c['variant']} ({c['loccode']})"


def variant_chooser():
    """Render the FVS variant chooser for the current selection.

    Lists every variant valid at the clicked location. The first is auto-picked;
    the user can override. A single-candidate selection renders nothing extra
    (``display_selected_info`` already shows the resolved variant).
    """
    candidates = st.session_state.get("variant_candidates") or []
    if len(candidates) <= 1:
        return

    labels = [_candidate_label(c) for c in candidates]
    active = st.session_state.get("active_variant")
    default_idx = next(
        (i for i, c in enumerate(candidates) if c["variant"] == active), 0
    )
    idx = st.selectbox(
        "Multiple FVS variants cover this location — choose one:",
        options=list(range(len(candidates))),
        index=default_idx,
        format_func=lambda i: labels[i],
        key="site_variant_choice",
        help=H("site.variant_chooser"),
    )
    chosen = candidates[idx]
    # The selected-info panel and map highlight are rendered earlier in the page
    # pass; rerun once on a real change so they reflect the new choice.
    changed = (
        st.session_state.get("active_variant") != chosen["variant"]
        or st.session_state.get("selected_varloc_code") != chosen["loccode"]
    )
    _apply_candidate(chosen)
    if changed:
        st.rerun()


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
            st.session_state["selected_varloc_name"] = clicked.get("FVSLocName", "Olympic National Forest")
            st.session_state["selected_varloc_code"] = _loccode_str(clicked.get("FVSLocCode")) or "609"
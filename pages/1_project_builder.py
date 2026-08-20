# import json
# import os
# import tempfile
# import zipfile
# from pathlib import Path

# import streamlit as st
# import streamlit.components.v1 as components
# from geopy.geocoders import Nominatim
# from shapely.geometry import Point
# from streamlit_folium import st_folium

# from utils.functions.helper import H
# from utils.functions.gcs_upload import (
#     create_signed_upload_url,
#     delete_gcs_object,
#     download_gcs_object_to_tempfile,
#     make_site_upload_object_name,
# )
# from utils.functions.plant_design import run_chart
# from utils.functions.site_select import (
#     _process_pending_click,
#     auto_select_variant_from_point,
#     auto_select_variant_from_upload,
#     build_highlight_layer,
#     build_map,
#     display_selected_info,
#     load_geojson_fragment,
#     load_geojson_or_shapefile,
#     show_clicked_variant,
#     variant_chooser,
#     variants_at_geometry,
# )
# from utils.functions.solver import current_solver_prefill, run_solver

# st.set_page_config(layout="wide", page_title="Project Builder", page_icon="🌲")

# # Initialize Session State
# if "active_tab" not in st.session_state:
#     st.session_state.active_tab = "Site Selection Map"

# BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# local_shapefile = os.path.join(
#     BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp"
# )
# simplified_geojson = os.path.join(
#     BASE_DIR,
#     "data",
#     "FVSVariantMap20210525",
#     "FVS_Variants_and_Locations_4326_simplified.geojson",
# )

# st.sidebar.markdown("## Project Workflow")

# with open(
#     os.path.join(BASE_DIR, "conf/base/workflow_steps.json"),
#     "r",
#     encoding="utf-8",
# ) as f:
#     workflow_steps = json.load(f)

# st.sidebar.markdown(
#     """
#     <style>
#     .workflow-step {
#         padding: 8px 12px;
#         border-radius: 6px;
#         margin-bottom: 6px;
#     }
#     .active-step {
#         background-color: #dffde9;
#         border-left: 5px solid #177233;
#         font-weight: 600;
#         color: #177233;
#     }
#     .inactive-step {
#         color: #555;
#     }
#     </style>
# """,
#     unsafe_allow_html=True,
# )

# for step in workflow_steps:
#     is_active = st.session_state.active_tab == step["tab"]
#     step_class = "active-step" if is_active else "inactive-step"

#     st.sidebar.markdown(
#         f'<div class="workflow-step {step_class}">{step["label"]}</div>',
#         unsafe_allow_html=True,
#     )

#     if is_active:
#         for line in step["caption"].split("\n"):
#             if line.strip():
#                 st.sidebar.caption(line.strip())

# st.sidebar.markdown("---")
# st.sidebar.info("Having Trouble? Visit the FAQ page above for more information.")

# if st.session_state.active_tab == "Site Selection Map":
#     st.title(
#         "🗺️ Site Selection",
#         anchor=None,
#         help=H("site.title"),
#     )

#     if "points" not in st.session_state:
#         st.session_state.points = []

#     if "upload_file" not in st.session_state:
#         st.session_state.upload_file = []

#     geojson_str, tooltip_fields = load_geojson_fragment(
#         simplified_geojson,
#         local_shapefile,
#     )

#     with st.expander(
#         label="Add Point by latitude/longitude or look up an address",
#         expanded=False,
#     ):
#         st.subheader("Go to Lat/Lon")

#         col1, col2, col3, col4, col5, col6, col7, col8, col9, col10 = st.columns(
#             [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
#         )

#         with col1:
#             lat = st.number_input(
#                 "Latitude",
#                 value=45.5,
#                 format="%.3f",
#                 help=None,
#                 width=200,
#             )

#         with col2:
#             lon = st.number_input(
#                 "Longitude",
#                 value=-118.0,
#                 format="%.3f",
#                 help=None,
#                 width=200,
#             )

#         add_point_button = st.button("Add Point to Map")

#         st.subheader("Go to Address")

#         (
#             col1_r2,
#             col2_r2,
#             col3_r2,
#             col4_r2,
#             col5_r2,
#             col6_r2,
#             col7_r2,
#             col8_r2,
#             col9_r2,
#         ) = st.columns([1, 1, 1, 1, 1, 1, 1, 1, 1])

#         with col1_r2:
#             street = st.text_input("Street Address")

#         with col2_r2:
#             city = st.text_input("City/Town")

#         with col3_r2:
#             state = st.text_input("State")

#         go_address_button = st.button("Go to Address")

#     if add_point_button:
#         new_pt = Point(lon, lat)

#         # Replace prior point instead of stacking multiple markers.
#         st.session_state.points = [new_pt]

#         st.session_state["last_added_type"] = "point"
#         st.session_state["last_point"] = new_pt

#         matched = auto_select_variant_from_point(new_pt, geojson_str)

#         if matched:
#             st.success(
#                 "Latitude/Longitude matched a supported FVS variant. Variant auto-selected."
#             )
#         else:
#             st.warning("Latitude/Longitude does not intersect a supported FVS variant.")

#         st.rerun()

#     if go_address_button:
#         full_address = ", ".join(filter(None, [street, city, state]))

#         if full_address:
#             geolocator = Nominatim(user_agent="streamlit_map_app")
#             location = geolocator.geocode(full_address)

#             if location:
#                 new_pt = Point(location.longitude, location.latitude)

#                 # Replace prior point instead of stacking multiple markers.
#                 st.session_state.points = [new_pt]

#                 st.session_state["last_added_type"] = "point"
#                 st.session_state["last_point"] = new_pt

#                 matched = auto_select_variant_from_point(new_pt, geojson_str)

#                 if matched:
#                     st.success(
#                         "Address matched a supported FVS variant. Variant auto-selected."
#                     )
#                 else:
#                     st.warning(
#                         "Address found, but it does not intersect a supported FVS variant polygon."
#                     )

#                 st.rerun()

#             else:
#                 st.error("Address not found.")
#         else:
#             st.error("Enter at least one field for address, city, or state.")

#     with st.expander(label="Upload GeoJSON/Shapefile", expanded=False):
#         uploaded_files = st.file_uploader(
#             "Upload GeoJSON (.geojson) or all shapefile components seperatly (.shp, .shx, .dbf, .prj) or zipped (.zip)",
#             accept_multiple_files=True,
#             type=["geojson", "shp", "shx", "dbf", "prj", "cpg", "zip"],
#             width=600,
#         )

#         upload_button = st.button("Upload file to map")
#         reset_button = st.button("Reset file uploads")

#         st.markdown("---")
#         st.caption(
#             "Large zipped shapefile upload: use this when Cloud Run rejects the normal upload. "
#             "The browser uploads the ZIP directly to temporary Google Cloud Storage."
#         )

#         large_upload_name = st.text_input(
#             "Large ZIP filename",
#             value="site_selection_upload.zip",
#             help="This name is only used for the temporary GCS object path.",
#         )

#         if st.button("Prepare large ZIP upload"):
#             object_name = make_site_upload_object_name(large_upload_name)
#             try:
#                 signed_url, gcs_uri = create_signed_upload_url(object_name)
#                 st.session_state["large_upload_signed_url"] = signed_url
#                 st.session_state["large_upload_gcs_uri"] = gcs_uri
#                 st.success("Signed upload URL created. Choose your ZIP below and upload it to GCS.")
#             except Exception as e:
#                 st.error(f"Could not create signed upload URL: {e}")

#         if st.session_state.get("large_upload_signed_url"):
#             signed_url_json = json.dumps(st.session_state["large_upload_signed_url"])
#             components.html(
#                 f"""
#                 <div style="font-family: sans-serif; border: 1px solid #ddd; border-radius: 6px; padding: 12px; max-width: 660px;">
#                   <label style="display:block; font-weight:600; margin-bottom:8px;">Choose zipped shapefile for direct GCS upload</label>
#                   <input id="gcs-file" type="file" accept=".zip" />
#                   <button id="gcs-upload" style="margin-left:8px; padding:4px 10px;">Upload to GCS</button>
#                   <div id="gcs-status" style="margin-top:10px; color:#555;">Waiting for file...</div>
#                   <script>
#                     const signedUrl = {signed_url_json};
#                     const status = document.getElementById('gcs-status');
#                     document.getElementById('gcs-upload').onclick = async () => {{
#                       const fileInput = document.getElementById('gcs-file');
#                       if (!fileInput.files.length) {{
#                         status.textContent = 'Choose a .zip file first.';
#                         status.style.color = '#b00020';
#                         return;
#                       }}
#                       const file = fileInput.files[0];
#                       status.textContent = `Uploading ${{file.name}} (${{(file.size / 1048576).toFixed(1)}} MB)...`;
#                       status.style.color = '#555';
#                       try {{
#                         const response = await fetch(signedUrl, {{
#                           method: 'PUT',
#                           headers: {{'Content-Type': 'application/zip'}},
#                           body: file
#                         }});
#                         if (!response.ok) {{
#                           throw new Error(`Upload failed: HTTP ${{response.status}} ${{response.statusText}}`);
#                         }}
#                         status.textContent = 'Upload complete. Now click "Process large GCS upload" in Streamlit.';
#                         status.style.color = '#177233';
#                       }} catch (err) {{
#                         status.textContent = err.toString();
#                         status.style.color = '#b00020';
#                       }}
#                     }};
#                   </script>
#                 </div>
#                 """,
#                 height=150,
#             )
#             st.caption(f"Temporary upload target: `{st.session_state['large_upload_gcs_uri']}`")

#         process_large_upload_button = st.button(
#             "Process large GCS upload",
#             disabled=not bool(st.session_state.get("large_upload_gcs_uri")),
#         )

#     if upload_button:
#         for key in [
#             "upload_file",
#             "uploaded_geojson_str",
#             "uploaded_tooltip_fields",
#             "upload_auto_selected",
#         ]:
#             if key in st.session_state:
#                 del st.session_state[key]

#         if uploaded_files:
#             if len(uploaded_files) == 1 and uploaded_files[0].name.lower().endswith(
#                 ".zip"
#             ):
#                 st.write("ZIP file detected!")
#                 uploaded_file = uploaded_files[0]

#                 tmpdir = tempfile.mkdtemp()

#                 zip_path = os.path.join(tmpdir, uploaded_file.name)
#                 with open(zip_path, "wb") as f:
#                     f.write(uploaded_file.getbuffer())

#                 with zipfile.ZipFile(zip_path, "r") as zip_ref:
#                     zip_ref.extractall(tmpdir)

#                 extracted_files = os.listdir(tmpdir)
#                 print("Extracted files:", extracted_files)

#                 extracted_full_paths = [
#                     os.path.join(tmpdir, f) for f in extracted_files
#                 ]

#                 geojson_target = next(
#                     (
#                         f
#                         for f in extracted_full_paths
#                         if f.lower().endswith(".geojson")
#                     ),
#                     None,
#                 )
#                 shp_target = next(
#                     (f for f in extracted_full_paths if f.lower().endswith(".shp")),
#                     None,
#                 )

#                 if geojson_target:
#                     st.session_state.upload_file = [geojson_target]
#                 elif shp_target:
#                     st.session_state.upload_file = extracted_full_paths
#                 else:
#                     st.error("No .shp or .geojson file found inside ZIP.")
#             else:
#                 st.write("Not a ZIP file or multiple files uploaded.")
#                 st.session_state.upload_file = uploaded_files

#     if process_large_upload_button:
#         for key in [
#             "upload_file",
#             "uploaded_geojson_str",
#             "uploaded_tooltip_fields",
#             "upload_auto_selected",
#         ]:
#             if key in st.session_state:
#                 del st.session_state[key]

#         gcs_uri = st.session_state.get("large_upload_gcs_uri")
#         if not gcs_uri:
#             st.error("Prepare and upload a large ZIP file first.")
#         else:
#             try:
#                 with st.spinner("Downloading uploaded ZIP from temporary cloud storage..."):
#                     zip_path = download_gcs_object_to_tempfile(gcs_uri, suffix=".zip")

#                 tmpdir = tempfile.mkdtemp()
#                 with zipfile.ZipFile(zip_path, "r") as zip_ref:
#                     zip_ref.extractall(tmpdir)

#                 extracted_full_paths = [
#                     str(path) for path in Path(tmpdir).rglob("*") if path.is_file()
#                 ]

#                 geojson_target = next(
#                     (
#                         f
#                         for f in extracted_full_paths
#                         if f.lower().endswith(".geojson")
#                     ),
#                     None,
#                 )
#                 shp_target = next(
#                     (f for f in extracted_full_paths if f.lower().endswith(".shp")),
#                     None,
#                 )

#                 if geojson_target:
#                     st.session_state.upload_file = [geojson_target]
#                     st.success("Large ZIP downloaded and prepared for map processing.")
#                     try:
#                         delete_gcs_object(gcs_uri)
#                         st.session_state.pop("large_upload_signed_url", None)
#                         st.session_state.pop("large_upload_gcs_uri", None)
#                     except Exception as cleanup_error:
#                         st.warning(
#                             f"Upload was processed, but temporary GCS cleanup failed: {cleanup_error}"
#                         )
#                 elif shp_target:
#                     st.session_state.upload_file = extracted_full_paths
#                     st.success("Large ZIP downloaded and prepared for map processing.")
#                     try:
#                         delete_gcs_object(gcs_uri)
#                         st.session_state.pop("large_upload_signed_url", None)
#                         st.session_state.pop("large_upload_gcs_uri", None)
#                     except Exception as cleanup_error:
#                         st.warning(
#                             f"Upload was processed, but temporary GCS cleanup failed: {cleanup_error}"
#                         )
#                 else:
#                     st.error("No .shp or .geojson file found inside uploaded ZIP.")
#             except Exception as e:
#                 st.error(f"Could not process large GCS upload: {e}")

#     uploaded_geojson_str, uploaded_tooltip_fields = None, None

#     if st.session_state.upload_file:
#         uploaded_geojson_str, uploaded_tooltip_fields = load_geojson_or_shapefile(
#             st.session_state.upload_file
#         )

#         st.session_state["last_added_type"] = "upload"
#         st.session_state["last_upload"] = uploaded_geojson_str

#         if uploaded_geojson_str and not st.session_state.get("upload_auto_selected"):
#             matched = auto_select_variant_from_upload(
#                 uploaded_geojson_str,
#                 geojson_str,
#             )

#             st.session_state["upload_auto_selected"] = True

#             if matched:
#                 st.success(
#                     "Uploaded geometry matched a supported FVS variant. Variant auto-selected."
#                 )
#             else:
#                 st.warning(
#                     "Uploaded geometry does not intersect a supported FVS variant."
#                 )

#     st.subheader(
#         "Select FVS Variant",
#         anchor=None,
#         divider=False,
#         help=H("site.subheader_select_variant"),
#     )

#     _process_pending_click(geojson_str)

#     st.session_state.setdefault(
#         "map_view",
#         {"center": [45.5, -118], "zoom": 6},
#     )

#     m = build_map(
#         geojson_str,
#         points=st.session_state.points,
#         upload=uploaded_geojson_str,
#         center=tuple(st.session_state["map_view"]["center"]),
#         zoom=int(st.session_state["map_view"]["zoom"]),
#         tooltip_fields=tooltip_fields,
#     )

#     highlight_fg = build_highlight_layer(st.session_state.get("clicked_feature"))

#     map_data = st_folium(
#         m,
#         key="fvs_map",
#         height=500,
#         use_container_width=True,
#         returned_objects=["last_active_drawing", "last_clicked"],
#         feature_group_to_add=highlight_fg,
#     )

#     show_clicked_variant(map_data)
#     display_selected_info()
#     variant_chooser()

#     # Fill the button placeholder now that click state is up to date.
#     # Show navigation buttons below the map.
#     # if st.session_state.get("selected_variant"):
#     #     # st.divider()

#     #     # col1, col2 = st.columns(2)

#     #     # with col1:
#     #     #     if st.button(
#     #     #         "➡️ Planting Design",
#     #     #         use_container_width=True,
#     #     #         help=H("site.button_forward_to_planting"),
#     #     #         type="primary",
#     #     #     ):
#     #     #         st.session_state.active_tab = "Planting Design"
#     #     #         st.rerun()

#     #     # with col2:
#     #     #     if st.button(
#     #     #         "🧮 Solver",
#     #     #         use_container_width=True,
#     #     #         help=H("site.button_forward_to_solver"),
#     #     #     ):
#     #     #         st.session_state.active_tab = "Solver"
#     #     #         st.rerun()
#     #     # Show navigation buttons below the map.
#     #     st.divider()

#     #     location_selected = bool(st.session_state.get("selected_variant"))

#     #     disabled_msg = (
#     #         "Select a location first using Step 1: click the map, enter coordinates/address, "
#     #         "or upload a shapefile/GeoJSON."
#     #     )

#     #     col1, col2 = st.columns(2)

#     #     with col1:
#     #         if st.button(
#     #             "➡️ Planting Design",
#     #             use_container_width=True,
#     #             help=H("site.button_forward_to_planting") if location_selected else disabled_msg,
#     #             type="primary",
#     #             disabled=not location_selected,
#     #         ):
#     #             st.session_state.active_tab = "Planting Design"
#     #             st.rerun()

#     #     with col2:
#     #         if st.button(
#     #             "🧮 Solver",
#     #             use_container_width=True,
#     #             help=H("site.button_forward_to_solver") if location_selected else disabled_msg,
#     #             disabled=not location_selected,
#     #         ):
#     #             st.session_state.active_tab = "Solver"
#     #             st.rerun()
#     # Show navigation buttons below the map.
#     st.divider()

#     location_selected = bool(st.session_state.get("selected_variant"))

#     disabled_msg = (
#         "Select a location first using Step 1: click the map, enter coordinates/address, "
#         "or upload a shapefile/GeoJSON."
#     )

#     col1, col2 = st.columns(2)

#     with col1:
#         if location_selected:
#             if st.button(
#                 "➡️ Planting Design",
#                 use_container_width=True,
#                 help=H("site.button_forward_to_planting"),
#                 type="primary",
#             ):
#                 st.session_state.active_tab = "Planting Design"
#                 st.rerun()
#         else:
#             st.button(
#                 "➡️ Planting Design",
#                 use_container_width=True,
#                 help=disabled_msg,
#                 type="primary",
#                 disabled=True,
#             )

#     with col2:
#         if location_selected:
#             if st.button(
#                 "🧮 Solver",
#                 use_container_width=True,
#                 help=H("site.button_forward_to_solver"),
#             ):
#                 st.session_state.active_tab = "Solver"
#                 st.rerun()
#         else:
#             st.button(
#                 "🧮 Solver",
#                 use_container_width=True,
#                 help=disabled_msg,
#                 disabled=True,
#             )

#         if reset_button:
#             for key in [
#                 "upload_file",
#                 "uploaded_geojson_str",
#                 "uploaded_tooltip_fields",
#                 "last_upload",
#                 "upload_auto_selected",
#                 "large_upload_signed_url",
#                 "large_upload_gcs_uri",
#             ]:
#                 if key in st.session_state:
#                     del st.session_state[key]

#             st.rerun()

# elif st.session_state.active_tab == "Planting Design":
#     col1, col2 = st.columns([8, 3])

#     with col1:
#         st.title(
#             "🌲 Planting Design",
#             anchor=None,
#             help=H("planting.title"),
#         )

#     with col2:
#         if st.button(
#             "⬅️ Site Selection",
#             use_container_width=True,
#             help=H("planting.button_back_to_site"),
#             type="primary",
#         ):
#             st.session_state.active_tab = "Site Selection Map"
#             st.rerun()

#     run_chart()

# elif st.session_state.active_tab == "Solver":
#     col1, col2, col3 = st.columns([6, 3, 3])

#     with col1:
#         st.title("🧮 Solver", anchor=None, help=H("solver.title"))

#     with col2:
#         if st.button(
#             "⬅️ Site Selection",
#             use_container_width=True,
#             help=H("planting.button_back_to_site"),
#             type="primary",
#         ):
#             st.session_state.active_tab = "Site Selection Map"
#             st.rerun()

#     with col3:
#         if st.button(
#             "🌲 Planting Design",
#             use_container_width=True,
#             help=H("site.button_forward_to_planting"),
#         ):
#             # Carry the solver's current design inputs over (not a solved value)
#             prefill = current_solver_prefill()
#             if prefill:
#                 st.session_state["_planting_prefill"] = prefill
#             st.session_state.active_tab = "Planting Design"
#             st.rerun()

#     run_solver()

import json
import os
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from geopy.geocoders import Nominatim
from shapely.geometry import Point
from streamlit_folium import st_folium

from utils.functions.helper import H
from utils.functions.gcs_upload import (
    create_signed_upload_url,
    delete_gcs_object,
    download_gcs_object_to_tempfile,
    make_site_upload_object_name,
)
from utils.functions.plant_design import run_chart
from utils.functions.site_select import (
    _process_pending_click,
    auto_select_variant_from_point,
    auto_select_variant_from_upload,
    build_highlight_layer,
    build_map,
    display_selected_info,
    load_geojson_fragment,
    load_geojson_or_shapefile,
    show_clicked_variant,
    variant_chooser,
    variants_at_geometry,
)
from utils.functions.solver import current_solver_prefill, run_solver

st.set_page_config(layout="wide", page_title="Project Builder", page_icon="🌲")

# Initialize Session State
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Site Selection Map"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_shapefile = os.path.join(
    BASE_DIR, "data", "FVSVariantMap20210525", "FVS_Variants_and_Locations_4326.shp"
)
simplified_geojson = os.path.join(
    BASE_DIR,
    "data",
    "FVSVariantMap20210525",
    "FVS_Variants_and_Locations_4326_simplified.geojson",
)

st.sidebar.markdown("## Project Workflow")

with open(
    os.path.join(BASE_DIR, "conf/base/workflow_steps.json"),
    "r",
    encoding="utf-8",
) as f:
    workflow_steps = json.load(f)

st.sidebar.markdown(
    """
    <style>
    .workflow-step {
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
    }
    .active-step {
        background-color: #dffde9;
        border-left: 5px solid #177233;
        font-weight: 600;
        color: #177233;
    }
    .inactive-step {
        color: #555;
    }
    </style>
""",
    unsafe_allow_html=True,
)

for step in workflow_steps:
    is_active = st.session_state.active_tab == step["tab"]
    step_class = "active-step" if is_active else "inactive-step"

    st.sidebar.markdown(
        f'<div class="workflow-step {step_class}">{step["label"]}</div>',
        unsafe_allow_html=True,
    )

    if is_active:
        for line in step["caption"].split("\n"):
            if line.strip():
                st.sidebar.caption(line.strip())

st.sidebar.markdown("---")
st.sidebar.info("Having Trouble? Visit the FAQ page above for more information.")

if st.session_state.active_tab == "Site Selection Map":
    st.title(
        "🗺️ Site Selection",
        anchor=None,
        help=H("site.title"),
    )

    if "points" not in st.session_state:
        st.session_state.points = []

    if "upload_file" not in st.session_state:
        st.session_state.upload_file = []

    geojson_str, tooltip_fields = load_geojson_fragment(
        simplified_geojson,
        local_shapefile,
    )

    controls_col, map_col = st.columns([1, 2], gap="large")

    with controls_col:
        with st.expander(
            label="Add Point by latitude/longitude or look up an address",
            expanded=False,
        ):
            st.subheader("Go to Lat/Lon")

            lat_lon_col1, lat_lon_col2 = st.columns(2)

            with lat_lon_col1:
                lat = st.number_input(
                    "Latitude",
                    value=45.5,
                    format="%.3f",
                    help=None,
                )

            with lat_lon_col2:
                lon = st.number_input(
                    "Longitude",
                    value=-118.0,
                    format="%.3f",
                    help=None,
                )

            add_point_button = st.button("Add Point to Map", use_container_width=True)

            st.subheader("Go to Address")

            street = st.text_input("Street Address")
            city = st.text_input("City/Town")
            state = st.text_input("State")

            go_address_button = st.button("Go to Address", use_container_width=True)

        if add_point_button:
            new_pt = Point(lon, lat)

            # Replace prior point instead of stacking multiple markers.
            st.session_state.points = [new_pt]

            st.session_state["last_added_type"] = "point"
            st.session_state["last_point"] = new_pt

            matched = auto_select_variant_from_point(new_pt, geojson_str)

            if matched:
                st.success(
                    "Latitude/Longitude matched a supported FVS variant. Variant auto-selected."
                )
            else:
                st.warning("Latitude/Longitude does not intersect a supported FVS variant.")

            st.rerun()

        if go_address_button:
            full_address = ", ".join(filter(None, [street, city, state]))

            if full_address:
                geolocator = Nominatim(user_agent="streamlit_map_app")
                location = geolocator.geocode(full_address)

                if location:
                    new_pt = Point(location.longitude, location.latitude)

                    # Replace prior point instead of stacking multiple markers.
                    st.session_state.points = [new_pt]

                    st.session_state["last_added_type"] = "point"
                    st.session_state["last_point"] = new_pt

                    matched = auto_select_variant_from_point(new_pt, geojson_str)

                    if matched:
                        st.success(
                            "Address matched a supported FVS variant. Variant auto-selected."
                        )
                    else:
                        st.warning(
                            "Address found, but it does not intersect a supported FVS variant polygon."
                        )

                    st.rerun()

                else:
                    st.error("Address not found.")
            else:
                st.error("Enter at least one field for address, city, or state.")

        with st.expander(label="Upload GeoJSON/Shapefile", expanded=False):
            uploaded_files = st.file_uploader(
                "Upload GeoJSON (.geojson) or all shapefile components seperatly (.shp, .shx, .dbf, .prj) or zipped (.zip)",
                accept_multiple_files=True,
                type=["geojson", "shp", "shx", "dbf", "prj", "cpg", "zip"],
            )

            upload_button = st.button("Upload file to map", use_container_width=True)
            reset_button = st.button("Reset file uploads", use_container_width=True)

            st.markdown("---")
            st.caption(
                "Large zipped shapefile upload: use this when Cloud Run rejects the normal upload. "
                "The browser uploads the ZIP directly to temporary Google Cloud Storage."
            )

            large_upload_name = st.text_input(
                "Large ZIP filename",
                value="site_selection_upload.zip",
                help="This name is only used for the temporary GCS object path.",
            )

            if st.button("Prepare large ZIP upload", use_container_width=True):
                object_name = make_site_upload_object_name(large_upload_name)
                try:
                    signed_url, gcs_uri = create_signed_upload_url(object_name)
                    st.session_state["large_upload_signed_url"] = signed_url
                    st.session_state["large_upload_gcs_uri"] = gcs_uri
                    st.success(
                        "Signed upload URL created. Choose your ZIP below and upload it to GCS."
                    )
                except Exception as e:
                    st.error(f"Could not create signed upload URL: {e}")

            if st.session_state.get("large_upload_signed_url"):
                signed_url_json = json.dumps(st.session_state["large_upload_signed_url"])
                components.html(
                    f"""
                    <div style="font-family: sans-serif; border: 1px solid #ddd; border-radius: 6px; padding: 12px; max-width: 660px;">
                      <label style="display:block; font-weight:600; margin-bottom:8px;">Choose zipped shapefile for direct GCS upload</label>
                      <input id="gcs-file" type="file" accept=".zip" />
                      <button id="gcs-upload" style="margin-left:8px; padding:4px 10px;">Upload to GCS</button>
                      <div id="gcs-status" style="margin-top:10px; color:#555;">Waiting for file...</div>
                      <script>
                        const signedUrl = {signed_url_json};
                        const status = document.getElementById('gcs-status');
                        document.getElementById('gcs-upload').onclick = async () => {{
                          const fileInput = document.getElementById('gcs-file');
                          if (!fileInput.files.length) {{
                            status.textContent = 'Choose a .zip file first.';
                            status.style.color = '#b00020';
                            return;
                          }}
                          const file = fileInput.files[0];
                          status.textContent = `Uploading ${{file.name}} (${{(file.size / 1048576).toFixed(1)}} MB)...`;
                          status.style.color = '#555';
                          try {{
                            const response = await fetch(signedUrl, {{
                              method: 'PUT',
                              headers: {{'Content-Type': 'application/zip'}},
                              body: file
                            }});
                            if (!response.ok) {{
                              throw new Error(`Upload failed: HTTP ${{response.status}} ${{response.statusText}}`);
                            }}
                            status.textContent = 'Upload complete. Now click "Process large GCS upload" in Streamlit.';
                            status.style.color = '#177233';
                          }} catch (err) {{
                            status.textContent = err.toString();
                            status.style.color = '#b00020';
                          }}
                        }};
                      </script>
                    </div>
                    """,
                    height=150,
                )
                st.caption(
                    f"Temporary upload target: `{st.session_state['large_upload_gcs_uri']}`"
                )

            process_large_upload_button = st.button(
                "Process large GCS upload",
                disabled=not bool(st.session_state.get("large_upload_gcs_uri")),
                use_container_width=True,
            )

        if upload_button:
            for key in [
                "upload_file",
                "uploaded_geojson_str",
                "uploaded_tooltip_fields",
                "upload_auto_selected",
            ]:
                if key in st.session_state:
                    del st.session_state[key]

            if uploaded_files:
                if len(uploaded_files) == 1 and uploaded_files[0].name.lower().endswith(
                    ".zip"
                ):
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

                    extracted_full_paths = [
                        os.path.join(tmpdir, f) for f in extracted_files
                    ]

                    geojson_target = next(
                        (
                            f
                            for f in extracted_full_paths
                            if f.lower().endswith(".geojson")
                        ),
                        None,
                    )
                    shp_target = next(
                        (f for f in extracted_full_paths if f.lower().endswith(".shp")),
                        None,
                    )

                    if geojson_target:
                        st.session_state.upload_file = [geojson_target]
                    elif shp_target:
                        st.session_state.upload_file = extracted_full_paths
                    else:
                        st.error("No .shp or .geojson file found inside ZIP.")
                else:
                    st.write("Not a ZIP file or multiple files uploaded.")
                    st.session_state.upload_file = uploaded_files

        if process_large_upload_button:
            for key in [
                "upload_file",
                "uploaded_geojson_str",
                "uploaded_tooltip_fields",
                "upload_auto_selected",
            ]:
                if key in st.session_state:
                    del st.session_state[key]

            gcs_uri = st.session_state.get("large_upload_gcs_uri")
            if not gcs_uri:
                st.error("Prepare and upload a large ZIP file first.")
            else:
                try:
                    with st.spinner("Downloading uploaded ZIP from temporary cloud storage..."):
                        zip_path = download_gcs_object_to_tempfile(gcs_uri, suffix=".zip")

                    tmpdir = tempfile.mkdtemp()
                    with zipfile.ZipFile(zip_path, "r") as zip_ref:
                        zip_ref.extractall(tmpdir)

                    extracted_full_paths = [
                        str(path) for path in Path(tmpdir).rglob("*") if path.is_file()
                    ]

                    geojson_target = next(
                        (
                            f
                            for f in extracted_full_paths
                            if f.lower().endswith(".geojson")
                        ),
                        None,
                    )
                    shp_target = next(
                        (f for f in extracted_full_paths if f.lower().endswith(".shp")),
                        None,
                    )

                    if geojson_target:
                        st.session_state.upload_file = [geojson_target]
                        st.success("Large ZIP downloaded and prepared for map processing.")
                        try:
                            delete_gcs_object(gcs_uri)
                            st.session_state.pop("large_upload_signed_url", None)
                            st.session_state.pop("large_upload_gcs_uri", None)
                        except Exception as cleanup_error:
                            st.warning(
                                f"Upload was processed, but temporary GCS cleanup failed: {cleanup_error}"
                            )
                    elif shp_target:
                        st.session_state.upload_file = extracted_full_paths
                        st.success("Large ZIP downloaded and prepared for map processing.")
                        try:
                            delete_gcs_object(gcs_uri)
                            st.session_state.pop("large_upload_signed_url", None)
                            st.session_state.pop("large_upload_gcs_uri", None)
                        except Exception as cleanup_error:
                            st.warning(
                                f"Upload was processed, but temporary GCS cleanup failed: {cleanup_error}"
                            )
                    else:
                        st.error("No .shp or .geojson file found inside uploaded ZIP.")
                except Exception as e:
                    st.error(f"Could not process large GCS upload: {e}")

        uploaded_geojson_str, uploaded_tooltip_fields = None, None

        if st.session_state.upload_file:
            uploaded_geojson_str, uploaded_tooltip_fields = load_geojson_or_shapefile(
                st.session_state.upload_file
            )

            st.session_state["last_added_type"] = "upload"
            st.session_state["last_upload"] = uploaded_geojson_str

            if uploaded_geojson_str and not st.session_state.get("upload_auto_selected"):
                matched = auto_select_variant_from_upload(
                    uploaded_geojson_str,
                    geojson_str,
                )

                st.session_state["upload_auto_selected"] = True

                if matched:
                    st.success(
                        "Uploaded geometry matched a supported FVS variant. Variant auto-selected."
                    )
                else:
                    st.warning(
                        "Uploaded geometry does not intersect a supported FVS variant."
                    )

    _process_pending_click(geojson_str)

    st.session_state.setdefault(
        "map_view",
        {"center": [45.5, -118], "zoom": 6},
    )

    with map_col:
        st.subheader(
            "Select FVS Variant",
            anchor=None,
            divider=False,
            help=H("site.subheader_select_variant"),
        )

        m = build_map(
            geojson_str,
            points=st.session_state.points,
            upload=uploaded_geojson_str,
            center=tuple(st.session_state["map_view"]["center"]),
            zoom=int(st.session_state["map_view"]["zoom"]),
            tooltip_fields=tooltip_fields,
        )

        highlight_fg = build_highlight_layer(st.session_state.get("clicked_feature"))

        map_data = st_folium(
            m,
            key="fvs_map",
            height=500,
            use_container_width=True,
            returned_objects=["last_active_drawing", "last_clicked"],
            feature_group_to_add=highlight_fg,
        )

    with controls_col:
        show_clicked_variant(map_data)
        display_selected_info()
        variant_chooser()

        st.divider()

        location_selected = bool(st.session_state.get("selected_variant"))

        disabled_msg = (
            "Select a location first using Step 1: click the map, enter coordinates/address, "
            "or upload a shapefile/GeoJSON."
        )

        nav_col1, nav_col2 = st.columns(2)

        with nav_col1:
            if location_selected:
                if st.button(
                    "➡️ Planting Design",
                    use_container_width=True,
                    help=H("site.button_forward_to_planting"),
                    type="primary",
                ):
                    st.session_state.active_tab = "Planting Design"
                    st.rerun()
            else:
                st.button(
                    "➡️ Planting Design",
                    use_container_width=True,
                    help=disabled_msg,
                    type="primary",
                    disabled=True,
                )

        with nav_col2:
            if location_selected:
                if st.button(
                    "🧮 Solver",
                    use_container_width=True,
                    help=H("site.button_forward_to_solver"),
                ):
                    st.session_state.active_tab = "Solver"
                    st.rerun()
            else:
                st.button(
                    "🧮 Solver",
                    use_container_width=True,
                    help=disabled_msg,
                    disabled=True,
                )

        if reset_button:
            for key in [
                "upload_file",
                "uploaded_geojson_str",
                "uploaded_tooltip_fields",
                "last_upload",
                "upload_auto_selected",
                "large_upload_signed_url",
                "large_upload_gcs_uri",
            ]:
                if key in st.session_state:
                    del st.session_state[key]

            st.rerun()

elif st.session_state.active_tab == "Planting Design":
    col1, col2 = st.columns([8, 3])

    with col1:
        st.title(
            "🌲 Planting Design",
            anchor=None,
            help=H("planting.title"),
        )

    with col2:
        if st.button(
            "⬅️ Site Selection",
            use_container_width=True,
            help=H("planting.button_back_to_site"),
            type="primary",
        ):
            st.session_state.active_tab = "Site Selection Map"
            st.rerun()

    run_chart()

elif st.session_state.active_tab == "Solver":
    col1, col2, col3 = st.columns([6, 3, 3])

    with col1:
        st.title("🧮 Solver", anchor=None, help=H("solver.title"))

    with col2:
        if st.button(
            "⬅️ Site Selection",
            use_container_width=True,
            help=H("planting.button_back_to_site"),
            type="primary",
        ):
            st.session_state.active_tab = "Site Selection Map"
            st.rerun()

    with col3:
        if st.button(
            "🌲 Planting Design",
            use_container_width=True,
            help=H("site.button_forward_to_planting"),
        ):
            # Carry the solver's current design inputs over (not a solved value)
            prefill = current_solver_prefill()
            if prefill:
                st.session_state["_planting_prefill"] = prefill
            st.session_state.active_tab = "Planting Design"
            st.rerun()

    run_solver()
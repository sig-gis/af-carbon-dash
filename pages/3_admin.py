"""Model management admin page.

Upload new regression models, inspect the registry, and manage the model store.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path

import joblib
import requests
import streamlit as st

from model_service.store import get_store
from utils.config import get_api_base_url
from utils.functions.slider_bounds import slider_bounds

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = APP_ROOT / "conf" / "base"

# ---------------------------------------------------------------------------
# Load reference data (static configs shipped with the image)
# ---------------------------------------------------------------------------


@st.cache_data
def _load_variant_species() -> dict:
    return get_store().get_json("config/variant_species.json")


@st.cache_data
def _load_species_labels() -> dict:
    with open(BASE_PATH / "species_labels.json") as f:
        return json.load(f)


@st.cache_data
def _load_variant_presets() -> dict:
    return get_store().get_json("config/FVSVariant_presets.json")


@st.cache_data
def _load_geojson_locations() -> dict[str, list[dict]]:
    """Parse GeoJSON for known variant-location pairs with names.

    Returns {base_variant: [{loccode, locname}, ...]}
    """
    store = get_store()
    try:
        gj_path = store.get_file(
            "geo/FVS_Variants_and_Locations_4326_simplified_full.geojson"
        )
    except FileNotFoundError:
        try:
            gj_path = store.get_file(
                "geo/FVS_Variants_and_Locations_4326_simplified.geojson"
            )
        except FileNotFoundError:
            return {}

    gj = json.loads(gj_path.read_text())
    by_variant: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        v = props.get("FVSVariant", "")
        lc = str(props.get("FVSLocCode", ""))
        if (v, lc) in seen:
            continue
        seen.add((v, lc))
        by_variant.setdefault(v, []).append(
            {"loccode": lc, "locname": props.get("FVSLocName", "")}
        )
    return by_variant


# ---------------------------------------------------------------------------
# Filename inference
# ---------------------------------------------------------------------------

_FILENAME_RE = re.compile(
    r"^(?P<variant>[A-Z]+(?:_\d+)?)_v(?P<version>\d+)_(?P<pct>PCT\d+)"
    r"_(?P<method>\w+)_(?P<loccode>\d+)_ridge_models\.pkl$"
)


def _infer_from_filename(name: str) -> dict | None:
    m = _FILENAME_RE.match(name)
    return m.groupdict() if m else None


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def _validate_model(path: Path) -> dict:
    """Load a model file and return summary metadata."""
    models = joblib.load(path)
    if not isinstance(models, dict):
        raise ValueError("Expected a dict keyed by (year, variable) tuples")

    sample_key = next(iter(models))
    if not (isinstance(sample_key, tuple) and len(sample_key) == 2):
        raise ValueError(f"Keys must be (year, variable) tuples, got {type(sample_key)}")

    sample_model = models[sample_key]
    n_features = getattr(sample_model, "n_features_in_", None)

    years = sorted({int(k[0]) for k in models})
    variables = sorted({k[1] for k in models})

    return {
        "n_entries": len(models),
        "years": years,
        "variables": variables,
        "n_features": n_features,
        "model_format": "v4 pipeline" if n_features == 7 else "v3 polynomial",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_variant(variant: str) -> str:
    """CR_1 -> CR, WS_1 -> WS, PN -> PN."""
    return variant.rsplit("_", 1)[0] if "_" in variant else variant


# ---------------------------------------------------------------------------
# Upload tab (extracted so early returns don't exit main)
# ---------------------------------------------------------------------------


def _render_upload_tab(
    known_variants: list[str],
    pct_options: list[str],
    variant_species: dict,
    species_labels: dict,
    variant_presets: dict,
    geo_locations: dict,
) -> None:
    uploaded_files = st.file_uploader(
        "Upload regression models (.pkl)",
        type=["pkl"],
        accept_multiple_files=True,
        help="Naming convention: {Variant}_v{Version}_{PCT}_Jenkins_{LocCode}_ridge_models.pkl",
    )

    if not uploaded_files:
        return

    _PCT_RETENTION_DEFAULTS = {"PCT0": 100, "PCT1": 85, "PCT2": 65}

    # ── Validate all files ────────────────────────────────────────
    file_entries: list[dict] = []
    for uploaded in uploaded_files:
        tmp = Path(tempfile.gettempdir()) / uploaded.name
        tmp.write_bytes(uploaded.getvalue())
        try:
            info = _validate_model(tmp)
        except Exception as e:
            st.error(f"**{uploaded.name}**: validation failed — {e}")
            continue
        inferred = _infer_from_filename(uploaded.name)
        file_entries.append({
            "uploaded": uploaded,
            "tmp": tmp,
            "info": info,
            "inferred": inferred,
        })

    if not file_entries:
        return

    valid_count = len(file_entries)
    st.success(f"{valid_count} file{'s' if valid_count != 1 else ''} validated")

    # ── Per-file metadata editing ─────────────────────────────────
    file_configs: list[dict] = []
    for idx, entry in enumerate(file_entries):
        info = entry["info"]
        inferred = entry["inferred"]
        fname = entry["uploaded"].name

        with st.expander(
            f"**{fname}** — {info['model_format']}, "
            f"{info['n_entries']} entries, "
            f"years {info['years'][0]}–{info['years'][-1]}",
            expanded=idx == 0,
        ):
            inferred_variant = inferred["variant"] if inferred else ""
            inferred_loc = inferred["loccode"] if inferred else ""
            inferred_pct = inferred["pct"] if inferred else "PCT0"

            c1, c2, c3, c4, c5 = st.columns([2, 3, 1, 1, 1])

            with c1:
                options = sorted(
                    set(known_variants) | ({inferred_variant} if inferred_variant else set())
                )
                default_var_idx = (
                    options.index(inferred_variant)
                    if inferred_variant in options
                    else 0
                )
                variant = st.selectbox(
                    "Variant", options=options,
                    index=default_var_idx, key=f"var_{idx}",
                )

            with c2:
                base_v = _base_variant(variant)
                locations = geo_locations.get(base_v, [])
                loc_labels = {
                    loc["loccode"]: f"{loc['loccode']} — {loc['locname']}"
                    for loc in locations
                }
                loc_codes = list(loc_labels.keys())

                if loc_codes:
                    if inferred_loc and inferred_loc not in loc_codes:
                        loc_codes.append(inferred_loc)
                        loc_labels[inferred_loc] = f"{inferred_loc} — (new)"
                    default_loc_idx = (
                        loc_codes.index(inferred_loc)
                        if inferred_loc in loc_codes else 0
                    )
                    loccode = st.selectbox(
                        "Location", options=loc_codes,
                        index=default_loc_idx,
                        format_func=lambda x, _ll=loc_labels: _ll.get(x, x),
                        key=f"loc_{idx}",
                    )
                else:
                    loccode = st.text_input(
                        "Location code", value=inferred_loc,
                        key=f"loc_{idx}",
                    )

            with c3:
                pct_idx = (
                    pct_options.index(inferred_pct)
                    if inferred_pct in pct_options else 0
                )
                pct_level = st.selectbox(
                    "PCT", options=pct_options,
                    index=pct_idx, key=f"pct_{idx}",
                )

            with c4:
                retention_pct = st.number_input(
                    "Retention %", min_value=0, max_value=100,
                    value=_PCT_RETENTION_DEFAULTS.get(pct_level, 100),
                    key=f"ret_{idx}",
                    help="Percentage of stand retained after thinning",
                )

            with c5:
                version = st.text_input(
                    "Version",
                    value=inferred["version"] if inferred else "4",
                    key=f"ver_{idx}",
                )

            file_configs.append({
                "idx": idx,
                "tmp": entry["tmp"],
                "filename": fname,
                "variant": variant,
                "loccode": loccode,
                "pct_level": pct_level,
                "pct_retention": retention_pct,
                "version": version,
            })

    if not file_configs:
        return

    # ── Per-variant species & planting defaults ───────────────────
    variants_in_batch: dict[str, list[dict]] = {}
    for fc in file_configs:
        variants_in_batch.setdefault(fc["variant"], []).append(fc)

    variant_settings: dict[str, dict] = {}
    for v_idx, (v, _fcs) in enumerate(sorted(variants_in_batch.items())):
        label = f"Species & Defaults — {v}" if len(variants_in_batch) > 1 else "Species & Defaults"
        st.subheader(label)

        max_species = variant_species.get("_max_species", 4)
        all_species_codes = sorted(species_labels.keys())
        species_options = [""] + [
            f"{code} — {species_labels[code]}"
            for code in all_species_codes
        ]
        current_species = variant_species.get(v, [])

        selected_species: list[str] = []
        sp_cols = st.columns(max_species)
        for i in range(max_species):
            with sp_cols[i]:
                default_code = current_species[i] if i < len(current_species) else ""
                default_display = (
                    f"{default_code} — {species_labels.get(default_code, default_code)}"
                    if default_code else ""
                )
                default_sp_idx = (
                    species_options.index(default_display)
                    if default_display in species_options else 0
                )
                if i == 0 or selected_species:
                    choice = st.selectbox(
                        f"SP{i + 1}", options=species_options,
                        index=default_sp_idx,
                        format_func=lambda x: x if x else "—",
                        key=f"sp_select_{v_idx}_{i}",
                    )
                    if choice:
                        selected_species.append(choice.split(" — ")[0])

        if not selected_species:
            st.warning(f"At least one species is required for {v}.")

        preset = variant_presets.get(v, {})
        existing_tpa = preset.get("default_tpa", [])
        bounds = slider_bounds(preset)
        n_sp = len(selected_species) if selected_species else 0

        # Row 1: default values
        default_cols = st.columns(3)
        with default_cols[0]:
            survival = st.number_input(
                "Survival %", min_value=0, max_value=100,
                value=preset.get("survival", 70),
                key=f"preset_survival_{v_idx}",
            )
        with default_cols[1]:
            si = st.number_input(
                "Site index", min_value=0, max_value=300,
                value=preset.get("si", 120),
                key=f"preset_si_{v_idx}",
            )
        with default_cols[2]:
            tpa_cap = st.number_input(
                "TPA cap", min_value=0,
                value=preset.get("_tpa_cap", 435),
                key=f"preset_tpa_cap_{v_idx}",
            )

        # Row 2: per-variant slider bounds
        bound_cols = st.columns(4)
        with bound_cols[0]:
            survival_min = st.number_input(
                "Survival min", min_value=0, max_value=100,
                value=bounds["survival_min"],
                key=f"preset_survival_min_{v_idx}",
            )
        with bound_cols[1]:
            survival_max = st.number_input(
                "Survival max", min_value=0, max_value=100,
                value=bounds["survival_max"],
                key=f"preset_survival_max_{v_idx}",
            )
        with bound_cols[2]:
            si_min = st.number_input(
                "SI min", min_value=0, max_value=300,
                value=bounds["si_min"],
                key=f"preset_si_min_{v_idx}",
            )
        with bound_cols[3]:
            si_max = st.number_input(
                "SI max", min_value=0, max_value=300,
                value=bounds["si_max"],
                key=f"preset_si_max_{v_idx}",
            )

        # Row 3: per-species default TPA
        default_tpa: list[int] = []
        if n_sp:
            tpa_cols = st.columns(n_sp)
            for i, sp_code in enumerate(selected_species):
                with tpa_cols[i]:
                    val = st.number_input(
                        f"{sp_code} TPA", min_value=0,
                        value=int(existing_tpa[i]) if i < len(existing_tpa) else 20,
                        key=f"preset_tpa_{v_idx}_{i}",
                    )
                    default_tpa.append(val)

        variant_settings[v] = {
            "species": selected_species,
            "survival": survival,
            "si": si,
            "si_min": si_min,
            "si_max": si_max,
            "survival_min": survival_min,
            "survival_max": survival_max,
            "default_tpa": default_tpa,
            "_tpa_cap": tpa_cap,
        }

    # ── Status + confirm ──────────────────────────────────────────
    store = get_store()
    registry = store.get_json("registry.json")
    models_list = registry.get("models", [])

    for fc in file_configs:
        existing = [
            m for m in models_list
            if m.get("variant") == fc["variant"]
            and m.get("loccode") == fc["loccode"]
            and m.get("pct_level", "PCT0") == fc["pct_level"]
        ]
        if existing:
            st.caption(
                f"**{fc['filename']}**: replaces existing "
                f"{fc['variant']}/{fc['loccode']}/{fc['pct_level']}"
            )

    missing = [fc for fc in file_configs if not fc["variant"] or not fc["loccode"]]
    if missing:
        st.warning("Variant and location code are required for all models.")
        return

    missing_species = [v for v, s in variant_settings.items() if not s["species"]]
    if missing_species:
        return

    if st.button(
        f"Confirm upload ({len(file_configs)} model{'s' if len(file_configs) != 1 else ''})",
        type="primary",
    ):
        uploaded_count = 0
        for fc in file_configs:
            filename = fc["filename"]

            store.put_file(fc["tmp"], f"models/{filename}")

            models_list = [
                m for m in models_list
                if not (
                    m.get("variant") == fc["variant"]
                    and m.get("loccode") == fc["loccode"]
                    and m.get("pct_level", "PCT0") == fc["pct_level"]
                )
            ]
            models_list.append({
                "variant": fc["variant"],
                "loccode": fc["loccode"],
                "pct_level": fc["pct_level"],
                "pct_retention": fc["pct_retention"],
                "version": fc["version"],
                "filename": filename,
            })
            uploaded_count += 1

        registry["models"] = models_list
        store.put_json(registry, "registry.json")

        vs_data = store.get_json("config/variant_species.json")
        vs_changed = False
        for v, settings in variant_settings.items():
            if vs_data.get(v) != settings["species"]:
                vs_data[v] = settings["species"]
                vs_changed = True
        if vs_changed:
            store.put_json(vs_data, "config/variant_species.json")

        presets_data = store.get_json("config/FVSVariant_presets.json")
        presets_changed = False
        for v, settings in variant_settings.items():
            new_preset = {
                "survival": settings["survival"],
                "si": settings["si"],
                "si_min": settings["si_min"],
                "si_max": settings["si_max"],
                "survival_min": settings["survival_min"],
                "survival_max": settings["survival_max"],
                "default_tpa": settings["default_tpa"],
                "_tpa_cap": settings["_tpa_cap"],
            }
            if presets_data.get(v) != new_preset:
                presets_data[v] = new_preset
                presets_changed = True
        if presets_changed:
            store.put_json(presets_data, "config/FVSVariant_presets.json")

        st.success(
            f"Uploaded **{uploaded_count}** model{'s' if uploaded_count != 1 else ''} "
            f"and updated registry ({len(models_list)} total)."
        )

        try:
            resp = requests.post(
                f"{get_api_base_url()}/geo/refresh", timeout=10
            )
            resp.raise_for_status()
            n = resp.json().get("features", 0)
            st.caption(f"API GeoJSON refreshed ({n} features)")
        except Exception as e:
            st.warning(f"Could not refresh API GeoJSON cache: {e}")

        st.cache_data.clear()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


def main() -> None:
    st.title("Model Management")

    variant_species = _load_variant_species()
    species_labels = _load_species_labels()
    variant_presets = _load_variant_presets()
    geo_locations = _load_geojson_locations()

    # Build option lists
    known_variants = sorted(
        k for k in variant_species if not k.startswith("_")
    )
    pct_options = ["PCT0", "PCT1", "PCT2"]

    tab_upload, tab_edit, tab_registry = st.tabs(["Upload Model", "Edit Model", "Registry"])

    # ── Upload tab ────────────────────────────────────────────────────────
    with tab_upload:
        _render_upload_tab(
            known_variants, pct_options, variant_species,
            species_labels, variant_presets, geo_locations,
        )

    # ── Edit tab ─────────────────────────────────────────────────────────
    with tab_edit:
        @st.fragment
        def _edit_fragment():
            store = get_store()
            registry = store.get_json("registry.json")
            models_list = registry.get("models", [])

            if not models_list:
                st.info("No models registered yet. Upload a model first.")
                return

            # Stable sort so indices don't shift between reruns
            models_list.sort(
                key=lambda m: (
                    m.get("variant", ""),
                    m.get("loccode", ""),
                    m.get("pct_level", ""),
                )
            )

            def _model_key(m: dict) -> str:
                return f"{m['variant']}|{m['loccode']}|{m.get('pct_level', 'PCT0')}"

            def _model_label(m: dict) -> str:
                pct = m.get("pct_level", "PCT0")
                ret = m.get("pct_retention")
                ret_str = f" ({ret}%)" if ret is not None else ""
                return (
                    f"{m['variant']} / {m['loccode']} / "
                    f"{pct}{ret_str} / v{m.get('version', '?')}"
                )

            model_keys = [_model_key(m) for m in models_list]
            model_labels = {_model_key(m): _model_label(m) for m in models_list}

            # Apply pending selection (set before rerun after save)
            pending = st.session_state.pop("_pending_edit_select", None)
            if pending and pending in model_keys:
                st.session_state["edit_model_select"] = pending

            selected_key = st.selectbox(
                "Select model to edit",
                options=model_keys,
                format_func=lambda k: model_labels[k],
                key="edit_model_select",
            )
            selected_model = models_list[model_keys.index(selected_key)]

            st.divider()

            _PCT_RETENTION_DEFAULTS = {"PCT0": 100, "PCT1": 85, "PCT2": 65}

            # ── Editable model fields ────────────────────────────────
            ec1, ec2, ec3, ec4, ec5 = st.columns([2, 3, 1, 1, 1])

            with ec1:
                cur_var = selected_model["variant"]
                options = sorted(
                    set(known_variants) | ({cur_var} if cur_var else set())
                )
                edit_var_idx = options.index(cur_var) if cur_var in options else 0
                edit_variant = st.selectbox(
                    "Variant", options=options,
                    index=edit_var_idx, key="edit_variant",
                )

            with ec2:
                base_v = _base_variant(edit_variant)
                locations = geo_locations.get(base_v, [])
                loc_labels = {
                    loc["loccode"]: f"{loc['loccode']} — {loc['locname']}"
                    for loc in locations
                }
                loc_codes = list(loc_labels.keys())
                cur_loc = selected_model.get("loccode", "")

                if loc_codes:
                    if cur_loc and cur_loc not in loc_codes:
                        loc_codes.append(cur_loc)
                        loc_labels[cur_loc] = f"{cur_loc} — (unlisted)"
                    default_loc_idx = (
                        loc_codes.index(cur_loc) if cur_loc in loc_codes else 0
                    )
                    edit_loccode = st.selectbox(
                        "Location", options=loc_codes,
                        index=default_loc_idx,
                        format_func=lambda x, _ll=loc_labels: _ll.get(x, x),
                        key="edit_loccode",
                    )
                else:
                    edit_loccode = st.text_input(
                        "Location code", value=cur_loc, key="edit_loccode",
                    )

            with ec3:
                cur_pct = selected_model.get("pct_level", "PCT0")
                edit_pct_idx = (
                    pct_options.index(cur_pct) if cur_pct in pct_options else 0
                )
                edit_pct = st.selectbox(
                    "PCT", options=pct_options,
                    index=edit_pct_idx, key="edit_pct",
                )

            with ec4:
                cur_ret = selected_model.get("pct_retention")
                edit_retention = st.number_input(
                    "Retention %", min_value=0, max_value=100,
                    value=cur_ret if cur_ret is not None else _PCT_RETENTION_DEFAULTS.get(edit_pct, 100),
                    key="edit_retention",
                    help="Percentage of stand retained after thinning",
                )

            with ec5:
                edit_version = st.text_input(
                    "Version",
                    value=selected_model.get("version", "4"),
                    key="edit_version",
                )

            # ── Species & planting defaults for this variant ──────────
            st.subheader("Species & Defaults")

            max_species = variant_species.get("_max_species", 4)
            all_species_codes = sorted(species_labels.keys())
            species_options = [""] + [
                f"{code} — {species_labels[code]}"
                for code in all_species_codes
            ]
            current_species = variant_species.get(edit_variant, [])

            edit_species: list[str] = []
            sp_cols = st.columns(max_species)
            for i in range(max_species):
                with sp_cols[i]:
                    default_code = current_species[i] if i < len(current_species) else ""
                    default_display = (
                        f"{default_code} — {species_labels.get(default_code, default_code)}"
                        if default_code else ""
                    )
                    default_sp_idx = (
                        species_options.index(default_display)
                        if default_display in species_options else 0
                    )
                    if i == 0 or edit_species:
                        choice = st.selectbox(
                            f"SP{i + 1}", options=species_options,
                            index=default_sp_idx,
                            format_func=lambda x: x if x else "—",
                            key=f"edit_sp_{i}",
                        )
                        if choice:
                            edit_species.append(choice.split(" — ")[0])

            preset = variant_presets.get(edit_variant, {})
            existing_tpa = preset.get("default_tpa", [])
            bounds = slider_bounds(preset)
            n_sp = len(edit_species) if edit_species else 0

            # Row 1: default values
            default_cols = st.columns(3)
            with default_cols[0]:
                edit_survival = st.number_input(
                    "Survival %", min_value=0, max_value=100,
                    value=preset.get("survival", 70), key="edit_survival",
                )
            with default_cols[1]:
                edit_si = st.number_input(
                    "Site index", min_value=0, max_value=300,
                    value=preset.get("si", 120), key="edit_si",
                )
            with default_cols[2]:
                edit_tpa_cap = st.number_input(
                    "TPA cap", min_value=0,
                    value=preset.get("_tpa_cap", 435), key="edit_tpa_cap",
                )

            # Row 2: per-variant slider bounds
            bound_cols = st.columns(4)
            with bound_cols[0]:
                edit_survival_min = st.number_input(
                    "Survival min", min_value=0, max_value=100,
                    value=bounds["survival_min"], key="edit_survival_min",
                )
            with bound_cols[1]:
                edit_survival_max = st.number_input(
                    "Survival max", min_value=0, max_value=100,
                    value=bounds["survival_max"], key="edit_survival_max",
                )
            with bound_cols[2]:
                edit_si_min = st.number_input(
                    "SI min", min_value=0, max_value=300,
                    value=bounds["si_min"], key="edit_si_min",
                )
            with bound_cols[3]:
                edit_si_max = st.number_input(
                    "SI max", min_value=0, max_value=300,
                    value=bounds["si_max"], key="edit_si_max",
                )

            # Row 3: per-species default TPA
            edit_tpa: list[int] = []
            if n_sp:
                tpa_cols = st.columns(n_sp)
                for i, sp_code in enumerate(edit_species):
                    with tpa_cols[i]:
                        val = st.number_input(
                            f"{sp_code} TPA", min_value=0,
                            value=int(existing_tpa[i]) if i < len(existing_tpa) else 20,
                            key=f"edit_tpa_{i}",
                        )
                        edit_tpa.append(val)

            # ── Save / Delete ─────────────────────────────────────────
            st.divider()
            btn_cols = st.columns([1, 1, 4])

            with btn_cols[0]:
                save_clicked = st.button("Save changes", type="primary", key="edit_save")
            with btn_cols[1]:
                delete_clicked = st.button("Delete model", type="secondary", key="edit_delete")

            if save_clicked:
                if not edit_variant or not edit_loccode:
                    st.warning("Variant and location code are required.")
                elif not edit_species:
                    st.warning("At least one species is required.")
                else:
                    # Remove old entry
                    old = selected_model
                    models_list = [
                        m for m in models_list
                        if not (
                            m.get("variant") == old["variant"]
                            and m.get("loccode") == old["loccode"]
                            and m.get("pct_level", "PCT0") == old.get("pct_level", "PCT0")
                        )
                    ]
                    # Also remove any entry at the new location (in case of move)
                    models_list = [
                        m for m in models_list
                        if not (
                            m.get("variant") == edit_variant
                            and m.get("loccode") == edit_loccode
                            and m.get("pct_level", "PCT0") == edit_pct
                        )
                    ]
                    # Insert updated entry
                    models_list.append({
                        "variant": edit_variant,
                        "loccode": edit_loccode,
                        "pct_level": edit_pct,
                        "pct_retention": edit_retention,
                        "version": edit_version,
                        "filename": old.get("filename") or Path(old.get("path", "")).name,
                    })
                    registry["models"] = models_list
                    store.put_json(registry, "registry.json")

                    vs_data = store.get_json("config/variant_species.json")
                    if vs_data.get(edit_variant) != edit_species:
                        vs_data[edit_variant] = edit_species
                        store.put_json(vs_data, "config/variant_species.json")

                    presets_data = store.get_json("config/FVSVariant_presets.json")
                    new_preset = {
                        "survival": edit_survival,
                        "si": edit_si,
                        "si_min": edit_si_min,
                        "si_max": edit_si_max,
                        "survival_min": edit_survival_min,
                        "survival_max": edit_survival_max,
                        "default_tpa": edit_tpa,
                        "_tpa_cap": edit_tpa_cap,
                    }
                    if presets_data.get(edit_variant) != new_preset:
                        presets_data[edit_variant] = new_preset
                        store.put_json(presets_data, "config/FVSVariant_presets.json")

                    # Queue selection for next rerun (can't set widget key after render)
                    st.session_state["_pending_edit_select"] = (
                        f"{edit_variant}|{edit_loccode}|{edit_pct}"
                    )

                    st.success(
                        f"Updated **{edit_variant}/{edit_loccode}/{edit_pct}**"
                    )

                    # Refresh GeoJSON + caches
                    try:
                        resp = requests.post(
                            f"{get_api_base_url()}/geo/refresh", timeout=10
                        )
                        resp.raise_for_status()
                    except Exception:
                        pass
                    st.cache_data.clear()
                    st.rerun(scope="fragment")

            if delete_clicked:
                old = selected_model
                models_list = [
                    m for m in models_list
                    if not (
                        m.get("variant") == old["variant"]
                        and m.get("loccode") == old["loccode"]
                        and m.get("pct_level", "PCT0") == old.get("pct_level", "PCT0")
                    )
                ]
                registry["models"] = models_list
                store.put_json(registry, "registry.json")

                label = (
                    f"{old['variant']}/{old['loccode']}/"
                    f"{old.get('pct_level', 'PCT0')}"
                )
                st.success(f"Deleted **{label}** from registry.")

                try:
                    resp = requests.post(
                        f"{get_api_base_url()}/geo/refresh", timeout=10
                    )
                    resp.raise_for_status()
                except Exception:
                    pass
                st.cache_data.clear()
                st.rerun(scope="fragment")

        _edit_fragment()

    # ── Registry tab ──────────────────────────────────────────────────────
    with tab_registry:
        store = get_store()
        registry = store.get_json("registry.json")
        models_list = registry.get("models", [])

        if not models_list:
            st.info("No models registered yet.")
        else:
            st.metric("Total models", len(models_list))

            # Group by variant
            variants: dict[str, list[dict]] = {}
            for m in models_list:
                variants.setdefault(m["variant"], []).append(m)

            for v in sorted(variants):
                sp_codes = variant_species.get(v, [])
                sp_str = (
                    " — " + ", ".join(
                        f"{c} ({species_labels.get(c, c)})" for c in sp_codes
                    )
                    if sp_codes
                    else ""
                )
                with st.expander(f"**{v}** — {len(variants[v])} models{sp_str}"):
                    for m in sorted(
                        variants[v],
                        key=lambda x: (x["loccode"], x.get("pct_level", "")),
                    ):
                        fn = m.get("filename") or Path(m.get("path", "")).name
                        lc = m["loccode"]
                        # Try to show location name
                        base = _base_variant(v)
                        locs = geo_locations.get(base, [])
                        locname = next(
                            (l["locname"] for l in locs if l["loccode"] == lc),
                            "",
                        )
                        label = f"{lc} — {locname}" if locname else lc
                        pct_lbl = m.get("pct_level", "PCT0")
                        ret = m.get("pct_retention")
                        if ret is not None:
                            pct_lbl += f" ({ret}%)"
                        st.text(
                            f"  {label}  |  {pct_lbl}  |  "
                            f"v{m.get('version', '?')}  |  {fn}"
                        )


main()

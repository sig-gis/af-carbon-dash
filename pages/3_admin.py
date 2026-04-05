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

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = APP_ROOT / "conf" / "base"

# ---------------------------------------------------------------------------
# Load reference data (static configs shipped with the image)
# ---------------------------------------------------------------------------


@st.cache_data
def _load_variant_species() -> dict:
    with open(BASE_PATH / "variant_species.json") as f:
        return json.load(f)


@st.cache_data
def _load_species_labels() -> dict:
    with open(BASE_PATH / "species_labels.json") as f:
        return json.load(f)


@st.cache_data
def _load_variant_presets() -> dict:
    with open(BASE_PATH / "FVSVariant_presets.json") as f:
        return json.load(f)


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

    tab_upload, tab_registry = st.tabs(["Upload Model", "Registry"])

    # ── Upload tab ────────────────────────────────────────────────────────
    with tab_upload:
        uploaded = st.file_uploader(
            "Upload a regression model (.pkl)",
            type=["pkl"],
            help="Naming convention: {Variant}_v{Version}_{PCT}_Jenkins_{LocCode}_ridge_models.pkl",
        )

        if uploaded is not None:
            inferred = _infer_from_filename(uploaded.name)

            # Write to temp file for validation
            tmp = Path(tempfile.gettempdir()) / uploaded.name
            tmp.write_bytes(uploaded.getvalue())

            try:
                info = _validate_model(tmp)
            except Exception as e:
                st.error(f"Validation failed: {e}")
                return

            st.success(
                f"Valid **{info['model_format']}** — "
                f"{info['n_entries']} entries, "
                f"years {info['years'][0]}–{info['years'][-1]}, "
                f"variables: {', '.join(info['variables'])}"
            )

            # ── Row 1: Variant, Location, PCT, Version ────────────────
            inferred_variant = inferred["variant"] if inferred else ""
            inferred_loc = inferred["loccode"] if inferred else ""
            inferred_pct = inferred["pct"] if inferred else "PCT0"

            r1c1, r1c2, r1c3, r1c4 = st.columns([2, 3, 1, 1])

            with r1c1:
                default_idx = (
                    known_variants.index(inferred_variant)
                    if inferred_variant in known_variants
                    else 0
                )
                variant = st.selectbox(
                    "Variant", options=known_variants, index=default_idx,
                )

            with r1c2:
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
                        loc_codes.index(inferred_loc) if inferred_loc in loc_codes else 0
                    )
                    loccode = st.selectbox(
                        "Location", options=loc_codes, index=default_loc_idx,
                        format_func=lambda x: loc_labels.get(x, x),
                    )
                else:
                    loccode = st.text_input("Location code", value=inferred_loc)

            with r1c3:
                pct_idx = (
                    pct_options.index(inferred_pct)
                    if inferred_pct in pct_options
                    else 0
                )
                pct_level = st.selectbox("PCT", options=pct_options, index=pct_idx)

            with r1c4:
                version = st.text_input(
                    "Version", value=inferred["version"] if inferred else "4"
                )

            # ── Row 2: Species (progressive, side-by-side) ────────────
            max_species = variant_species.get("_max_species", 4)
            all_species_codes = sorted(species_labels.keys())
            species_options = [""] + [
                f"{code} — {species_labels[code]}" for code in all_species_codes
            ]
            current_species = variant_species.get(variant, [])

            selected_species: list[str] = []
            sp_cols = st.columns(max_species)
            for i in range(max_species):
                with sp_cols[i]:
                    default_code = current_species[i] if i < len(current_species) else ""
                    default_display = (
                        f"{default_code} — {species_labels.get(default_code, default_code)}"
                        if default_code
                        else ""
                    )
                    default_idx = (
                        species_options.index(default_display)
                        if default_display in species_options
                        else 0
                    )
                    # Only show if previous slot is filled (or this is SP1)
                    if i == 0 or selected_species:
                        choice = st.selectbox(
                            f"SP{i + 1}", options=species_options, index=default_idx,
                            format_func=lambda x: x if x else "—",
                            key=f"sp_select_{i}",
                        )
                        if choice:
                            selected_species.append(choice.split(" — ")[0])

            if not selected_species:
                st.warning("At least one species is required.")

            # ── Row 3: Planting defaults (all one row) ────────────────
            preset = variant_presets.get(variant, {})
            existing_tpa = preset.get("default_tpa", [])

            n_sp = len(selected_species) if selected_species else 0
            preset_cols = st.columns([1, 1, 1] + [1] * n_sp)

            with preset_cols[0]:
                survival = st.number_input(
                    "Survival %", min_value=0, max_value=100,
                    value=preset.get("survival", 70), key="preset_survival",
                )
            with preset_cols[1]:
                si = st.number_input(
                    "Site index", min_value=0, max_value=300,
                    value=preset.get("si", 120), key="preset_si",
                )
            with preset_cols[2]:
                tpa_cap = st.number_input(
                    "TPA cap", min_value=0,
                    value=preset.get("_tpa_cap", 435), key="preset_tpa_cap",
                )

            default_tpa: list[int] = []
            for i, sp_code in enumerate(selected_species):
                with preset_cols[3 + i]:
                    val = st.number_input(
                        f"{sp_code} TPA", min_value=0,
                        value=int(existing_tpa[i]) if i < len(existing_tpa) else 20,
                        key=f"preset_tpa_{i}",
                    )
                    default_tpa.append(val)

            # ── Status + confirm ──────────────────────────────────────
            store = get_store()
            registry = store.get_json("registry.json")
            models_list = registry.get("models", [])
            existing = [
                m for m in models_list
                if m.get("variant") == variant and m.get("loccode") == loccode
            ]
            if existing:
                pcts = ", ".join(sorted(m.get("pct_level", "PCT0") for m in existing))
                st.caption(
                    f"Existing for {variant}/{loccode}: {pcts}. "
                    f"Uploading {pct_level} replaces current."
                )

            if not variant or not loccode:
                st.warning("Variant and location code are required.")
                return

            if st.button("Confirm upload", type="primary"):
                filename = uploaded.name
                key = f"models/{filename}"

                # 1. Upload model file
                store.put_file(tmp, key)

                # 2. Update registry (replace existing entry for same combo)
                models_list = [
                    m
                    for m in models_list
                    if not (
                        m.get("variant") == variant
                        and m.get("loccode") == loccode
                        and m.get("pct_level", "PCT0") == pct_level
                    )
                ]
                models_list.append(
                    {
                        "variant": variant,
                        "loccode": loccode,
                        "pct_level": pct_level,
                        "version": version,
                        "filename": filename,
                    }
                )
                registry["models"] = models_list
                store.put_json(registry, "registry.json")

                # 3. Update variant_species.json if species changed
                vs_path = BASE_PATH / "variant_species.json"
                with open(vs_path) as f:
                    vs_data = json.load(f)
                if vs_data.get(variant) != selected_species:
                    vs_data[variant] = selected_species
                    with open(vs_path, "w") as f:
                        json.dump(vs_data, f, indent=4)

                # 4. Update FVSVariant_presets.json if presets changed
                presets_path = BASE_PATH / "FVSVariant_presets.json"
                with open(presets_path) as f:
                    presets_data = json.load(f)
                new_preset = {
                    "survival": survival,
                    "si": si,
                    "default_tpa": default_tpa,
                    "_tpa_cap": tpa_cap,
                }
                if presets_data.get(variant) != new_preset:
                    presets_data[variant] = new_preset
                    with open(presets_path, "w") as f:
                        json.dump(presets_data, f, indent=4)

                st.success(
                    f"Uploaded **{filename}** and updated registry "
                    f"({len(models_list)} total models)."
                )

                # Tell the API to rebuild its filtered GeoJSON cache
                try:
                    resp = requests.post(
                        f"{get_api_base_url()}/geo/refresh", timeout=10
                    )
                    resp.raise_for_status()
                    n = resp.json().get("features", 0)
                    st.caption(f"API GeoJSON refreshed ({n} features)")
                except Exception as e:
                    st.warning(f"Could not refresh API GeoJSON cache: {e}")

                # Clear Streamlit caches so dashboard picks up changes
                st.cache_data.clear()

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
                        st.text(
                            f"  {label}  |  {m.get('pct_level', 'PCT0')}  |  "
                            f"v{m.get('version', '?')}  |  {fn}"
                        )


main()

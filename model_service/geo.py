"""Dynamic GeoJSON filtering based on the model registry.

The full (unfiltered) USDA FVS GeoJSON lives in the store under
``geo/FVS_Variants_and_Locations_4326_simplified_full.geojson``.  At runtime
we filter it to only the variant-location pairs that have models registered,
replacing the old Makefile + ``supported_variant_locations.yml`` workflow.
"""

from __future__ import annotations

import json
import logging

from shapely.geometry import mapping, shape

from model_service.store._protocol import ModelStore

logger = logging.getLogger(__name__)

_FULL_GEOJSON_KEY = "geo/FVS_Variants_and_Locations_4326_simplified_full.geojson"
_LEGACY_GEOJSON_KEY = "geo/FVS_Variants_and_Locations_4326_simplified.geojson"

_DISPLAY_SIMPLIFY_TOLERANCE_DEG = 0.01  # ~1.1 km at the equator
_DISPLAY_COORD_PRECISION = 5  # ~1.1 m; further trims serialized size


def get_filtered_geojson(store: ModelStore) -> dict:
    """Return GeoJSON filtered to variant-location pairs in the registry."""
    try:
        full_path = store.get_file(_FULL_GEOJSON_KEY)
    except FileNotFoundError:
        # Fall back to legacy filtered GeoJSON (local dev)
        full_path = store.get_file(_LEGACY_GEOJSON_KEY)
    full_geojson = json.loads(full_path.read_text())

    registry = store.get_json("registry.json").get("models", [])

    # Build set of supported variant-loccode pairs.
    # Registry uses sub-variant codes (CR_1, WS_1) but the GeoJSON uses
    # base variant names (CR, WS).  Strip the trailing _N suffix.
    supported: set[str] = set()
    for entry in registry:
        variant = entry["variant"]
        base = variant.rsplit("_", 1)[0] if "_" in variant else variant
        supported.add(f"{base}-{entry['loccode']}")

    filtered_features = [
        _simplify_feature(f)
        for f in full_geojson.get("features", [])
        if _feature_key(f) in supported
    ]

    logger.info(
        "GeoJSON filter: %d/%d features kept (%d registry pairs)",
        len(filtered_features),
        len(full_geojson.get("features", [])),
        len(supported),
    )

    return {**full_geojson, "features": filtered_features}


def _feature_key(feature: dict) -> str:
    props = feature.get("properties", {})
    return f"{props.get('FVSVariant', '')}-{props.get('FVSLocCode', '')}"


def _simplify_feature(feature: dict) -> dict:
    """Return a copy of ``feature`` with display-simplified, rounded geometry.

    Falls back to the original geometry if simplification fails (e.g. an
    invalid ring), so a single bad feature can never blank the whole map.
    """
    geom = feature.get("geometry")
    if not geom:
        return feature
    try:
        simplified = shape(geom).simplify(
            _DISPLAY_SIMPLIFY_TOLERANCE_DEG, preserve_topology=True
        )
        new_geom = _round_coords(mapping(simplified))
    except Exception:  # pragma: no cover - defensive, keeps original geometry
        return feature
    return {**feature, "geometry": new_geom}


def _round_coords(obj):
    """Recursively round coordinate floats to trim serialized payload size."""
    if isinstance(obj, float):
        return round(obj, _DISPLAY_COORD_PRECISION)
    if isinstance(obj, (list, tuple)):
        return [_round_coords(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _round_coords(v) for k, v in obj.items()}
    return obj

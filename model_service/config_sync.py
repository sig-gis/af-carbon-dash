"""Add-only config synchronization for store-backed JSON config.

The shipped ``conf/base/*.json`` files are defaults. Once the store has been
seeded, new fields added to the shipped files would otherwise never reach the
store. ``sync_config_defaults`` backfills any *missing* keys without ever
overwriting values an operator has customized.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

from model_service.store import ModelStore

logger = logging.getLogger(__name__)

# (store key, shipped filename in conf/base/)
_BOOTSTRAP_CONFIG_KEYS: tuple[tuple[str, str], ...] = (
    ("config/FVSVariant_presets.json", "FVSVariant_presets.json"),
    ("config/variant_species.json", "variant_species.json"),
)


def deep_merge_defaults(shipped: dict, stored: dict) -> tuple[dict, bool]:
    """Return ``(merged, changed)``.

    ``merged`` is ``stored`` with any keys missing from it filled in from
    ``shipped``. Recurses into nested dicts. Never overwrites a key that is
    already present in ``stored``; never merges into non-dict values. Inputs
    are not mutated.
    """
    result = copy.deepcopy(stored)
    changed = False
    for key, ship_val in shipped.items():
        if key not in result:
            result[key] = copy.deepcopy(ship_val)
            changed = True
        elif isinstance(ship_val, dict) and isinstance(result[key], dict):
            merged_sub, sub_changed = deep_merge_defaults(ship_val, result[key])
            result[key] = merged_sub
            changed = changed or sub_changed
    return result, changed


def sync_config_defaults(store: ModelStore, base_path: Path) -> None:
    """Seed or backfill store-backed config from shipped defaults.

    For each bootstrap key: if the store lacks it, write the shipped file
    verbatim; if the store has it, backfill missing keys via
    ``deep_merge_defaults`` and write back only if something changed.
    """
    for key, shipped_name in _BOOTSTRAP_CONFIG_KEYS:
        try:
            shipped_path = base_path / shipped_name
            if not shipped_path.exists():
                logger.warning("Cannot sync %s: shipped file %s missing", key, shipped_path)
                continue
            with open(shipped_path, encoding="utf-8") as f:
                shipped = json.load(f)

            if not store.exists(key):
                store.put_json(shipped, key)
                logger.info("Seeded %s from shipped defaults", key)
                continue

            stored = store.get_json(key)
            merged, changed = deep_merge_defaults(shipped, stored)
            if changed:
                store.put_json(merged, key)
                logger.info("Backfilled missing keys in %s from shipped defaults", key)
        except Exception:
            logger.exception("Failed to sync %s", key)

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolved once at import time — works both locally and inside Docker (/app).
APP_ROOT = Path(__file__).resolve().parent.parent.parent

_JSON_CACHE_TTL_SECONDS = 30.0


def _models_dir() -> Path:
    """Resolve the models directory, honoring MODEL_STORE_PATH override."""
    override = os.environ.get("MODEL_STORE_PATH")
    if override:
        return Path(override)
    return APP_ROOT / "data" / "models"


def _prefix_map() -> dict[str, Path]:
    return {
        "models/": _models_dir(),
        "geo/": APP_ROOT / "data" / "FVSVariantMap20210525",
        "config/": APP_ROOT / "conf" / "base",
    }


_REGISTRY_LOCAL = APP_ROOT / "conf" / "base" / "model_registry.json"


def _resolve(key: str) -> Path:
    """Map a store key to a local filesystem path."""
    if key == "registry.json":
        return _REGISTRY_LOCAL
    for prefix, base_dir in _prefix_map().items():
        if key.startswith(prefix):
            return base_dir / key[len(prefix):]
    return APP_ROOT / key


class LocalStore:
    """Store backed by the local project filesystem (dev default)."""

    def __init__(self) -> None:
        self._json_cache: dict[str, tuple[float, dict]] = {}
        self._json_cache_lock = threading.Lock()

    def get_file(self, key: str) -> Path:
        path = _resolve(key)
        if not path.exists():
            raise FileNotFoundError(f"LocalStore: {key} -> {path} not found")
        return path

    def put_file(self, local_path: Path, key: str) -> None:
        dest = _resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)
        logger.info("LocalStore: wrote %s -> %s", key, dest)

    def get_json(self, key: str) -> dict:
        now = time.monotonic()
        with self._json_cache_lock:
            entry = self._json_cache.get(key)
            if entry is not None and now - entry[0] < _JSON_CACHE_TTL_SECONDS:
                return copy.deepcopy(entry[1])

        path = _resolve(key)
        if not path.exists():
            if key == "registry.json":
                return {"models": []}
            raise FileNotFoundError(f"LocalStore: {key} -> {path} not found")
        with open(path) as f:
            parsed = json.load(f)

        with self._json_cache_lock:
            self._json_cache[key] = (now, parsed)
        return copy.deepcopy(parsed)

    def put_json(self, data: dict, key: str) -> None:
        path = _resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
        logger.info("LocalStore: wrote JSON %s -> %s", key, path)
        with self._json_cache_lock:
            self._json_cache.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        base = None
        for pfx, base_dir in _prefix_map().items():
            if prefix.startswith(pfx) or pfx.startswith(prefix):
                base = base_dir
                break
        if base is None or not base.exists():
            return []
        rel_prefix = prefix.split("/", 1)[-1] if "/" in prefix else ""
        return [
            f"{prefix.split('/')[0]}/{p.name}"
            for p in base.iterdir()
            if p.is_file() and p.name.startswith(rel_prefix)
        ]

    def exists(self, key: str) -> bool:
        return _resolve(key).exists()

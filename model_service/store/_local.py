from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolved once at import time — works both locally and inside Docker (/app).
APP_ROOT = Path(__file__).resolve().parent.parent.parent

# Mapping from store key prefixes to local directories.
_PREFIX_MAP: dict[str, Path] = {
    "models/": APP_ROOT / "data" / "models",
    "geo/": APP_ROOT / "data" / "FVSVariantMap20210525",
    "config/": APP_ROOT / "conf" / "base",
}

_REGISTRY_LOCAL = APP_ROOT / "conf" / "base" / "model_registry.json"


def _resolve(key: str) -> Path:
    """Map a store key to a local filesystem path."""
    if key == "registry.json":
        return _REGISTRY_LOCAL
    for prefix, base_dir in _PREFIX_MAP.items():
        if key.startswith(prefix):
            return base_dir / key[len(prefix):]
    return APP_ROOT / key


class LocalStore:
    """Store backed by the local project filesystem (dev default)."""

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
        path = _resolve(key)
        if not path.exists():
            if key == "registry.json":
                return {"models": []}
            raise FileNotFoundError(f"LocalStore: {key} -> {path} not found")
        with open(path) as f:
            return json.load(f)

    def put_json(self, data: dict, key: str) -> None:
        path = _resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
        logger.info("LocalStore: wrote JSON %s -> %s", key, path)

    def list_keys(self, prefix: str) -> list[str]:
        base = None
        for pfx, base_dir in _PREFIX_MAP.items():
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

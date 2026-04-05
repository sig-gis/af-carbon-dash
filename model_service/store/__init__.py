"""Cloud-agnostic model store abstraction.

Usage::

    from model_service.store import get_store

    store = get_store()           # reads MODEL_STORE_BACKEND env var
    path = store.get_file("models/my_model.pkl")
    registry = store.get_json("registry.json")
"""

from __future__ import annotations

import os
from functools import lru_cache

from ._protocol import ModelStore

__all__ = ["ModelStore", "get_store"]


@lru_cache(maxsize=1)
def get_store() -> ModelStore:
    """Return the configured store singleton.

    The ``MODEL_STORE_BACKEND`` environment variable selects the backend:

    * ``"local"`` (default) — reads/writes to the local project filesystem.
    * ``"s3"`` — S3-compatible object store (AWS, GCS HMAC, R2, MinIO, …).
      Requires ``MODEL_STORE_ENDPOINT``, ``MODEL_STORE_BUCKET``,
      ``MODEL_STORE_ACCESS_KEY``, and ``MODEL_STORE_SECRET_KEY``.
    """
    backend = os.environ.get("MODEL_STORE_BACKEND", "local")

    if backend == "gcs":
        from ._gcs import GCSStore

        return GCSStore.from_env()

    if backend == "s3":
        from ._s3 import S3Store

        return S3Store.from_env()

    from ._local import LocalStore

    return LocalStore()

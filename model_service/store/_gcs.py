from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from google.cloud import storage
from google.api_core.exceptions import NotFound

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/tmp/model_store")


class GCSStore:
    """Store backed by Google Cloud Storage using native ADC authentication.

    On Cloud Run the attached service account authenticates automatically —
    no keys or secrets required.
    """

    def __init__(self, bucket_name: str, project: str | None = None) -> None:
        self._client = storage.Client(project=project)
        self._bucket = self._client.bucket(bucket_name)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> GCSStore:
        return cls(
            bucket_name=os.environ["MODEL_STORE_BUCKET"],
            project=os.environ.get("GCP_PROJECT"),
        )

    def _cache_path(self, key: str) -> Path:
        safe = key.replace("/", "__")
        return _CACHE_DIR / safe

    def get_file(self, key: str) -> Path:
        local = self._cache_path(key)
        if local.exists():
            return local
        blob = self._bucket.blob(key)
        if not blob.exists():
            raise FileNotFoundError(f"GCSStore: {key} not found")
        logger.info("GCSStore: downloading %s", key)
        blob.download_to_filename(str(local))
        return local

    def put_file(self, local_path: Path, key: str) -> None:
        logger.info("GCSStore: uploading %s", key)
        blob = self._bucket.blob(key)
        blob.upload_from_filename(str(local_path))
        # Update local cache
        cache = self._cache_path(key)
        if cache != local_path:
            shutil.copy2(local_path, cache)

    def get_json(self, key: str) -> dict:
        blob = self._bucket.blob(key)
        try:
            data = blob.download_as_text()
            return json.loads(data)
        except NotFound:
            if key == "registry.json":
                return {"models": []}
            raise FileNotFoundError(f"GCSStore: {key} not found")

    def put_json(self, data: dict, key: str) -> None:
        body = json.dumps(data, indent=2)
        logger.info("GCSStore: writing JSON %s (%d bytes)", key, len(body))
        blob = self._bucket.blob(key)
        blob.upload_from_string(body, content_type="application/json")

    def list_keys(self, prefix: str) -> list[str]:
        return [blob.name for blob in self._client.list_blobs(self._bucket, prefix=prefix)]

    def exists(self, key: str) -> bool:
        return self._bucket.blob(key).exists()

    def invalidate_cache(self, key: str) -> None:
        cached = self._cache_path(key)
        if cached.exists():
            cached.unlink()

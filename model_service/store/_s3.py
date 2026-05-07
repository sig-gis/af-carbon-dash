from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("/tmp/model_store")


class S3Store:
    """Store backed by an S3-compatible object store (AWS, GCS HMAC, R2, MinIO, …)."""

    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> S3Store:
        """Create an ``S3Store`` from ``MODEL_STORE_*`` environment variables."""
        return cls(
            endpoint=os.environ["MODEL_STORE_ENDPOINT"],
            bucket=os.environ["MODEL_STORE_BUCKET"],
            access_key=os.environ["MODEL_STORE_ACCESS_KEY"],
            secret_key=os.environ["MODEL_STORE_SECRET_KEY"],
            region=os.environ.get("MODEL_STORE_REGION", "us-east-1"),
        )

    def _cache_path(self, key: str) -> Path:
        safe = key.replace("/", "__")
        return _CACHE_DIR / safe

    def get_file(self, key: str) -> Path:
        local = self._cache_path(key)
        if local.exists():
            return local
        logger.info("S3Store: downloading %s", key)
        self._client.download_file(self._bucket, key, str(local))
        return local

    def put_file(self, local_path: Path, key: str) -> None:
        logger.info("S3Store: uploading %s", key)
        self._client.upload_file(str(local_path), self._bucket, key)
        # Update local cache too
        cache = self._cache_path(key)
        if cache != local_path:
            import shutil
            shutil.copy2(local_path, cache)

    def get_json(self, key: str) -> dict:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=key)
            return json.loads(resp["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                if key == "registry.json":
                    return {"models": []}
                raise FileNotFoundError(f"S3Store: {key} not found") from e
            raise

    def put_json(self, data: dict, key: str) -> None:
        body = json.dumps(data, indent=2).encode()
        logger.info("S3Store: writing JSON %s (%d bytes)", key, len(body))
        self._client.put_object(Bucket=self._bucket, Key=key, Body=body)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def invalidate_cache(self, key: str) -> None:
        """Remove a cached file so the next ``get_file`` re-downloads it."""
        cached = self._cache_path(key)
        if cached.exists():
            cached.unlink()

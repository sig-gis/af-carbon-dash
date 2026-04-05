from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelStore(Protocol):
    """Abstract interface for model/config/geo storage backends.

    Implementations exist for local filesystem and S3-compatible object
    stores.  New backends (SharePoint, Azure Blob, …) only need to satisfy
    this protocol and register in ``get_store()``.
    """

    def get_file(self, key: str) -> Path:
        """Return a local ``Path`` for *key*, downloading if necessary."""
        ...

    def put_file(self, local_path: Path, key: str) -> None:
        """Upload *local_path* to the store under *key*."""
        ...

    def get_json(self, key: str) -> dict:
        """Read *key* from the store and return parsed JSON."""
        ...

    def put_json(self, data: dict, key: str) -> None:
        """Serialize *data* as JSON and write it to *key*."""
        ...

    def list_keys(self, prefix: str) -> list[str]:
        """Return all keys whose name starts with *prefix*."""
        ...

    def exists(self, key: str) -> bool:
        """Return ``True`` if *key* exists in the store."""
        ...

"""Machine-to-machine authentication for the model service.

The service has no concept of end users. Every caller is a *client system*
(our dashboard, the American Forests dashboard/BFF, an admin script) that
presents a static bearer key on each request::

    Authorization: Bearer <key>

Key configuration
-----------------
Keys live in the model store as ``api_keys.json``, next to ``registry.json``,
so every deployment of an environment shares the same keys and nothing has to
be created by hand. The file is a JSON object keyed by client name::

    {
      "sig-dashboard": {"keys": ["k1"], "role": "admin"},
      "af-dashboard":  {"keys": ["k2", "k2-rotating-in"], "role": "client"},
      "quick-script":  "k3"
    }

* ``keys`` is a list so a client can be rotated without downtime: add the new
  key, let the client switch over, then remove the old one.
* ``role`` is ``client`` (compute + read endpoints) or ``admin`` (also the
  mutating endpoints such as ``/geo/refresh``). A bare string value is
  shorthand for ``{"keys": [value], "role": "client"}``.

If the file does not exist, whichever process starts first (service or
dashboard) generates it with a single admin key for the dashboard client,
``DASHBOARD_CLIENT``. The service re-reads the file when it sees an unknown
key and at least once a minute, so adding, rotating or revoking a client is an
edit to the file with no redeploy.

``CARBON_API_KEYS`` (the same JSON, as an environment variable) overrides the
store entirely, for anyone who prefers Secret Manager or a ``.env`` file.

``CARBON_API_AUTH=off`` disables authentication. It is refused when
``ENV=production``.

Only ``/health`` is exempt from authentication. FastAPI's ``/docs`` and
``/openapi.json`` routes bypass app-level dependencies by construction.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

ENV_VAR = "CARBON_API_KEYS"
DISABLE_VAR = "CARBON_API_AUTH"
STORE_KEY = "api_keys.json"
DASHBOARD_CLIENT = "sig-dashboard"
ROLES = ("client", "admin")
PUBLIC_PATHS = frozenset({"/health"})

# Minimum seconds between store re-reads triggered by an unknown key, so a
# flood of bad keys can't turn into a flood of store reads.
_REFRESH_INTERVAL = 10.0
# Maximum age of the cached key set. After this the next lookup re-reads the
# store even for a known key, so removing or rotating a key takes effect
# without anyone presenting an unknown one.
_MAX_AGE = 60.0

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Client:
    """The authenticated client system for a request."""

    name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class _KeyEntry:
    key: str
    client: Client


class AuthConfigError(RuntimeError):
    """Raised when the key configuration is malformed or unusable."""


# --- parsing ----------------------------------------------------------------


def parse_key_config(doc: dict | str | None) -> list[_KeyEntry]:
    """Parse the key document (dict, or its JSON text) into a flat list of entries."""
    if doc is None:
        return []
    if isinstance(doc, str):
        if not doc.strip():
            return []
        try:
            doc = json.loads(doc)
        except json.JSONDecodeError as e:
            raise AuthConfigError(f"API key config is not valid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise AuthConfigError("API key config must be a JSON object keyed by client name")

    entries: list[_KeyEntry] = []
    for name, spec in doc.items():
        if isinstance(spec, str):
            spec = {"keys": [spec]}
        if not isinstance(spec, dict):
            raise AuthConfigError(f"API key config: client {name!r} must be a string or object")
        keys = spec.get("keys")
        if isinstance(keys, str):
            keys = [keys]
        if not keys or not all(isinstance(k, str) and k for k in keys):
            raise AuthConfigError(f"API key config: client {name!r} needs a non-empty 'keys' list")
        role = spec.get("role", "client")
        if role not in ROLES:
            raise AuthConfigError(
                f"API key config: client {name!r} has unknown role {role!r} (expected one of {ROLES})"
            )
        client = Client(name=str(name), role=role)
        entries.extend(_KeyEntry(key=k, client=client) for k in keys)

    seen: set[str] = set()
    for e in entries:
        if e.key in seen:
            raise AuthConfigError("API key config: the same key is assigned to more than one client")
        seen.add(e.key)
    return entries


# --- key sources --------------------------------------------------------------


def generate_key() -> str:
    return secrets.token_urlsafe(32)


def ensure_store_keys(store) -> dict:
    """Return the key document from ``store``, creating it if absent.

    Shared by the service and the dashboard so whichever starts first
    provisions the file, and both then agree on the dashboard's key. After a
    write the document is read back, so if two processes race the store's
    copy wins for both.
    """
    try:
        return store.get_json(STORE_KEY)
    except FileNotFoundError:
        pass
    doc = {DASHBOARD_CLIENT: {"keys": [generate_key()], "role": "admin"}}
    logger.warning(
        "%s not found in the model store; generating a fresh key for client %r",
        STORE_KEY,
        DASHBOARD_CLIENT,
    )
    store.put_json(doc, STORE_KEY)
    try:
        return store.get_json(STORE_KEY)
    except FileNotFoundError:  # pragma: no cover - store just wrote it
        return doc


def auth_disabled() -> bool:
    flag = os.getenv(DISABLE_VAR, "").strip().lower()
    return flag in {"off", "0", "false", "no"}


def _load_entries() -> list[_KeyEntry]:
    """Load key entries from the env override, else the model store."""
    raw = os.getenv(ENV_VAR)
    if raw and raw.strip():
        return parse_key_config(raw)
    from model_service.store import get_store

    return parse_key_config(ensure_store_keys(get_store()))


class _KeyRing:
    """Cached key entries with throttled refresh from the source."""

    def __init__(self) -> None:
        self._entries: tuple[_KeyEntry, ...] | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._entries = None
            self._loaded_at = 0.0

    def entries(self) -> tuple[_KeyEntry, ...]:
        with self._lock:
            if self._entries is None:
                self._entries = tuple(_load_entries())
                self._loaded_at = time.monotonic()
            return self._entries

    def refresh(self) -> tuple[_KeyEntry, ...]:
        """Re-read from the source unless it was read very recently."""
        with self._lock:
            if time.monotonic() - self._loaded_at < _REFRESH_INTERVAL:
                return self._entries or ()
            try:
                self._entries = tuple(_load_entries())
            except Exception:  # keep serving the last good key set
                logger.exception("Failed to refresh API keys; keeping the previous set")
            self._loaded_at = time.monotonic()
            return self._entries or ()

    def lookup(self, presented: str | None) -> Client | None:
        if not presented:
            return None
        entries = self.entries()
        if time.monotonic() - self._loaded_at > _MAX_AGE:
            entries = self.refresh()
        found = self._match(entries, presented)
        if found is None:
            # Unknown key: maybe a client was just added to the store.
            found = self._match(self.refresh(), presented)
        return found

    @staticmethod
    def _match(entries, presented: str) -> Client | None:
        match: Client | None = None
        # Compare against every key so timing doesn't reveal which prefix matched.
        for entry in entries:
            if hmac.compare_digest(entry.key.encode(), presented.encode()):
                match = entry.client
        return match


_ring = _KeyRing()


def reset_cache() -> None:
    """Forget the loaded keys (for tests and hot reloads)."""
    _ring.reset()


def lookup_client(presented: str | None) -> Client | None:
    """Return the client owning ``presented``, or None."""
    return _ring.lookup(presented)


def validate_startup() -> None:
    """Load keys (provisioning them if needed) and refuse unsafe configs. Call from app startup."""
    env = os.getenv("ENV", "local")
    if auth_disabled():
        if env == "production":
            raise AuthConfigError(f"{DISABLE_VAR}=off is not allowed when ENV=production")
        logger.warning("API authentication is DISABLED (%s=off, ENV=%s)", DISABLE_VAR, env)
        return
    entries = _ring.entries()  # raises AuthConfigError on malformed config
    if not entries:
        raise AuthConfigError("API key config contains no clients")
    names = sorted({e.client.name for e in entries})
    logger.info("API auth enabled for %d client(s): %s", len(names), ", ".join(names))


# --- FastAPI dependencies --------------------------------------------------------


def require_client(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Client:
    """App-level dependency: authenticate the calling system.

    Returns the ``Client`` and records it on ``request.state.client`` so the
    access log can attribute the request.
    """
    if request.url.path in PUBLIC_PATHS:
        client = Client(name="public", role="client")
    elif auth_disabled():
        client = Client(name="anonymous", role="admin")
    else:
        client = lookup_client(credentials.credentials if credentials else None)
        if client is None:
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
    request.state.client = client
    return client


def require_admin(client: Client = Depends(require_client)) -> Client:
    """Route dependency for mutating/admin endpoints."""
    if not client.is_admin:
        raise HTTPException(
            status_code=403,
            detail=f"Client {client.name!r} is not permitted to perform admin operations",
        )
    return client

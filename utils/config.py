import os
from functools import lru_cache
from urllib.parse import urlparse

import numpy as np
import requests


def _secret_or_env(name: str) -> str | None:
    """Read a setting from Streamlit secrets first, then the environment."""
    try:
        import streamlit as st

        value = st.secrets.get(name)
        if value:
            return str(value)
    except (ImportError, FileNotFoundError, KeyError):
        pass
    return os.getenv(name) or None


def get_api_client_name() -> str:
    """Which client in api_keys.json this dashboard authenticates as."""
    from model_service.auth import DASHBOARD_CLIENT

    return _secret_or_env("CARBON_API_CLIENT_NAME") or DASHBOARD_CLIENT


def get_api_key() -> str | None:
    """The bearer key this dashboard presents to the model service.

    Precedence:

    1. ``CARBON_API_KEY`` (Streamlit secret or env var), for anyone who manages
       keys outside the model store.
    2. The dashboard client's first key in the store's ``api_keys.json``. The
       file is created if it doesn't exist, so a fresh checkout or a fresh
       environment needs no setup; the service reads the same file.

    Returns None only if neither source yields a key (e.g. the store is
    unreachable), in which case requests go out unauthenticated.
    """
    key = _secret_or_env("CARBON_API_KEY")
    if key:
        return key
    try:
        from model_service.auth import ensure_store_keys, parse_key_config
        from model_service.store import get_store

        name = get_api_client_name()
        for entry in parse_key_config(ensure_store_keys(get_store())):
            if entry.client.name == name:
                return entry.key
        print(f"api key: client {name!r} not present in the model store's api_keys.json")
    except Exception as e:  # noqa: BLE001 - never take the dashboard down over auth setup
        print(f"api key: could not load from model store: {e}")
    return None


class _ApiSession(requests.Session):
    """Session that re-resolves the key and retries once after a 401.

    Covers the dashboard having cached a key that was since rotated in the
    store, and the rare startup race where two processes provisioned the
    file at once and the store's copy won.
    """

    def request(self, method, url, **kwargs):  # type: ignore[override]
        resp = super().request(method, url, **kwargs)
        if resp.status_code != 401:
            return resp
        key = get_api_key()
        if not key or self.headers.get("Authorization") == f"Bearer {key}":
            return resp
        print("api key: refreshed after 401, retrying once")
        self.headers["Authorization"] = f"Bearer {key}"
        return super().request(method, url, **kwargs)


@lru_cache(maxsize=1)
def api_session() -> requests.Session:
    """Shared HTTP session for calls to the model service.

    Carries the ``Authorization: Bearer`` header when a key is available, so
    call sites only need the URL. Every dashboard request to the API should go
    through this rather than the bare ``requests`` module.
    """
    session = _ApiSession()
    key = get_api_key()
    if key:
        session.headers["Authorization"] = f"Bearer {key}"
    return session


def get_api_base_url() -> str:
    """
    Resolve CARBON_API_BASE_URL with sensible local defaults.
    Priority: Streamlit secrets → env var → local default
    """
    api_url = None
    
    # Try Streamlit secrets first
    try:
        import streamlit as st
        api_url = st.secrets.get("CARBON_API_BASE_URL")
    except (ImportError, FileNotFoundError, KeyError):
        pass
    
    # Fall back to environment variable
    if not api_url:
        api_url = os.getenv("CARBON_API_BASE_URL")
    
    # Default to localhost for development
    if not api_url:
        api_url = "http://127.0.0.1:8001"

    env = os.getenv("ENV", "local")

    # Enforce rules only in production
    if env == "production":
        parsed = urlparse(api_url)
        if parsed.hostname in {"localhost", "127.0.0.1"}:
            raise RuntimeError(
                "In production, CARBON_API_BASE_URL must not point to localhost."
            )
    print(f'api_url: {api_url}')
    return api_url

def normalize_params(params: dict) -> dict:
    """
    Convert params dict into JSON-safe Python primitives.
    - Converts numpy scalars → Python floats
    - Replaces NaN / inf → None
    """
    clean = {}

    for k, v in params.items():
        if isinstance(v, (int, float, np.generic)):
            v = float(v)
            if not np.isfinite(v):
                clean[k] = None
            else:
                clean[k] = v
        else:
            clean[k] = v

    return clean
import os
import numpy as np
from urllib.parse import urlparse

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
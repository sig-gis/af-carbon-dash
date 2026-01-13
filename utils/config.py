import os
import numpy as np
from urllib.parse import urlparse

def get_api_base_url() -> str:
    """
    Resolve CARBON_API_BASE_URL with sensible local defaults.
    """
    # Priority: env var → Streamlit secrets → local default
    api_url = (
        os.getenv("CARBON_API_BASE_URL")
    )

    # If nothing set, assume local FastAPI for dev
    if not api_url:
        api_url = "http://127.0.0.1:8000"

    env = os.getenv("ENV", "local")

    # Enforce rules only in production
    if env == "production":
        parsed = urlparse(api_url)
        if parsed.hostname in {"localhost", "127.0.0.1"}:
            raise RuntimeError(
                "In production, CARBON_API_BASE_URL must not point to localhost."
            )

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
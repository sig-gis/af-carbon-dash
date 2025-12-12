import os
import streamlit as st
from urllib.parse import urlparse

def get_api_base_url() -> str:
    """
    Resolve CARBON_API_BASE_URL with sensible local defaults.
    """
    # Priority: env var → Streamlit secrets → local default
    api_url = (
        os.getenv("CARBON_API_BASE_URL")
        or st.secrets.get("CARBON_API_BASE_URL", None)
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
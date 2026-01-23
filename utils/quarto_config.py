import os
import numpy as np
from urllib.parse import urlparse

def get_api_quarto_url() -> str:
    """
    Resolve QUARTO_API_BASE_URL with sensible local defaults.
    Priority: Streamlit secrets → env var → local default
    """
    api_url = None
    
    # Try Streamlit secrets first
    try:
        import streamlit as st
        api_url = st.secrets.get("QUARTO_API_BASE_URL")
    except (ImportError, FileNotFoundError, KeyError):
        pass
    
    # Fall back to environment variable
    if not api_url:
        api_url = os.getenv("QUARTO_API_BASE_URL")
    
    # Default to localhost for development
    if not api_url:
        api_url = "http://127.0.0.1:8000"

    env = os.getenv("ENV", "local")

    # Enforce rules only in production
    if env == "production":
        parsed = urlparse(api_url)
        if parsed.hostname in {"localhost", "127.0.0.1"}:
            raise RuntimeError(
                "In production, QUARTO_API_BASE_URL must not point to localhost."
            )
    print(f'api_url: {api_url}')
    return api_url
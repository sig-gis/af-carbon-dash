import streamlit as st
import json
import numpy as np

@st.cache_data
def load_help(path: str = "conf/base/help_text.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
    
# access HELP text
HELP = load_help()
def H(key: str) -> str:
    """
    Accessor for help text loaded from conf/base/help_text.json.
    Returns empty string if key is missing to avoid runtime errors.
    """
    entry = HELP.get(key)
    if isinstance(entry, dict) and "help" in entry:
        return entry["help"]
    return ""
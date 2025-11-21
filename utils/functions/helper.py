import streamlit as st
import json
from pathlib import Path

@st.cache_data
def load_help(path: str = "conf/base/help_text.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
    
# access HELP text
HELP = load_help()
def H(key: str) -> str:
    """
    Safe accessor for help text loaded from conf/base/helptext.json.
    Returns empty string if key is missing to avoid runtime errors.
    """
    entry = HELP.get(key)
    if isinstance(entry, dict) and "help" in entry:
        return entry["help"]
    return ""

def _species_keys(preset: dict):
    # any key that starts with tpa_ is treated as a species slider
    return [k for k in preset.keys() if k.startswith("tpa_")]

LABELS_PATH = Path("conf/base/species_labels.json")

with LABELS_PATH.open("r") as f:
    SPECIES_LABELS = json.load(f)

def _label_for(key: str) -> str:
    return SPECIES_LABELS.get(key, key.replace("tpa_", "TPA_").upper())
import streamlit as st
from pathlib import Path
import json

from model_service.main import load_species_labels

def _planting_keys():
    """
    Return list of planting session state keys.
    """
    return [k for k in list(st.session_state.keys()) if k.startswith("tpa_") or k in ("survival", "si", "net_acres")]

def _carbon_units_keys() -> list[str]:
    """
    Return the set of session-state keys that should persist for the Carbon Units section.
    """
    return ["carbon_units_protocols", "carbon_units_inputs"]

def _init_planting_state(variant: str, preset: dict):
    """
    Seed/clear planting slider state ONLY when the selected variant changes.
    Otherwise, leave the user's inputs intact across page switches.
    """
    last_variant = st.session_state.get("_last_variant")
    if last_variant == variant:
        return 

    for k in _planting_keys():
        st.session_state.pop(k, None)

    # Base defaults if missing
    st.session_state["survival"] = preset.get("survival", st.session_state.get("survival", 70))
    st.session_state["si"]       = preset.get("si",       st.session_state.get("si", 120))
    # net_acres input in planting params for organization (top of page), but not in FVSVariant_presets.json
    st.session_state["net_acres"] = st.session_state.get("net_acres", 10000)

    # Species defaults if missing
    for spk in _species_keys(preset):
        st.session_state.setdefault(spk, int(preset.get(spk, 0)))

    st.session_state["_last_variant"] = variant

def _init_carbon_units_state():
    """
    Initialize Carbon Units inputs ONLY if missing.
    Does not overwrite existing user selections.
    """
    # default protocols
    default_protocols = ["ACR/CAR/VERRA"]

    # initialize the mapping dict
    if "carbon_units_inputs" not in st.session_state:
        st.session_state["carbon_units_inputs"] = {"protocols": default_protocols}

    # ensure the widget-backed list key exists
    if "carbon_units_protocols" not in st.session_state:
        st.session_state["carbon_units_protocols"] = st.session_state["carbon_units_inputs"].get("protocols", default_protocols)

def _backup_keys(keys, backup_name: str = "_planting_backup"):
    """
    Persist the current values for the given session-state keys to a small
    backup dict stored under `backup_name` in session_state.
    Helpful when Streamlit drops a widget's state when navigating back and forth between content. 

    Parameters
    ----------
    keys : Iterable[str]
        The session-state keys you want to persist (e.g., ["survival", "si", *species_keys]).
    backup_name : str, optional
        The session-state key under which the backup is stored. Default: "_planting_backup".

    Notes
    -----
    - Call this *after* rendering widgets so the latest user inputs are captured.
    - Only keys present in `st.session_state` are saved; missing keys are ignored.
    """
    backup = {}
    for k in keys:
        if k in st.session_state:
            # Cast to int for sliders
            val = st.session_state[k]
            backup[k] = int(val) if isinstance(val, (int, float, str)) and str(val).isdigit() else val
    st.session_state[backup_name] = backup
    return backup

def _restore_backup(keys, backup_name: str = "_planting_backup"):
    """
    Restore any *missing* session-state keys from a previously saved backup.

    Parameters
    ----------
    keys : Iterable[str]
        The session-state keys you want to ensure are present (e.g., ["survival", "si", *species_keys]).
    backup_name : str, optional
        The session-state key where the backup dict is stored. Default: "_planting_backup".

    Behavior
    --------
    - If a key is already present in `st.session_state`, it is left untouched.
    - If a key is missing and present in the backup, it is restored from backup.
    - If no backup exists, this is a no-op.
    """
    backup = st.session_state.get(backup_name, {})
    if not backup:
        return

    for k in keys:
        if k not in st.session_state and k in backup:
            st.session_state[k] = backup[k]

def _species_keys(preset: dict):
    """
    Accessor for species keys loaded from conf/base/FVSVariant_presets.json.
    """
    # any key that starts with tpa_ is treated as a species slider
    return [k for k in preset.keys() if k.startswith("tpa_")]

def _label_for(key: str) -> str:
    """
    Accessor for species labels loaded from conf/base/species_labels.json.
    """
    SPECIES_LABELS = load_species_labels()

    return SPECIES_LABELS.get(key, key.replace("tpa_", "TPA_").upper())
import streamlit as st
from pathlib import Path
import json

from model_service.main import load_species_labels, load_variant_species


def _species_codes(variant: str) -> list[str]:
    """
    Return the ordered list of species codes for a variant from variant_species.json.
    Falls back to empty list if variant not found.
    """
    vs = load_variant_species()
    return vs.get(variant, [])


def _max_species() -> int:
    """Return the configured maximum number of species slots."""
    vs = load_variant_species()
    return vs.get("_max_species", 4)


def _species_keys(variant: str) -> list[str]:
    """
    Return positional species session-state keys for a variant.
    e.g. ["sp1_tpa", "sp2_tpa", "sp3_tpa"] for a 3-species variant.
    """
    codes = _species_codes(variant)
    return [f"sp{i+1}_tpa" for i in range(len(codes))]


def _species_label(variant: str, index: int) -> str:
    """
    Return a human-readable label for a species slot.
    e.g. "SP1: Douglas-fir (DF)" for PN index 0.
    """
    labels = load_species_labels()
    codes = _species_codes(variant)
    if index < len(codes):
        code = codes[index]
        name = labels.get(code, code)
        return f"{name} ({code})"
    return f"SP{index+1}"


def _planting_keys():
    """Return list of planting session state keys."""
    sp_keys = [k for k in st.session_state.keys() if k.startswith("sp") and k.endswith("_tpa")]
    return sp_keys + [k for k in ["survival", "si", "net_acres"] if k in st.session_state]


def _carbon_units_keys() -> list[str]:
    """Return the set of session-state keys that should persist for the Carbon Units section."""
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

    # Base defaults
    st.session_state["survival"] = preset.get("survival", st.session_state.get("survival", 70))
    st.session_state["si"] = preset.get("si", st.session_state.get("si", 120))
    st.session_state["net_acres"] = st.session_state.get("net_acres", 10000)

    # Species defaults from positional default_tpa list
    default_tpa = preset.get("default_tpa", [])
    for i, key in enumerate(_species_keys(variant)):
        st.session_state.setdefault(key, int(default_tpa[i]) if i < len(default_tpa) else 0)

    st.session_state["_last_variant"] = variant


def _init_carbon_units_state():
    """Initialize Carbon Units inputs ONLY if missing."""
    default_protocols = ["ACR", "CAR", "VERRA"]

    if "carbon_units_inputs" not in st.session_state:
        st.session_state["carbon_units_inputs"] = {"protocols": default_protocols}

    if "carbon_units_protocols" not in st.session_state:
        st.session_state["carbon_units_protocols"] = st.session_state["carbon_units_inputs"].get("protocols", default_protocols)


def _backup_keys(keys, backup_name: str = "_planting_backup"):
    """
    Persist the current values for the given session-state keys to a backup dict.
    Call after rendering widgets so the latest user inputs are captured.
    """
    backup = {}
    for k in keys:
        if k in st.session_state:
            val = st.session_state[k]
            backup[k] = int(val) if isinstance(val, (int, float, str)) and str(val).isdigit() else val
    st.session_state[backup_name] = backup
    return backup


def _restore_backup(keys, backup_name: str = "_planting_backup"):
    """
    Restore any *missing* session-state keys from a previously saved backup.
    If a key is already present, it is left untouched.
    """
    backup = st.session_state.get(backup_name, {})
    if not backup:
        return

    for k in keys:
        if k not in st.session_state and k in backup:
            st.session_state[k] = backup[k]

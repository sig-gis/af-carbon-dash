from fastapi import FastAPI
from fastapi import Depends
from pathlib import Path
import json
import pandas as pd
import requests
import numpy as np

from model_service.model import compute_proforma, compute_summaries, compute_carbon_scores, compute_carbon_units
from model_service.schemas import ProformaRequest, ProformaResponse, CarbonInputs, CarbonResponse, CarbonUnitsRequest, CarbonUnitsResponse

from utils.config import get_api_base_url

app = FastAPI(title="Carbon Model Service")

API_BASE_URL = get_api_base_url()

BASE_PATH = Path("conf/base")

def load_json(filename: str):
    with open(BASE_PATH / filename, "r") as f:
        return json.load(f)
    
def fetch_carbon_coefficients():
    resp = requests.get(f"{API_BASE_URL}/carbon/coefficients", timeout=5)
    resp.raise_for_status()
    return resp.json()

def _load_proforma_defaults() -> dict:
    resp = requests.get(f"{API_BASE_URL}/proforma/presets", timeout=5)
    resp.raise_for_status()
    return resp.json()

def load_variant_presets() -> dict:
    resp = requests.get(f"{API_BASE_URL}/variant/presets", timeout=5)
    resp.raise_for_status()
    return resp.json()

def load_species_labels() -> dict:
    resp = requests.get(f"{API_BASE_URL}/species/labels", timeout=5)
    resp.raise_for_status()
    return resp.json()

def load_protocol_rules() -> dict:
    resp = requests.get(f"{API_BASE_URL}/protocol/rules", timeout=5)
    resp.raise_for_status()
    return resp.json()

@app.get("/carbon/coefficients")
def get_carbon_coefficients():
    return load_json("carbon_model_coefficients.json")

@app.get("/proforma/presets")
def get_proforma_presets():
    return load_json("proforma_presets.json")

@app.get("/variant/presets")
def get_variant_presets():
    return load_json("FVSVariant_presets.json")

@app.get("/species/labels")
def get_species_labels():
    return load_json("species_labels.json")

@app.get("/protocol/rules")
def get_protocol_rules():
    return load_json("protocol_rules.json")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/proforma/compute", response_model=ProformaResponse)
def run_proforma(req: ProformaRequest):
    df_ert_ac = pd.DataFrame(req.df_ert_ac)
    df_pf = compute_proforma(df_ert_ac, req.params)
    summaries_df = compute_summaries(df_pf, req.params)

    return {
        "proforma_rows": df_pf.to_dict(orient="records"),
        "summaries": summaries_df.to_dict(orient="records"),
    }

@app.post("/carbon/calculate", response_model=CarbonResponse)
def calculate_carbon(inputs: CarbonInputs):
    coefficients = fetch_carbon_coefficients()

    results = compute_carbon_scores(
        coefficients=coefficients,
        tpa_df=inputs.tpa_df,
        tpa_rc=inputs.tpa_rc,
        tpa_wh=inputs.tpa_wh,
        survival=inputs.survival,
        si=inputs.si,
    )

    # Add Year 0
    results.insert(0, {
        "Year": 2024,
        "C_Score": 0.0,
        "Annual_C_Score": 0.0
    })

    return {"carbon_df": results}

@app.post("/carbon/units", response_model=CarbonUnitsResponse)
def carbon_units_endpoint(req: CarbonUnitsRequest,
                          protocol_rules: dict = Depends(get_protocol_rules),):
    df_carbon = pd.DataFrame(req.carbon_rows)

    ruleset = req.protocol_rules or protocol_rules

    df_units = compute_carbon_units(
        df_carbon,
        req.protocols,
        ruleset,
    )

    return {
        "rows": df_units.to_dict(orient="records")
    }
from fastapi import FastAPI, HTTPException
from fastapi import Depends
from fastapi.responses import FileResponse
from pathlib import Path
import json
import pandas as pd
import requests
import numpy as np
import subprocess
import datetime
import os
import tempfile
import shutil

from model_service.model import compute_proforma, compute_summaries, compute_carbon_scores, compute_carbon_units
from model_service.schemas import ProformaRequest, ProformaResponse, CarbonInputs, CarbonResponse, CarbonUnitsRequest, CarbonUnitsResponse, ReportRequest

from utils.config import get_api_base_url

app = FastAPI(title="Carbon Model Service")

API_BASE_URL = get_api_base_url()

# BASE_PATH = Path("conf/base")
# QUARTO_DIR = Path("model_service/quarto")

APP_ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = APP_ROOT / "conf" / "base"
QUARTO_DIR = APP_ROOT / "model_service" / "quarto"

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
    coefficients = get_carbon_coefficients()

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

#QUARTO REPORTING
@app.post("/reports/generate")
def generate_report(req: ReportRequest = None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

    TMP_DIR = Path("/tmp/quarto")
    DATA_DIR = TMP_DIR / "data"
    REPORTS_DIR = TMP_DIR / "reports"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    output_file = REPORTS_DIR / f"report_{timestamp}.pdf"

    temp_dir = None

    try:
        if req:
            # pd.DataFrame(req.data.planting_design).to_csv(DATA_DIR / "planting_design.csv", index=False, header=None)
            # pd.DataFrame(req.data.species_mix).to_csv(DATA_DIR / "species_mix.csv", index=False, header=None)
            # pd.DataFrame(req.data.financial_options1).to_csv(DATA_DIR / "financial_options1.csv", index=False, header=None)
            # pd.DataFrame(req.data.financial_options2).to_csv(DATA_DIR / "financial_options2.csv", index=False, header=None)
            # pd.DataFrame(req.data.carbon).to_csv(DATA_DIR / "carbon.csv", index=False)
            # pd.DataFrame([{"variant": req.data.selected_variant}]).to_csv(DATA_DIR / "variant.csv", index=False)

                df = pd.DataFrame(req.data.planting_design)
                df.to_csv(DATA_DIR / "planting_design.csv", index=False, header=None)
                del df

                df = pd.DataFrame(req.data.species_mix)
                df.to_csv(DATA_DIR / "species_mix.csv", index=False, header=None)
                del df

                df = pd.DataFrame(req.data.financial_options1)
                df.to_csv(DATA_DIR / "financial_options1.csv", index=False, header=None)
                del df

                df = pd.DataFrame(req.data.financial_options2)
                df.to_csv(DATA_DIR / "financial_options2.csv", index=False, header=None)
                del df

                df = pd.DataFrame(req.data.carbon)
                df.to_csv(DATA_DIR / "carbon.csv", index=False)
                del df

                df = pd.DataFrame([{"variant": req.data.selected_variant}])
                df.to_csv(DATA_DIR / "variant.csv", index=False)
                del df

        env = os.environ.copy()
        env["QUARTO_DATA_DIR"] = str(DATA_DIR)

        result = subprocess.run(
            [
                "quarto", "render", str(QUARTO_DIR / "report.ipynb"),
                "--to", "typst-pdf",
                "--output-dir", str(REPORTS_DIR),
                "--output", f"report_{timestamp}.pdf",
                "--execute", "--no-cache"
            ],
            cwd=str(QUARTO_DIR),
            env=env,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Quarto failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

        return FileResponse(
            path=output_file,
            media_type="application/pdf",
            filename=output_file.name,
        )

    finally:
        if temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)
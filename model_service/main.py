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

BASE_PATH = Path("conf/base")
QUARTO_DIR = Path("model_service/quarto")

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
    """
    Generate a PDF report using Quarto.
    If req is provided, generates temp CSVs from the data.
    Otherwise, uses existing data in quarto/data/.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

    # Ensure reports folder exists
    reports_dir = QUARTO_DIR / "reports"
    reports_dir.mkdir(exist_ok=True)

    output_file = reports_dir / f"report_{timestamp}.pdf"

    # Change to quarto directory for execution
    original_cwd = os.getcwd()
    temp_dir = None

    try:
        os.chdir(QUARTO_DIR)

        if req:
            # Create temp data directory
            temp_dir = tempfile.mkdtemp()
            temp_data_dir = Path(temp_dir) / "data"
            temp_data_dir.mkdir()

            # Generate CSVs from request data
            pd.DataFrame(req.data.planting_design).to_csv(temp_data_dir / "planting_design.csv", index=False, header=None)
            pd.DataFrame(req.data.species_mix).to_csv(temp_data_dir / "species_mix.csv", index=False, header=None)
            pd.DataFrame(req.data.financial_options1).to_csv(temp_data_dir / "financial_options1.csv", index=False, header=None)
            pd.DataFrame(req.data.financial_options2).to_csv(temp_data_dir / "financial_options2.csv", index=False, header=None)
            pd.DataFrame(req.data.carbon).to_csv(temp_data_dir / "carbon.csv", index=False)
            # Save variant
            pd.DataFrame([{"variant": req.data.selected_variant}]).to_csv(temp_data_dir / "variant.csv", index=False)

            # Copy temp data to quarto data folder (or modify notebook to use temp dir)
            # For simplicity, copy to data/
            data_dir = Path("data")
            data_dir.mkdir(exist_ok=True)
            for file in temp_data_dir.glob("*.csv"):
                shutil.copy(file, data_dir / file.name)

        # Run quarto render
        result = subprocess.run([
            "quarto", "render", "report.ipynb",
            "--to", "typst-pdf",
            "--output-dir", "reports",
            "--output", f"report_{timestamp}.pdf",
            "--execute"
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Quarto render failed: {result.stderr}")

        # Return the PDF file
        return FileResponse(
            path=output_file,
            media_type='application/pdf',
            filename=f"report_{timestamp}.pdf"
        )

    finally:
        os.chdir(original_cwd)
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir)
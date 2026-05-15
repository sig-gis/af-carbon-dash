import datetime
import json
import logging
import os
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from model_service.geo import get_filtered_geojson
from model_service.model import (
    compute_carbon_scores,
    compute_carbon_units,
    compute_proforma,
    compute_summaries,
    default_scenario,
    get_fvs_models,
    predict_fvs_metrics,
    run_scenario,
)
from model_service.schemas import (
    CarbonInputs,
    CarbonResponse,
    CarbonUnitsRequest,
    CarbonUnitsResponse,
    ProformaRequest,
    ProformaResponse,
    ReportRequest,
    ScenarioDefaults,
    ScenarioRequest,
    ScenarioResponse,
)
from model_service.config_sync import sync_config_defaults
from model_service.store import get_store
from utils.config import get_api_base_url

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = APP_ROOT / "conf" / "base"
QUARTO_DIR = APP_ROOT / "model_service" / "quarto"

# Cached filtered GeoJSON (rebuilt on startup)
_filtered_geojson: dict | None = None


def refresh_geojson() -> None:
    """Rebuild the cached filtered GeoJSON from the store."""
    global _filtered_geojson
    store = get_store()
    try:
        _filtered_geojson = get_filtered_geojson(store)
    except FileNotFoundError:
        logger.warning("Full GeoJSON not found in store; filtered GeoJSON unavailable")
        _filtered_geojson = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load registry and GeoJSON cache on startup. Models are fetched lazily on first use."""
    t0 = time.time()
    store = get_store()

    registry = store.get_json("registry.json").get("models", [])
    logger.info("Registry loaded: %d models (%.1fs)", len(registry), time.time() - t0)

    sync_config_defaults(store, BASE_PATH)

    refresh_geojson()

    yield


app = FastAPI(title="Carbon Model Service", lifespan=lifespan)

API_BASE_URL = get_api_base_url()

SUPPORTED_VARIANTS = {"CR", "CR_1", "CR_2", "EC", "EM", "PN", "WS", "WS_1"}


def normalize_variant(value: str) -> str:
    if value is None:
        return ""
    normalized = str(value).strip().upper()
    for variant in SUPPORTED_VARIANTS:
        if variant in normalized:
            return variant
    return normalized


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


def load_variant_species() -> dict:
    resp = requests.get(f"{API_BASE_URL}/variant/species", timeout=5)
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
    return get_store().get_json("config/FVSVariant_presets.json")


@app.get("/species/labels")
def get_species_labels():
    return load_json("species_labels.json")


@app.get("/protocol/rules")
def get_protocol_rules():
    return load_json("protocol_rules.json")


@app.get("/variant/species")
def get_variant_species():
    return get_store().get_json("config/variant_species.json")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/geo/variants")
def geo_variants():
    """Return filtered GeoJSON containing only locations with registered models."""
    if _filtered_geojson is None:
        raise HTTPException(status_code=503, detail="GeoJSON not available")
    return JSONResponse(content=_filtered_geojson)


@app.get("/models/registry")
def get_model_registry():
    """Return the current model registry."""
    store = get_store()
    return store.get_json("registry.json")


@app.get("/models/pct-info")
def get_pct_info(variant: str, loccode: str):
    """Return available PCT levels and retention percentages for a variant/location."""
    store = get_store()
    registry = store.get_json("registry.json").get("models", [])
    matches = [
        m
        for m in registry
        if m.get("variant") == variant and m.get("loccode") == loccode
    ]
    if not matches:
        # Fallback: return all PCT levels with no retention data
        return [
            {"pct_level": p, "pct_retention": None} for p in ["PCT0", "PCT1", "PCT2"]
        ]
    return sorted(
        [
            {
                "pct_level": m.get("pct_level", "PCT0"),
                "pct_retention": m.get("pct_retention"),
            }
            for m in matches
        ],
        key=lambda x: x["pct_level"],
    )


@app.post("/geo/refresh")
def geo_refresh():
    """Rebuild the filtered GeoJSON cache from the current registry."""
    refresh_geojson()
    n = len(_filtered_geojson.get("features", [])) if _filtered_geojson else 0
    return {"status": "ok", "features": n}


@app.post("/proforma/compute", response_model=ProformaResponse)
def run_proforma(req: ProformaRequest):
    df_ert_ac = pd.DataFrame(req.df_ert_ac)
    df_pf = compute_proforma(df_ert_ac, req.params)
    npv_year = int(req.params.get("npv_year", 20))
    summaries_df = compute_summaries(df_pf, req.params, npv_years=npv_year)

    return {
        "proforma_rows": df_pf.to_dict(orient="records"),
        "summaries": summaries_df.to_dict(orient="records"),
    }


@app.post("/carbon/calculate", response_model=CarbonResponse)
def calculate_carbon(inputs: CarbonInputs):
    species_tpa = inputs.species_tpa  # already a positional list [SP1, SP2, ...]

    # Try FVS models first (LRU cached, joblib/sklearn Pipeline)
    models = get_fvs_models(inputs.variant, inputs.loccode, inputs.pct_level)

    if models is not None:
        wide = predict_fvs_metrics(models, inputs.survival, inputs.si, species_tpa)
        if not wide.empty:
            if "ABLD_C" in wide.columns:
                wide["Annual_ABLD_C"] = (
                    wide["ABLD_C"].diff().fillna(wide["ABLD_C"].iloc[0])
                )

            # Prepend base year row
            zero_row = {col: 0.0 for col in wide.columns}
            zero_row["Year"] = 2024
            wide = pd.concat([pd.DataFrame([zero_row]), wide], ignore_index=True)
            wide = wide.sort_values("Year").reset_index(drop=True)

            return {
                "carbon_df": wide.to_dict(orient="records"),
                "model_source": "fvs",
            }

    # Fallback: coefficient-based prediction
    coefficients = get_carbon_coefficients()
    results = compute_carbon_scores(
        coefficients=coefficients,
        species_tpa=species_tpa,
        survival=inputs.survival,
        si=inputs.si,
    )
    results.insert(
        0,
        {
            "Year": 2024,
            "ABLD_C": 0.0,
            "Annual_ABLD_C": 0.0,
        },
    )

    return {
        "carbon_df": results,
        "model_source": "coefficients",
    }


@app.post("/carbon/units", response_model=CarbonUnitsResponse)
def carbon_units_endpoint(
    req: CarbonUnitsRequest,
    protocol_rules: dict = Depends(get_protocol_rules),
):
    df_carbon = pd.DataFrame(req.carbon_rows)

    ruleset = req.protocol_rules or protocol_rules

    df_units = compute_carbon_units(
        df_carbon,
        req.protocols,
        ruleset,
    )

    return {"rows": df_units.to_dict(orient="records")}


@app.post("/scenario/run", response_model=ScenarioResponse)
def scenario_run(req: ScenarioRequest):
    """
    One round-trip evaluator: carbon → CU → proforma → summaries.
    Optional `solve` directive runs a closed-form acreage inverse server-side.
    """
    try:
        result = run_scenario(req.model_dump(exclude_none=False))
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.get("/scenario/defaults", response_model=ScenarioDefaults)
def scenario_defaults(variant: str, loccode: str):
    """
    Return a complete defaults dict for a (variant, loccode) pair, ready to
    feed into /scenario/run. Composes FVSVariant_presets, variant_species,
    and proforma_presets.
    """
    try:
        return default_scenario(variant, loccode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# QUARTO REPORTING
@app.post("/reports/generate")
def generate_report(req: ReportRequest = None):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")

    TMP_DIR = Path(tempfile.gettempdir()) / "quarto"
    DATA_DIR = TMP_DIR / "data"
    REPORTS_DIR = TMP_DIR / "reports"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure static lookup table required by report.ipynb is present in QUARTO_DATA_DIR
    lookup_src = QUARTO_DIR / "data" / "var_sp_ref.csv"
    lookup_dst = DATA_DIR / "var_sp_ref.csv"
    if not lookup_src.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Required lookup file not found: {lookup_src}",
        )
    lookup_dst.write_bytes(lookup_src.read_bytes())

    output_file = REPORTS_DIR / f"report_{timestamp}.pdf"

    env = os.environ.copy()
    env["QUARTO_DATA_DIR"] = str(DATA_DIR)
    env["QUARTO_FIG_DIR"] = str(QUARTO_DIR / "data" / "fig")

    if req:
        selected_variant = normalize_variant(req.data.selected_variant)
        if selected_variant not in SUPPORTED_VARIANTS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported variant value. "
                    f"Expected one of {sorted(SUPPORTED_VARIANTS)}, got: {selected_variant!r}"
                ),
            )

        df = pd.DataFrame(req.data.planting_design)
        # Defensive fix: make sure Variant row always exists for report.ipynb parsing.
        if "column1" in df.columns and "column2" in df.columns:
            mask = df["column1"].astype(str).str.strip().str.lower() == "variant"
            if not mask.any():
                df = pd.concat(
                    [
                        df,
                        pd.DataFrame(
                            [{"column1": "Variant", "column2": selected_variant}]
                        ),
                    ],
                    ignore_index=True,
                )
        df.to_csv(DATA_DIR / "planting_design.csv", index=False, header=None)

        pd.DataFrame(req.data.species_mix).to_csv(
            DATA_DIR / "species_mix.csv", index=False, header=None
        )
        pd.DataFrame(req.data.financial_options1).to_csv(
            DATA_DIR / "financial_options1.csv", index=False, header=None
        )
        pd.DataFrame(req.data.financial_options2).to_csv(
            DATA_DIR / "financial_options2.csv", index=False, header=None
        )
        pd.DataFrame(req.data.carbon).to_csv(DATA_DIR / "carbon.csv", index=False)
        pd.DataFrame([{"variant": selected_variant}]).to_csv(
            DATA_DIR / "variant.csv", index=False
        )

    try:
        result = subprocess.run(
            [
                "quarto",
                "render",
                str(QUARTO_DIR / "report.ipynb"),
                "--to",
                "typst-pdf",
                "--output-dir",
                str(REPORTS_DIR),
                "--output",
                f"report_{timestamp}.pdf",
                "--execute",
                "--no-cache",
            ],
            cwd=str(QUARTO_DIR),
            env=env,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="Quarto executable not found. Ensure Quarto is installed and on PATH.",
        )

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Quarto failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

    return FileResponse(
        path=output_file,
        media_type="application/pdf",
        filename=output_file.name,
    )

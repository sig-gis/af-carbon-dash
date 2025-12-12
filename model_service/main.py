from fastapi import FastAPI
from pathlib import Path
import json

app = FastAPI(title="Carbon Model Service")

BASE_PATH = Path("conf/base")

def load_json(filename: str):
    with open(BASE_PATH / filename, "r") as f:
        return json.load(f)

@app.get("/carbon/coefficients")
def get_carbon_coefficients():
    return load_json("carbon_model_coefficients.json")

@app.get("/proforma/presets")
def get_proforma_presets():
    return load_json("proforma_presets.json")

@app.get("/health")
def health():
    return {"status": "ok"}
from pydantic import BaseModel
from typing import List, Dict, Any

class ProformaRequest(BaseModel):
    df_ert_ac: List[Dict]  # rows of Year, CU, Protocol
    params: Dict

class ProformaSummary(BaseModel):
    Protocol: str
    total_net: float
    npv_yr20: float
    npv_per_acre: float

class ProformaResponse(BaseModel):
    proforma_rows: list[dict]
    summaries: list[ProformaSummary]

class CarbonInputs(BaseModel):
    variant: str
    loccode: str
    survival: float
    si: float
    species_tpa: List[float]  # positional: [SP1_TPA, SP2_TPA, ...] in variant species order
    pct_level: str = "PCT0"  # PCT0 (none), PCT1 (light), PCT2 (moderate)

class CarbonResponse(BaseModel):
    carbon_df: List[Dict[str, Any]]  # wide-format rows: Year, ABLD_C, BA, QMD, ...
    model_source: str  # "fvs" or "coefficients"

class ProtocolRule(BaseModel):
    BUF: float
    coeff: float
    apply_buf: bool


ProtocolRules = Dict[str, ProtocolRule]

class CarbonUnitsRequest(BaseModel):
    carbon_rows: List[Dict]  # Year, ABLD_C
    protocols: List[str]
    protocol_rules: ProtocolRules | None = None


class CarbonUnitsResponse(BaseModel):
    rows: List[Dict]

class ReportData(BaseModel):
    planting_design: List[Dict[str, Any]]  # List of rows for planting_design.csv
    species_mix: List[Dict[str, Any]]      # List of rows for species_mix.csv
    financial_options1: List[Dict[str, Any]]  # List of rows for financial_options1.csv
    financial_options2: List[Dict[str, Any]]  # List of rows for financial_options2.csv
    carbon: List[Dict[str, Any]]           # List of rows for carbon.csv
    selected_variant: str                  # Selected FVS variant

class ReportRequest(BaseModel):
    data: ReportData
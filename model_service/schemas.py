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
    tpa_df: float
    tpa_rc: float
    tpa_wh: float
    survival: float
    si: float

class CarbonYearResult(BaseModel):
    Year: int
    C_Score: float
    Annual_C_Score: float

class CarbonResponse(BaseModel):
    carbon_df: List[CarbonYearResult]

class ProtocolRule(BaseModel):
    BUF: float
    coeff: float
    apply_buf: bool


ProtocolRules = Dict[str, ProtocolRule]

class CarbonUnitsRequest(BaseModel):
    carbon_rows: List[Dict]  # Year, C_Score
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
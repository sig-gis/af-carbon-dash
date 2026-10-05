from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class ProformaRequest(BaseModel):
    df_ert_ac: List[Dict]  # rows of Year, CU, Protocol
    params: Dict


class ProformaSummary(BaseModel):
    Protocol: str
    total_net: float
    npv_yr: float
    npv_year: int
    npv_per_acre: float


class ProformaResponse(BaseModel):
    proforma_rows: list[dict]
    summaries: list[ProformaSummary]


class CarbonInputs(BaseModel):
    variant: str
    loccode: str
    survival: float
    si: float
    species_tpa: List[
        float
    ]  # positional: [SP1_TPA, SP2_TPA, ...] in variant species order
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
    species_mix: List[Dict[str, Any]]  # List of rows for species_mix.csv
    financial_options1: List[Dict[str, Any]]  # List of rows for financial_options1.csv
    financial_options2: List[Dict[str, Any]]  # List of rows for financial_options2.csv
    carbon: List[Dict[str, Any]]  # List of rows for carbon.csv
    selected_variant: str  # Selected FVS variant


class ReportRequest(BaseModel):
    data: ReportData


# Scenario API: one round-trip for the full carbon → CU → proforma pipeline.


class SolveDirective(BaseModel):
    variable: Literal["net_acres"]
    target: Literal["tnr", "npv"] = "tnr"
    value: float


class ScenarioRequest(BaseModel):
    variant: str
    loccode: str
    survival: Optional[float] = None
    si: Optional[float] = None
    species_tpa: Optional[List[float]] = None
    pct_level: str = "PCT0"
    net_acres: Optional[float] = None
    protocols: Optional[List[str]] = None
    financial_params: Optional[Dict[str, Dict[str, float]]] = (
        None  # per-protocol partial overrides
    )
    npv_year: int = 40
    solve: Optional[SolveDirective] = None
    return_dataframes: bool = False


class ScenarioSummary(BaseModel):
    Protocol: str
    net_acres: float
    total_net: float
    npv_yr: float
    npv_year: int
    npv_per_acre: float


class ScenarioResponse(BaseModel):
    inputs: Dict[str, Any]  # echo of resolved inputs after defaults applied
    summaries: List[ScenarioSummary]
    model_source: str  # "fvs" or "coefficients"
    proforma_rows: Optional[List[Dict]] = None
    carbon_rows: Optional[List[Dict]] = None
    cu_rows: Optional[List[Dict]] = None


class ScenarioDefaults(BaseModel):
    variant: str
    loccode: str
    survival: float
    si: float
    species_tpa: List[float]
    species_codes: List[str]
    pct_level: str
    net_acres: float
    protocols: List[str]
    financial_params: Dict[str, Dict[str, float]]
    npv_year: int


class BulkScenarioRequest(BaseModel):
    scenarios: List[ScenarioRequest]


class BulkScenarioError(BaseModel):
    index: int
    error: str


# results[i] is None iff an error with index == i is present.
class BulkScenarioResponse(BaseModel):
    results: List[Optional[ScenarioResponse]]
    errors: List[BulkScenarioError]


class TpaGrid(BaseModel):
    # relative bounds based on the base TPA value for a given species
    lo_factor: float = 0.25
    hi_factor: float = 4.0
    # lo and hi are absolute bounds, which take precedence over factors when set
    lo: Optional[float] = None
    hi: Optional[float] = None
    # hard ceiling on the swept value (e.g. the model's TPA cap); clamps hi
    max_value: Optional[float] = None
    steps: int = 25


class TpaSweepRequest(ScenarioRequest):
    mode: Literal["scalar", "species", "per_species"] = "scalar"
    species: Optional[int | str] = None  # required for mode="species"
    target_npv: float
    op: Literal[">=", "<=", "=="] = ">="
    grid: Optional[TpaGrid] = None
    include_curve: bool = True


class TpaInterval(BaseModel):
    lo: float
    hi: float
    lo_clipped: bool  # feasible region runs off the low edge of the swept grid
    hi_clipped: bool


class TpaCurvePoint(BaseModel):
    x: float  # swept variable value (k for scalar, TPA for species)
    npv: float  # total NPV across protocols at this point
    species_tpa: List[float]  # full mix at this point


class TpaRangeResult(BaseModel):
    species_index: Optional[int]  # None for scalar mode
    species_code: Optional[str]
    variable: Literal["k", "tpa"]
    range: Optional[TpaInterval]  # outer [min,max] box; None if nothing feasible
    intervals: List[TpaInterval]  # feasible region(s); usually one (unimodal)
    curve: Optional[List[TpaCurvePoint]] = None


class TpaSweepResponse(BaseModel):
    mode: str
    op: str
    target_npv: float
    metric: str  # e.g. "total_npv"
    base_species_tpa: List[float]
    species_codes: List[str]
    results: List[TpaRangeResult]  # one per swept dimension (one for scalar/species)

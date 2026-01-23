from pydantic import BaseModel
from typing import List, Dict, Any

class ReportData(BaseModel):
    planting_design: List[Dict[str, Any]]  # List of rows for planting_design.csv
    species_mix: List[Dict[str, Any]]      # List of rows for species_mix.csv
    financial_options1: List[Dict[str, Any]]  # List of rows for financial_options1.csv
    financial_options2: List[Dict[str, Any]]  # List of rows for financial_options2.csv
    carbon: List[Dict[str, Any]]           # List of rows for carbon.csv
    selected_variant: str                  # Selected FVS variant

class ReportRequest(BaseModel):
    data: ReportData

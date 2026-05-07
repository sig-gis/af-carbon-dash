# Model Service Documentation

This document provides detailed documentation for the functions and classes in the FastAPI service for carbon modeling and financial proforma calculations.

## Overview

The model service consists of three main scripts:

- **main.py**: FastAPI application with endpoints for data serving and computations
- **model.py**: Core computational functions for carbon modeling and financial analysis
- **schemas.py**: Pydantic models for request/response validation

## main.py

### Utility Functions

#### `load_json(filename: str)`
Loads and parses a JSON file from the base configuration directory.

**Parameters:**
- `filename` (str): Name of the JSON file to load

**Returns:**
- dict: Parsed JSON data

**Usage:**
Used internally to load static configuration data like coefficients and presets.

#### `fetch_carbon_coefficients()`
Fetches carbon coefficients from an external API.

**Returns:**
- dict: Carbon coefficients data

**Usage:**
Retrieves dynamic carbon modeling coefficients from the API.

#### `_load_proforma_defaults()`
Private function that fetches proforma presets from the API.

**Returns:**
- dict: Proforma preset data

**Usage:**
Internal function for loading default financial parameters.

#### `load_variant_presets()`
Fetches forest variant presets from the API.

**Returns:**
- dict: Variant preset data

**Usage:**
Retrieves preset configurations for different forest types.

#### `load_species_labels()`
Fetches species label mappings from the API.

**Returns:**
- dict: Species label data

**Usage:**
Provides human-readable labels for tree species codes.

#### `load_protocol_rules()`
Fetches protocol-specific rules from the API.

**Returns:**
- dict: Protocol rules data

**Usage:**
Retrieves rules for different carbon credit protocols (ACR, CAR, VERRA, etc.).

### API Endpoints

#### `GET /carbon/coefficients`
Returns carbon model coefficients.

**Returns:**
- JSON response with coefficient data

**Usage:**
Provides coefficients used in carbon score calculations.

#### `GET /proforma/presets`
Returns proforma calculation presets.

**Returns:**
- JSON response with preset financial parameters

**Usage:**
Default parameters for financial modeling.

#### `GET /variant/presets`
Returns forest variant presets.

**Returns:**
- JSON response with variant configurations

**Usage:**
Preset configurations for different forest management scenarios.

#### `GET /species/labels`
Returns species label mappings.

**Returns:**
- JSON response with species code to label mappings

**Usage:**
Human-readable species names for UI display.

#### `GET /protocol/rules`
Returns protocol-specific rules.

**Returns:**
- JSON response with protocol rules

**Usage:**
Rules for calculating carbon credits under different protocols.

#### `GET /health`
Health check endpoint.

**Returns:**
- `{"status": "ok"}`

**Usage:**
Service availability monitoring.

#### `POST /proforma/compute`
Computes financial proforma and summaries.

**Request Body:**
- `ProformaRequest` schema

**Response:**
- `ProformaResponse` with proforma rows and summaries

**Usage:**
Main endpoint for financial analysis of carbon credit projects.

#### `POST /carbon/calculate`
Calculates carbon sequestration scores over time.

**Request Body:**
- `CarbonInputs` schema

**Response:**
- `CarbonResponse` with yearly carbon scores

**Usage:**
Computes carbon sequestration based on tree planting parameters.

#### `POST /carbon/units`
Calculates carbon units (credits) for different protocols.

**Request Body:**
- `CarbonUnitsRequest` schema

**Response:**
- `CarbonUnitsResponse` with carbon unit calculations

**Usage:**
Converts carbon scores to tradable carbon credits under various protocols.

## model.py

### `compute_proforma(df_ert_ac: pd.DataFrame, p: dict) -> pd.DataFrame`
Computes financial proforma for carbon credit sales.

**Parameters:**
- `df_ert_ac` (DataFrame): Carbon units per acre by year and protocol
- `p` (dict): Financial parameters including costs, prices, acres, etc.

**Returns:**
- DataFrame: Detailed yearly financial data including revenues, costs, and net revenue

**Key Logic:**
- Groups data by protocol
- Calculates credit sales (every 5 years)
- Applies escalating credit prices
- Includes validation, verification, survey, registry, issuance, planting, and seedling costs
- Computes net revenue per year

**Usage:**
Financial modeling for carbon credit projects to determine profitability.

### `compute_summaries(df_pf: pd.DataFrame, params: dict, npv_years: int = 20) -> pd.DataFrame`
Computes financial summaries per protocol.

**Parameters:**
- `df_pf` (DataFrame): Proforma data from `compute_proforma`
- `params` (dict): Financial parameters
- `npv_years` (int): Years for NPV calculation (default 20)

**Returns:**
- DataFrame: Per-protocol summaries including total net revenue, NPV, and NPV per acre

**Key Logic:**
- Groups proforma data by protocol
- Calculates total net revenue
- Computes NPV using discount rate
- Provides per-acre financial metrics

**Usage:**
Summarizes financial performance across different carbon credit protocols.

### `compute_carbon_scores(coefficients: Dict, tpa_df: float, tpa_rc: float, tpa_wh: float, survival: float, si: float)`
Calculates carbon sequestration scores over project years.

**Parameters:**
- `coefficients` (dict): Carbon model coefficients by year
- `tpa_df` (float): Trees per acre - dominant forest
- `tpa_rc` (float): Trees per acre - riparian corridor
- `tpa_wh` (float): Trees per acre - wildlife habitat
- `survival` (float): Tree survival rate
- `si` (float): Site index

**Returns:**
- List[dict]: Yearly carbon scores with Year, C_Score, and Annual_C_Score

**Key Logic:**
- Applies linear regression model using coefficients for each year
- Calculates cumulative and annual carbon sequestration
- Uses tree density, survival, and site quality factors

**Usage:**
Core carbon modeling function to estimate sequestration over time.

### `compute_carbon_units(df_carbon: pd.DataFrame, protocols: list[str], protocol_rules: dict | None = None) -> pd.DataFrame`
Calculates carbon units (credits) under different protocols.

**Parameters:**
- `df_carbon` (DataFrame): Carbon scores by year
- `protocols` (list[str]): List of protocols to calculate for
- `protocol_rules` (dict): Protocol-specific rules (optional)

**Returns:**
- DataFrame: Carbon units by year and protocol

**Key Logic:**
- Converts carbon scores to CO2 equivalent
- Applies protocol-specific coefficients
- Performs cubic spline interpolation for smooth curves
- Calculates project vs baseline deltas
- Applies buffer requirements where specified
- Handles multiple protocols simultaneously

**Usage:**
Converts raw carbon sequestration data into tradable carbon credits.

## schemas.py

### Data Models

#### `ProformaRequest`
Request model for proforma computation.

**Fields:**
- `df_ert_ac` (List[Dict]): Rows with Year, CU (carbon units), Protocol
- `params` (Dict): Financial parameters

#### `ProformaSummary`
Summary data for each protocol.

**Fields:**
- `Protocol` (str): Protocol name
- `total_net` (float): Total net revenue
- `npv_yr20` (float): 20-year NPV
- `npv_per_acre` (float): NPV per acre

#### `ProformaResponse`
Response model for proforma endpoint.

**Fields:**
- `proforma_rows` (list[dict]): Detailed proforma data
- `summaries` (list[ProformaSummary]): Per-protocol summaries

#### `CarbonInputs`
Input parameters for carbon calculation.

**Fields:**
- `tpa_df` (float): Trees per acre - dominant forest
- `tpa_rc` (float): Trees per acre - riparian corridor
- `tpa_wh` (float): Trees per acre - wildlife habitat
- `survival` (float): Survival rate
- `si` (float): Site index

#### `CarbonYearResult`
Yearly carbon calculation result.

**Fields:**
- `Year` (int): Project year
- `C_Score` (float): Cumulative carbon score
- `Annual_C_Score` (float): Annual carbon sequestration

#### `CarbonResponse`
Response model for carbon calculation endpoint.

**Fields:**
- `carbon_df` (List[CarbonYearResult]): Yearly carbon results

#### `ProtocolRule`
Rules for a specific protocol.

**Fields:**
- `BUF` (float): Buffer percentage
- `coeff` (float): Conversion coefficient
- `apply_buf` (bool): Whether to apply buffer

#### `ProtocolRules`
Type alias for protocol rules dictionary.

#### `CarbonUnitsRequest`
Request model for carbon units calculation.

**Fields:**
- `carbon_rows` (List[Dict]): Carbon score data (Year, C_Score)
- `protocols` (List[str]): Protocols to calculate for
- `protocol_rules` (ProtocolRules): Custom rules (optional)

#### `CarbonUnitsResponse`
Response model for carbon units endpoint.

**Fields:**
- `rows` (List[Dict]): Carbon unit calculations by year and protocol

## Related Configuration Files

### `utils/config.py`

This file provides configuration utilities used by the model service.

#### `get_api_base_url() -> str`
Resolves the base URL for external API calls.

**Returns:**
- str: The API base URL

**Key Logic:**
- Checks `CARBON_API_BASE_URL` environment variable first
- Falls back to production API URL if not set
- Includes localhost option for development (commented out)
- Enforces production rules to prevent localhost usage in production

**Usage:**
Used in main.py to construct API endpoints for fetching external data.

#### `normalize_params(params: dict) -> dict`
Converts parameter dictionary to JSON-safe Python primitives.

**Parameters:**
- `params` (dict): Dictionary containing various data types

**Returns:**
- dict: Cleaned dictionary with JSON-safe values

**Key Logic:**
- Converts numpy scalars to Python floats
- Replaces NaN and infinite values with None
- Preserves other data types unchanged

**Usage:**
Ensures parameters can be safely serialized to JSON for API responses or logging.

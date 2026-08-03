# Model Service Documentation

This document describes the current model service in `af-carbon-dash`. The service is a FastAPI application that supports carbon estimation, carbon-unit conversion, proforma calculations, scenario runs, breakeven solving, model registry access, filtered GeoJSON, and PDF report generation.

## Current Directory Context

Important paths:

- `carbon_dash.py`: Streamlit dashboard entry point.
- `model_service/main.py`: FastAPI app, endpoints, startup lifecycle, and report generation.
- `model_service/model.py`: core FVS, carbon, proforma, scenario, and solve logic.
- `model_service/schemas.py`: Pydantic request and response models.
- `model_service/tpa_sweep.py`: TPA breakeven sweep/range solver.
- `model_service/geo.py`: filtered GeoJSON generation from the model registry.
- `model_service/config_sync.py`: synchronization of shipped config defaults into the model store.
- `model_service/store/`: model, config, and GeoJSON storage abstraction.
- `aff_dash_client/`: programmatic Python client and CLI for scenario runs.
- `pages/1_project_builder.py`: Project Builder page with Site Selection, Planting Design, and Solver.
- `pages/3_admin.py`: Model Management page for non-production environments.

## Service Overview

The FastAPI app is created in `model_service/main.py` as `FastAPI(title="Carbon Model Service", lifespan=lifespan)`.

The current modeling pipeline is:

1. Resolve variant, location, PCT, and species inputs.
2. Use registered FVS-derived model predictions when available.
3. Fall back to coefficient-based carbon calculations when FVS models are unavailable.
4. Convert carbon outputs to protocol-specific carbon units.
5. Calculate financial proforma rows and summary metrics.
6. Optionally solve breakeven acreage or TPA ranges.

## Startup Behavior

The `lifespan` function runs on startup. It loads the model registry, synchronizes default configuration from `conf/base`, and builds the cached filtered GeoJSON used by the dashboard map. Model files are loaded lazily on first use rather than all at startup.

The `refresh_geojson()` function rebuilds the cached filtered GeoJSON from the configured model store.

## Configuration

The service uses shipped configuration under `conf/base`, including carbon coefficients, proforma presets, species labels, protocol rules, variant species, variant presets, and workflow steps.

Shared helpers in `utils/config.py` include:

- `get_api_base_url()`: resolves the model-service base URL and honors `CARBON_API_BASE_URL`.
- `normalize_params(params)`: converts numpy and scientific values into JSON-safe values.

## Main API Endpoints

Reference data endpoints:

- `GET /carbon/coefficients`: returns coefficient-based carbon-model parameters.
- `GET /proforma/presets`: returns default proforma assumptions.
- `GET /variant/presets`: returns effective variant presets.
- `GET /species/labels`: returns species-code labels.
- `GET /protocol/rules`: returns carbon protocol rules.
- `GET /variant/species`: returns effective variant-to-species mappings.
- `GET /health`: returns service status.

Geo and registry endpoints:

- `GET /geo/variants`: returns filtered GeoJSON containing locations with registered models.
- `POST /geo/refresh`: rebuilds the filtered GeoJSON cache.
- `GET /models/registry`: returns the current model registry.
- `GET /models/pct-info`: returns available PCT levels and retention percentages for a variant/location pair.

Carbon and financial endpoints:

- `POST /carbon/calculate`: calculates carbon metrics for a variant/location/PCT/species scenario.
- `POST /carbon/units`: converts carbon rows into protocol-specific carbon units.
- `POST /proforma/compute`: computes proforma rows and financial summaries.

Scenario endpoints:

- `GET /scenario/defaults`: returns default scenario inputs for a variant/location pair.
- `POST /scenario/run`: runs the full carbon-to-financial scenario pipeline.
- `POST /scenario/bulk`: evaluates up to 1000 scenarios in one request.
- `POST /scenario/solve-tpa`: sweeps species TPA values to find ranges where NPV meets a target.

Report endpoint:

- `POST /reports/generate`: generates a PDF report with Quarto from dashboard-provided data.

## Carbon Calculation

`POST /carbon/calculate` uses the `CarbonInputs` schema. Current fields include:

- `variant`
- `loccode`
- `survival`
- `si`
- `species_tpa`
- `pct_level`, defaulting to `PCT0`

The endpoint first tries to load matching FVS models by variant, location code, and PCT level. If model output is available, it returns FVS-based projections. If not, it falls back to coefficient-based carbon scores. The response includes `carbon_df` and `model_source`, where `model_source` is `fvs` or `coefficients`.

## Scenario Evaluation

`POST /scenario/run` uses `ScenarioRequest` and returns `ScenarioResponse`. It can backfill missing values from `default_scenario(variant, loccode)`.

Important scenario fields include:

- `variant`
- `loccode`
- `survival`
- `si`
- `species_tpa`
- `pct_level`
- `net_acres`
- `protocols`
- `financial_params`
- `npv_year`
- `solve`
- `return_dataframes`

The optional solve directive can solve for `net_acres` needed to reach a target metric such as NPV.

## TPA Sweep

`POST /scenario/solve-tpa` uses `TpaSweepRequest`. It supports these modes:

- `scalar`: scales the full species mix.
- `species`: varies one selected species.
- `per_species`: evaluates each species separately.

The response includes feasible intervals and optional curve points showing how NPV changes across the TPA sweep.

## Core Model Functions

- `get_fvs_models(variant, loccode, pct_level)`: loads and caches a registered joblib model collection from the model store.
- `predict_fvs_metrics(models, survival, si, species_tpa)`: runs FVS-derived sklearn models and returns wide-format annual outputs.
- `compute_carbon_scores(...)`: coefficient-based fallback carbon model.
- `compute_carbon_units(...)`: converts carbon values into protocol-specific carbon units.
- `compute_proforma(...)`: computes yearly financial proforma rows.
- `compute_summaries(...)`: computes total net revenue, NPV, NPV horizon, and NPV per acre.
- `default_scenario(...)`: builds complete default inputs for a variant/location pair.
- `run_scenario(...)`: executes the full carbon, carbon-unit, proforma, summary, and optional solve pipeline.

## Schemas

Major schemas in `model_service/schemas.py` include:

- Proforma: `ProformaRequest`, `ProformaSummary`, `ProformaResponse`
- Carbon: `CarbonInputs`, `CarbonResponse`, `ProtocolRule`, `CarbonUnitsRequest`, `CarbonUnitsResponse`
- Report: `ReportData`, `ReportRequest`
- Scenario: `SolveDirective`, `ScenarioRequest`, `ScenarioSummary`, `ScenarioResponse`, `ScenarioDefaults`, `BulkScenarioRequest`, `BulkScenarioError`, `BulkScenarioResponse`
- TPA sweep: `TpaGrid`, `TpaSweepRequest`, `TpaInterval`, `TpaCurvePoint`, `TpaRangeResult`, `TpaSweepResponse`

## Dashboard Integration

The Streamlit dashboard calls the model service through `get_api_base_url()` and `requests`.

- Site Selection uses GeoJSON and registry-aware variant availability.
- Planting Design calls carbon, carbon-unit, proforma, and report workflows.
- Solver calls scenario endpoints for breakeven acreage, sensitivity grids, and TPA sweeps.
- Model Management updates model registry and associated variant/species/preset metadata outside production.

## Operational Notes

- Set `CARBON_API_BASE_URL` for deployed dashboard environments.
- Model files must exist in the configured model store under `models/`.
- `registry.json` controls available variant/location/PCT combinations.
- Filtered GeoJSON exposes only locations with registered models.
- Report generation requires Quarto and report assets in the runtime image.
- `ENV=production` hides the Model Management page.

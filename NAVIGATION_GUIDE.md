# Dashboard Navigation Guide

This guide explains how to navigate the current American Forests Carbon Dashboard in `af-carbon-dash`. It uses no emojis so the Markdown and text versions can be copied cleanly to Google Drive.

## Launch

Run the dashboard from the `af-carbon-dash` directory:

```bash
uv run streamlit run carbon_dash.py
```

The Streamlit entry point is `carbon_dash.py`.

## Main Navigation Pages

The app uses Streamlit navigation with these pages:

- Project Builder
- Frequently Asked Questions
- Model Management, visible only when `ENV` is not `production`

In production, Model Management is hidden.

## Project Builder Workflow

Project Builder contains three internal workflow views:

1. Site Selection Map
2. Planting Design
3. Solver

The left sidebar shows the Project Workflow list from `conf/base/workflow_steps.json`. The active workflow step is highlighted.

## Site Selection Map

Use Site Selection Map to choose the FVS variant/location geometry for the project area. This selection controls species options, model defaults, PCT options, and downstream calculations.

Ways to set a location:

- Enter latitude and longitude, then select `Add Point to Map`.
- Enter address fields, then select `Go to Address`.
- Upload GeoJSON.
- Upload shapefile components.
- Upload a zipped shapefile.
- For large zipped shapefiles, use the temporary signed Google Cloud Storage upload workflow.

The dashboard attempts to auto-select a supported FVS variant/location when a point, address, or uploaded geometry intersects a supported map feature.

At the bottom of Site Selection, the `Planting Design` and `Solver` buttons are disabled until a supported location is selected.

## Planting Design

Use Planting Design to estimate carbon units and financial results for a fixed project acreage and planting design.

Main inputs include:

- Selected variant/location
- Sub-variant or registered model selection where applicable
- PCT level
- Net acres
- Survival percentage
- Site index, except where a variant does not use site index
- Species mix using trees-per-acre sliders
- Protocol selection
- Financial assumptions

The PCT selector is based on registry data for the selected variant/location. Typical levels are `PCT0`, `PCT1`, and `PCT2`.

Carbon outputs can include projection charts, carbon units by protocol, and per-acre carbon-unit estimates. Supported protocol names include ACR, CAR, VERRA, GS, and ISO.

Financial outputs can include a net revenue chart, summary table, proforma rows, and downloadable proforma CSV where enabled.

The `Generate Project Report` action sends dashboard data to the model service and generates a PDF report using Quarto.

## Solver

Use Solver for breakeven questions instead of fixed-acreage evaluation.

Solver can answer:

- How many net acres are required to reach a target NPV?
- How does breakeven acreage change under different financial assumptions?
- What planting density is required to break even?

Solver uses the scenario endpoints in the model service. It supports breakeven acreage, financial-lever sensitivity grids, and TPA breakeven sweeps.

Density sweep modes include:

- Scalar, which scales the whole species mix
- Species, which varies one selected species while holding others fixed
- Per-species, which evaluates each species separately

## Frequently Asked Questions

Use the FAQ page for reference content, including baseline assumptions, protocol differences, carbon accounting assumptions, FVS and machine-learning approximation concepts, unrealistic scenario warnings, and verification cost logic.

## Model Management

Model Management is available only outside production. It is intended for administrators and developers managing model availability.

Capabilities include:

- Uploading regression model `.pkl` files
- Validating model file structure
- Inferring metadata from model filenames
- Assigning variant, location code, PCT level, retention percentage, and version metadata
- Configuring species order and default TPA values
- Setting TPA caps
- Inspecting and editing model registry entries

The upload helper expects filenames shaped like:

```text
{Variant}_v{Version}_{PCT}_{Method}_{LocCode}_ridge_models.pkl
```

Example:

```text
PN_v1_PCT0_Jenkins_609_ridge_models.pkl
```

## Common Navigation Tips

- Start with Site Selection.
- Use Planting Design for fixed-acreage project evaluation.
- Use Solver for breakeven acreage, financial sensitivity, and breakeven TPA questions.
- If outputs are empty, confirm that a location is selected, species TPA values are not all zero, protocols are selected, the model-service URL is correct, and registry entries exist for the selected variant/location/PCT.
# Streamlit Dashboard Navigation Guide

This guide explains how to navigate the **American Forests Carbon Dashboard** Streamlit app and complete the Project Builder workflow.

## 1. Launch the App

Run the dashboard from the repo root:

```bash
uv run streamlit run carbon_dash.py
```

The app opens with a page sidebar that contains two main pages:

- **🌲 Project Builder** (primary workflow)
- **❓ Frequently Asked Questions** (reference content)

---

## 2. Project Builder (Primary Workflow)

The Project Builder contains **two main tabs** that you move between using the buttons on the page:

1. **Site Selection Map** (default landing tab)
2. **Planting Design**

The left sidebar also shows a **Project Workflow** list with the current step highlighted.

### 2.1 Site Selection Map

Use this tab to select the **FVS Variant** that fits your project location.

**Ways to set a location:**

- **Add a point by latitude/longitude**
- **Look up an address** (street, city, state)
- **Upload a GeoJSON or Shapefile** (can be zipped)

**Tips:**

- If you upload a file in a different CRS, the dashboard will **reproject to EPSG:4326** automatically.
- Uploaded geometries are filtered to the supported FVS variants.

**Select a variant:**

- Click a variant on the map to select it.
- The selection is shown in a success banner below the map.

Once a variant is selected, click **➡️ Planting Design** to continue.

---

### 2.2 Planting Design

This tab contains the modeling workflow in **four expanders**:

#### 1) Planting Parameters

- Enter **Net Acres**
- Adjust **Survival %** and **Site Index**
- Set a **Species Mix** (TPA sliders)

This section drives all downstream outputs.

#### 2) Carbon Estimates

- Choose one or more **protocols** (ACR/CAR/VERRA, GS, ISO)
- View the carbon unit chart

#### 3) Project Financials

- Enter financial assumptions (costs, prices, inflation, etc.)
- Review the **Net Revenue** chart and **summary table**
- Download the **proforma CSV**

#### 4) Generate Report

- Click **Generate Project Report** to download a PDF report

To return to the map, use **⬅️ Site Selection** at the top right.

---

## 3. FAQ Page

Use the **❓ Frequently Asked Questions** page for definitions and model assumptions, including:

- Baseline scenario
- Protocol differences
- Calculation assumptions
- Verification cost formula

---

## 4. Common Navigation Tips

- **Sidebar workflow steps** highlight the current stage.
- Your selections are preserved across tabs using Streamlit session state.
- If data or charts appear empty, confirm:
  - a variant is selected
  - planting sliders are populated
  - protocols are chosen

---

If you'd like this guide expanded with screenshots or example inputs, let me know.
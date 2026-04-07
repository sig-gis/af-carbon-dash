import json
import logging
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd
import numpy as np
import numpy_financial as npf
from typing import List, Dict
from scipy.interpolate import make_interp_spline
from sklearn.preprocessing import PolynomialFeatures

from model_service.store import get_store

logger = logging.getLogger(__name__)

APP_ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = APP_ROOT / "conf" / "base"

FVS_MODEL_CACHE_SIZE = 16


def _load_registry() -> list[dict]:
    store = get_store()
    return store.get_json("registry.json").get("models", [])


@lru_cache(maxsize=FVS_MODEL_CACHE_SIZE)
def get_fvs_models(variant: str, loccode: str, pct_level: str = "PCT0") -> dict | None:
    """
    Load and cache an FVS model collection via joblib.
    LRU cache keeps the most recent models in memory and evicts the oldest
    when the cache is full, preventing unbounded memory growth.

    Models are sklearn Pipeline objects keyed by (year, variable).
    """
    registry = _load_registry()
    entry = next(
        (m for m in registry
         if m["variant"] == variant
         and m["loccode"] == loccode
         and m.get("pct_level", "PCT0") == pct_level),
        None,
    )
    if entry is None:
        logger.warning(
            "No model registry entry for variant=%s loccode=%s pct=%s",
            variant, loccode, pct_level,
        )
        return None

    store = get_store()
    filename = entry.get("filename") or Path(entry["path"]).name
    try:
        model_path = store.get_file(f"models/{filename}")
    except FileNotFoundError:
        logger.warning("Model file not found in store: models/%s", filename)
        return None

    models = joblib.load(model_path)

    logger.info("Loaded FVS models from %s (%d entries)", model_path, len(models))
    return models


def predict_fvs_metrics(
    models: dict,
    survival: float,
    si: float,
    species_tpa: list[float],
) -> pd.DataFrame:
    """
    Run prediction across all (year, variable) model entries.

    Parameters
    ----------
    models : dict keyed by (year, variable) -> sklearn Ridge Pipeline
    survival : survival percentage
    si : site index
    species_tpa : list of species TPA values in preset order (up to 4)

    Returns
    -------
    Wide-format DataFrame: Year, ABLD_C, BA, QMD, SDI, TCuFt, MCuFt, ...
    """
    total_tpa = sum(species_tpa)
    # Pad to exactly 4 species slots (SP1–SP4) as the pipelines expect
    padded = (list(species_tpa) + [0, 0, 0, 0])[:4]

    X_raw = np.array(
        [[float(survival), float(total_tpa), *[float(s) for s in padded], float(si)]],
        dtype=float,
    )

    # Detect model type: v3 (plain LinearRegression, expects 119 poly features)
    # vs v4 (Pipeline with built-in transform, expects 7 raw features)
    sample_model = next(iter(models.values()))
    needs_poly = getattr(sample_model, "n_features_in_", 7) > len(X_raw[0])

    if needs_poly:
        poly = PolynomialFeatures(degree=3, include_bias=False)
        X = poly.fit_transform(X_raw)
    else:
        # v4 pipelines expect named DataFrame
        X = pd.DataFrame([{
            "Survival": float(survival),
            "total_TPA": float(total_tpa),
            "SP1_TPA": float(padded[0]),
            "SP2_TPA": float(padded[1]),
            "SP3_TPA": float(padded[2]),
            "SP4_TPA": float(padded[3]),
            "SI": float(si),
        }])

    rows = []
    for (year, var), model in models.items():
        y_pred = max(model.predict(X)[0], 0)  # clamp negatives to 0 per Dave
        rows.append({"Year": int(year), "Variable": var, "Value": y_pred})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    wide = df.pivot(index="Year", columns="Variable", values="Value").reset_index()
    wide = wide.sort_values("Year").reset_index(drop=True)
    return wide

def compute_proforma(df_ert_ac: pd.DataFrame, p: dict) -> pd.DataFrame:
    results = []

    for protocol, subdf in df_ert_ac.groupby("Protocol"):
        df = subdf[['Year', 'CU']].copy()
        df = df.rename(columns={'CU': 'CU_ac'})
        df['Project_acres'] = p['net_acres']
        df['CU'] = df['CU_ac'] * p['net_acres']

        # credit volume: sell every 5th year including start year
        df['CUs_Sold'] = 0.0
        for i, row in df.iterrows():
            if (
                row['Year'] == p['year_start']
                or ((row['Year'] - p['year_start']) % 5 == 0 and row['Year'] > p['year_start'])
            ):
                df.loc[i, 'CUs_Sold'] = df.loc[max(0, i - 4):i, 'CU'].sum()

        # revenue
        df['CU_Credit_Price'] = (
            p['price_per_ert_initial']
            * ((1 + p['credit_price_increase']) ** (df['Year'] - p['year_start']))
        )
        df['Total_Revenue'] = df['CUs_Sold'] * df['CU_Credit_Price']

        # costs
        df['Validation_and_Verification'] = 0
        df.loc[df['Year'] == p['year_start'], 'Validation_and_Verification'] = p['validation_cost']
        df.loc[
            (df['Year'] > p['year_start']) &
            ((df['Year'] - p['year_start']) % 5 == 0),
            'Validation_and_Verification'
        ] = p['verification_cost']

        df['Survey_Cost'] = 0
        df.loc[
            (df['Year'] - p['year_start']) % 5 == 4,
            'Survey_Cost'
        ] = p['num_plots'] * p['cost_per_cfi_plot'] * (1 + p['anticipated_inflation'])

        df['Registry_Fees'] = p['registry_fees']
        df['Issuance_Fees'] = df['CUs_Sold'] * p['issuance_fee_per_ert']
        df['Planting_Cost'] = p['planting_cost']

        df['Total_Costs'] = (
            df['Validation_and_Verification']
            + df['Survey_Cost']
            + df['Registry_Fees']
            + df['Issuance_Fees']
            + df['Planting_Cost']
        )

        df['Net_Revenue'] = df['Total_Revenue'] - df['Total_Costs']
        df['Protocol'] = protocol
        results.append(df)

    return pd.concat(results, ignore_index=True)


def compute_summaries(
    df_pf: pd.DataFrame,
    params: dict,
    npv_years: int = 20,
) -> pd.DataFrame:
    """
    Compute per-protocol financial summaries from proforma output.
    """

    year_start = params["year_start"]
    discount_rate = params["anticipated_inflation"] + params["discount_rate"]
    net_acres = params["net_acres"]

    summaries = []

    for protocol, subdf in df_pf.groupby("Protocol"):
        subdf = subdf.sort_values("Year")

        total_net = subdf["Net_Revenue"].sum()

        cashflows = subdf[
            subdf["Year"] <= (year_start + npv_years)
        ]["Net_Revenue"]

        npv_yr = float(npf.npv(discount_rate, cashflows))
        npv_per_acre = npv_yr / net_acres if net_acres else None

        summaries.append({
            "Protocol": protocol,
            "total_net": total_net,
            "npv_yr20": npv_yr,
            "npv_per_acre": npv_per_acre,
        })

    return pd.DataFrame(summaries)

def compute_carbon_scores(
    coefficients: Dict,
    species_tpa: list[float],
    survival: float,
    si: float,
):
    years = []
    c_scores = []
    ann_c_scores = []

    tpa_total = sum(species_tpa)

    # Extract species-specific coefficient keys (anything starting with TPA_ except TPA_total)
    sample_year = next(iter(sorted(coefficients.keys(), key=int)))
    sp_coeff_keys = [k for k in coefficients[sample_year] if k.startswith("TPA_") and k != "TPA_total"]

    for year in sorted(coefficients.keys(), key=int):
        c = coefficients[year]
        # Sum species contributions positionally
        sp_score = sum(
            c.get(sp_coeff_keys[i], 0) * species_tpa[i]
            for i in range(min(len(sp_coeff_keys), len(species_tpa)))
        )
        c_score = (
            sp_score
            + c["TPA_total"] * tpa_total
            + c["Survival"] * survival
            + c["SI"] * si
            + c["Intercept"]
        )

        ann = c_score - c_scores[-1] if c_scores else c_score

        years.append(int(year))
        c_scores.append(c_score)
        ann_c_scores.append(ann)

    return [
        {
            "Year": y,
            "ABLD_C": round(c, 4),
            "Annual_ABLD_C": round(a, 4),
        }
        for y, c, a in zip(years, c_scores, ann_c_scores)
    ]

def compute_carbon_units(
    df_carbon: pd.DataFrame,
    protocols: list[str],
    protocol_rules: dict | None = None,
) -> pd.DataFrame:
    """
    df_carbon: DataFrame with ['Year', 'ABLD_C']
    returns: DataFrame with ['Year', 'CU', 'Protocol']
    """

    ruleset = protocol_rules
    all_protocol_dfs = []

    for protocol in protocols:
        # Backward-compatible fallback chain for legacy combined protocol key
        rules = (
            ruleset.get(protocol)
            or ruleset.get("ACR")
            or ruleset.get("CAR")
            or ruleset.get("VERRA")
            or ruleset.get("ACR/CAR/VERRA")
        )

        if rules is None:
            raise KeyError(
                "No protocol rules found for selected protocols and no fallback protocol rules are configured."
            )


        df_base = df_carbon.copy()
        df_base["Onsite_Total_CO2"] = df_base["ABLD_C"] * 3.667 * rules["coeff"]

        # Interpolation
        df_poly = df_base[["Year", "Onsite_Total_CO2"]].sort_values("Year")
        X = df_poly["Year"].values
        y = df_poly["Onsite_Total_CO2"].values

        spline = make_interp_spline(X, y, k=1)
        years_interp = np.arange(X.min(), X.max() + 1)
        y_interp = spline(years_interp)

        df_project = pd.DataFrame({
            "Year": years_interp,
            "project": y_interp,
        })

        df_baseline = pd.DataFrame({
            "Year": years_interp,
            "baseline": np.zeros_like(years_interp, dtype=float),
        })

        df_project["delta_project"] = df_project["project"].diff()
        df_baseline["delta_baseline"] = df_baseline["baseline"].diff()

        merged = df_project.merge(
            df_baseline[["Year", "delta_baseline"]],
            on="Year",
        )

        merged["C_total"] = merged["delta_project"] - merged["delta_baseline"]

        if rules["apply_buf"]:
            merged["BUF"] = merged["C_total"] * rules["BUF"]
        else:
            merged["BUF"] = 0.0

        merged["CU"] = merged["C_total"] - merged["BUF"]
        merged["Protocol"] = protocol

        # JSON safety
        merged = merged.replace([np.inf, -np.inf], np.nan)
        merged = merged.dropna(subset=["CU"])

        all_protocol_dfs.append(
            merged[["Year", "CU", "Protocol"]]
        )

    return pd.concat(all_protocol_dfs, ignore_index=True)
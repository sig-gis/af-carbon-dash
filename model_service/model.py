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
            "npv_yr": npv_yr,
            "npv_year": int(npv_years),
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
        # Enforce modeling/report baseline at 2026 for CU generation.
        start_year = max(int(X.min()), PROFORMA_YEAR_START)
        years_interp = np.arange(start_year, int(X.max()) + 1)
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


# ---------------------------------------------------------------------------
# Scenario orchestration: full carbon → CU → proforma pipeline + acreage solver
# ---------------------------------------------------------------------------

PROFORMA_YEAR_START = 2026
PROFORMA_YEARS_ADVANCE = 35


@lru_cache(maxsize=16)
def _load_base_json(filename: str) -> dict:
    with open(BASE_PATH / filename, "r") as f:
        return json.load(f)


def default_scenario(variant: str, loccode: str) -> dict:
    """
    Compose authoritative default inputs for a (variant, loccode) pair.
    Pulls from FVSVariant_presets.json, variant_species.json, proforma_presets.json.

    Returned dict is shaped to feed straight into run_scenario(); callers may
    override any subset of fields.
    """
    store = get_store()
    variant_presets = store.get_json("config/FVSVariant_presets.json")
    species_map = store.get_json("config/variant_species.json")
    proforma_presets = _load_base_json("proforma_presets.json")

    preset = variant_presets.get(variant)
    if preset is None:
        # Fall back to base variant prefix (e.g., "PN" for "PN_1")
        for key, value in variant_presets.items():
            if variant.startswith(key) or key.startswith(variant):
                preset = value
                variant = key
                break
    if preset is None:
        raise KeyError(f"No variant preset for {variant!r}")

    species_codes = species_map.get(variant) or []

    return {
        "variant": variant,
        "loccode": loccode,
        "survival": float(preset["survival"]),
        "si": float(preset["si"]),
        "species_tpa": [float(x) for x in preset["default_tpa"]],
        "species_codes": list(species_codes),
        "pct_level": "PCT0",
        "net_acres": 1000.0,
        "protocols": ["ACR"],
        "financial_params": {
            "ACR": dict(proforma_presets),
        },
        "npv_year": 40,
    }


@lru_cache(maxsize=512)
def _carbon_for_inputs_cached(
    variant: str,
    loccode: str,
    survival: float,
    si: float,
    species_tpa: tuple[float, ...],
    pct_level: str,
) -> tuple[pd.DataFrame, str]:
    """Hashable-keyed core of ``_carbon_for_inputs`` for memoization."""
    models = get_fvs_models(variant, loccode, pct_level)
    if models is not None:
        wide = predict_fvs_metrics(models, survival, si, list(species_tpa))
        if not wide.empty:
            if "ABLD_C" in wide.columns:
                wide["Annual_ABLD_C"] = wide["ABLD_C"].diff().fillna(wide["ABLD_C"].iloc[0])
            zero_row = {col: 0.0 for col in wide.columns}
            zero_row["Year"] = PROFORMA_YEAR_START
            wide = pd.concat([pd.DataFrame([zero_row]), wide], ignore_index=True)
            wide = wide.sort_values("Year").reset_index(drop=True)
            return wide, "fvs"

    coefficients = _load_base_json("carbon_model_coefficients.json")
    rows = compute_carbon_scores(
        coefficients=coefficients,
        species_tpa=list(species_tpa),
        survival=survival,
        si=si,
    )
    rows.insert(0, {"Year": PROFORMA_YEAR_START, "ABLD_C": 0.0, "Annual_ABLD_C": 0.0})
    return pd.DataFrame(rows), "coefficients"


def _carbon_for_inputs(
    variant: str,
    loccode: str,
    survival: float,
    si: float,
    species_tpa: list[float],
    pct_level: str,
) -> tuple[pd.DataFrame, str]:
    """
    Compute the carbon DataFrame for a scenario input set, returning (df, source).
    Tries FVS models first, falls back to coefficient-based prediction.

    Memoized: callers receive a fresh copy of the DataFrame so downstream
    mutation is safe even though the cache reuses the underlying result.
    """
    df, source = _carbon_for_inputs_cached(
        variant, loccode, float(survival), float(si),
        tuple(float(x) for x in species_tpa), pct_level,
    )
    return df.copy(), source


def _normalize_financial_params(
    protocols: list[str],
    overrides: dict[str, dict] | None,
) -> dict[str, dict]:
    """
    Merge per-protocol financial overrides on top of proforma_presets defaults.
    Percent-style fields (credit_price_increase, anticipated_inflation,
    discount_rate) are converted from percent (6.0) to fraction (0.06) only if
    the value looks percent-shaped (>1).
    """
    base = _load_base_json("proforma_presets.json")
    overrides = overrides or {}

    PERCENT_FIELDS = {"credit_price_increase", "anticipated_inflation", "discount_rate"}

    def merge(protocol: str) -> dict:
        merged = dict(base)
        merged.update(overrides.get(protocol, {}))
        for field in PERCENT_FIELDS:
            value = float(merged.get(field, 0))
            if value > 1.0:
                merged[field] = value / 100.0
            else:
                merged[field] = value
        return merged

    return {protocol: merge(protocol) for protocol in protocols}


def _proforma_for_protocol(
    df_cu: pd.DataFrame,
    protocol: str,
    fin_params: dict,
    net_acres: float,
    npv_year: int,
) -> tuple[pd.DataFrame, dict]:
    """Run the proforma + summary for one protocol at a given net_acres value."""
    params = {
        **fin_params,
        "net_acres": float(net_acres),
        "year_start": PROFORMA_YEAR_START,
        "years_advance": PROFORMA_YEARS_ADVANCE,
    }
    df_pf = compute_proforma(df_cu, params)
    df_sum = compute_summaries(df_pf, params, npv_years=npv_year)
    summary_row = df_sum[df_sum["Protocol"] == protocol].iloc[0].to_dict()
    summary_row["net_acres"] = float(net_acres)
    return df_pf, summary_row


_METRIC_TO_SUMMARY_KEY = {"tnr": "total_net", "npv": "npv_yr"}


def _solve_acreage_for_metric(
    df_cu_protocol: pd.DataFrame,
    protocol: str,
    fin_params: dict,
    npv_year: int,
    target_value: float,
    metric: str = "tnr",
) -> float:
    """
    Closed-form inverse: TNR and NPV are both exactly linear in net_acres for a
    fixed protocol, fixed financial params, and fixed npv_year horizon. Run the
    proforma at acres=1 and acres=10 to recover slope/intercept, then solve.

    For metric="npv" the result is the acreage that hits target_value at the
    given npv_year horizon under the supplied financial params.
    """
    if metric not in _METRIC_TO_SUMMARY_KEY:
        raise ValueError(
            f"Unsupported solve metric {metric!r}; expected one of "
            f"{sorted(_METRIC_TO_SUMMARY_KEY)}."
        )
    key = _METRIC_TO_SUMMARY_KEY[metric]

    _, s1 = _proforma_for_protocol(df_cu_protocol, protocol, fin_params, 1.0, npv_year)
    _, s10 = _proforma_for_protocol(df_cu_protocol, protocol, fin_params, 10.0, npv_year)

    v_1 = float(s1[key])
    v_10 = float(s10[key])

    slope = (v_10 - v_1) / 9.0
    if slope == 0:
        raise ValueError(
            f"{metric.upper()} is invariant to net_acres (slope=0) — cannot solve. "
            "Likely the protocol produces no credits for this scenario."
        )
    intercept = v_1 - slope * 1.0   # so metric(acres) = slope * acres + intercept
    target_acres = (target_value - intercept) / slope
    if target_acres <= 0:
        raise ValueError(
            f"Solved acreage is non-positive ({target_acres:.2f}). "
            f"Target {metric.upper()} {target_value} is unreachable with these inputs."
        )
    return float(target_acres)


def run_scenario(inputs: dict) -> dict:
    """
    End-to-end scenario evaluator.

    inputs is a dict matching ScenarioRequest fields. None-valued fields are
    backfilled from default_scenario(variant, loccode). Returns a dict matching
    ScenarioResponse.

    When inputs["solve"] is set, runs the closed-form acreage solver
    (single protocol only) and returns the verified result.
    """
    defaults = default_scenario(inputs["variant"], inputs["loccode"])

    resolved = {**defaults}
    for key in ("survival", "si", "species_tpa", "pct_level", "net_acres",
                "protocols", "npv_year"):
        value = inputs.get(key)
        if value is not None:
            resolved[key] = value

    fin_overrides = inputs.get("financial_params")
    resolved["financial_params"] = _normalize_financial_params(
        resolved["protocols"], fin_overrides,
    )

    solve = inputs.get("solve")
    return_dataframes = bool(inputs.get("return_dataframes", False))

    if solve is not None and len(resolved["protocols"]) != 1:
        raise ValueError(
            "Solver mode requires exactly one protocol; got "
            f"{resolved['protocols']!r}. Pick a single protocol per solve."
        )

    df_carbon, model_source = _carbon_for_inputs(
        resolved["variant"], resolved["loccode"],
        resolved["survival"], resolved["si"],
        resolved["species_tpa"], resolved["pct_level"],
    )
    protocol_rules = _load_base_json("protocol_rules.json")
    df_cu = compute_carbon_units(df_carbon, resolved["protocols"], protocol_rules)

    summaries: list[dict] = []
    proforma_frames: list[pd.DataFrame] = []

    for protocol in resolved["protocols"]:
        fin_params = resolved["financial_params"][protocol]
        df_cu_p = df_cu[df_cu["Protocol"] == protocol]

        if solve is not None and protocol == resolved["protocols"][0]:
            target_acres = _solve_acreage_for_metric(
                df_cu_p, protocol, fin_params, resolved["npv_year"],
                solve["value"], metric=solve.get("target", "tnr"),
            )
            resolved["net_acres"] = target_acres

        net_acres = resolved["net_acres"]
        df_pf, summary_row = _proforma_for_protocol(
            df_cu_p, protocol, fin_params, net_acres, resolved["npv_year"],
        )
        summaries.append(summary_row)
        proforma_frames.append(df_pf)

    response: dict = {
        "inputs": {k: resolved[k] for k in (
            "variant", "loccode", "survival", "si", "species_tpa",
            "species_codes", "pct_level", "net_acres", "protocols",
            "npv_year", "financial_params",
        )},
        "summaries": summaries,
        "model_source": model_source,
    }

    if return_dataframes and proforma_frames:
        df_pf_all = pd.concat(proforma_frames, ignore_index=True)
        response["proforma_rows"] = df_pf_all.to_dict(orient="records")
        response["carbon_rows"] = df_carbon.to_dict(orient="records")
        response["cu_rows"] = df_cu.to_dict(orient="records")

    return response

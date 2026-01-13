import pandas as pd
import numpy as np    
import numpy_financial as npf
from typing import List, Dict
from scipy.interpolate import make_interp_spline

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
        df['Seedling_Cost'] = p['seedling_cost']

        df['Total_Costs'] = (
            df['Validation_and_Verification']
            + df['Survey_Cost']
            + df['Registry_Fees']
            + df['Issuance_Fees']
            + df['Planting_Cost']
            + df['Seedling_Cost']
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
    tpa_df: float,
    tpa_rc: float,
    tpa_wh: float,
    survival: float,
    si: float,
):
    years = []
    c_scores = []
    ann_c_scores = []

    tpa_total = tpa_df + tpa_rc + tpa_wh

    for year in sorted(coefficients.keys(), key=int):
        c_score = (
            coefficients[year]["TPA_DF"] * tpa_df
            + coefficients[year]["TPA_RC"] * tpa_rc
            + coefficients[year]["TPA_WH"] * tpa_wh
            + coefficients[year]["TPA_total"] * tpa_total
            + coefficients[year]["Survival"] * survival
            + coefficients[year]["SI"] * si
            + coefficients[year]["Intercept"]
        )

        ann = c_score - c_scores[-1] if c_scores else c_score

        years.append(int(year))
        c_scores.append(c_score)
        ann_c_scores.append(ann)

    return [
        {
            "Year": y,
            "C_Score": round(c, 4),
            "Annual_C_Score": round(a, 4),
        }
        for y, c, a in zip(years, c_scores, ann_c_scores)
    ]

def compute_carbon_units(
    df_carbon: pd.DataFrame,
    protocols: list[str],
    protocol_rules: dict | None = None,
) -> pd.DataFrame:
    """
    df_carbon: DataFrame with ['Year', 'C_Score']
    returns: DataFrame with ['Year', 'CU', 'Protocol']
    """

    ruleset = protocol_rules
    all_protocol_dfs = []

    for protocol in protocols:
        rules = ruleset.get(protocol, ruleset["ACR/CAR/VERRA"])


        df_base = df_carbon.copy()
        df_base["Onsite_Total_CO2"] = df_base["C_Score"] * 3.667 * rules["coeff"]

        # Interpolation
        df_poly = df_base[["Year", "Onsite_Total_CO2"]].sort_values("Year")
        X = df_poly["Year"].values
        y = df_poly["Onsite_Total_CO2"].values

        spline = make_interp_spline(X, y, k=3)
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
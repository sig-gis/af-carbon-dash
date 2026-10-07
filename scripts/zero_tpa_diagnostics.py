"""Diagnostics for the zero-TPA carbon floor and its effect on the breakeven solver.

Background
----------
The models predict nonzero carbon at 0 total TPA. NPV is affine in net_acres, so
that phantom carbon yields a positive per-acre NPV and a large enough project
"breaks even" with nothing planted -- hence breakeven densities of 0.

It's extrapolation, not a no-plant counterfactual: training covered ~100-435
total TPA, never a bare plot (per-species zero IS in-distribution, ~half of
rows). ABLD_C is live-tree carbon, so f(0) = 0 is physical fact, which makes the
zero-TPA prediction a direct readout of model error at that boundary.

Subcommands
-----------
  scan      every registered model: floor size + per-acre NPV at TPA=0  -> CSV
  case      one (variant, loccode): units check, floor by year, NPV, design fit
  design    one model: recover the training grid from the fitted StandardScaler
  costs     show that planting_cost never reaches the proforma (separate bug)
  mechanism fleet-wide test of WHY the floor grows with stand age  -> CSV

Usage
-----
  uv run python scripts/zero_tpa_diagnostics.py scan --out /tmp/zero_tpa.csv
  uv run python scripts/zero_tpa_diagnostics.py case WS_1 503
  uv run python scripts/zero_tpa_diagnostics.py case EC 699 --pct PCT0
  uv run python scripts/zero_tpa_diagnostics.py design PN 612
  uv run python scripts/zero_tpa_diagnostics.py costs WS_1 503
  uv run python scripts/zero_tpa_diagnostics.py mechanism --out /tmp/mechanism.csv

All numbers come from the same code paths the model service uses at runtime
(model_service.model), so nothing here is a reimplementation of the pipeline.
"""

from __future__ import annotations

import argparse
import warnings
from itertools import combinations_with_replacement

import joblib
import numpy as np
import pandas as pd

# sklearn version-skew warnings on the pickles are noise for this analysis.
warnings.filterwarnings("ignore")

from model_service.model import (  # noqa: E402
    _carbon_for_inputs,
    _load_base_json,
    _normalize_financial_params,
    _proforma_for_protocol,
    compute_carbon_units,
    default_scenario,
    get_fvs_models,
    load_effective_preset_map,
    predict_fvs_metrics,
)
from model_service.store import get_store  # noqa: E402

PROTOCOL = "ACR"
NPV_YEAR = 40

# Oven-dry wood ~28 lb/ft^3; carbon ~50% of dry mass; stemwood ~78% of aboveground
# live biomass. Only confirms ABLD_C is tons/ac, not lb/ac. Not a model input.
_TONS_PER_CUFT = 0.014
_CARBON_FRACTION = 0.5
_STEM_SHARE_OF_AGL = 0.78


# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #
def _registry_models() -> list[dict]:
    return get_store().get_json("registry.json").get("models", [])


def _fin_params(planting_cost: float | None = None) -> dict:
    """Default ACR financial params, optionally with planting_cost overridden."""
    fin = _normalize_financial_params([PROTOCOL], None)[PROTOCOL]
    if planting_cost is not None:
        fin = {**fin, "planting_cost": float(planting_cost)}
    return fin


def npv_line_at_tpa0(variant: str, loccode: str, pct: str, fin: dict) -> tuple[float, float]:
    """NPV vs acreage at zero TPA as (slope $/ac, intercept = fixed costs).

    NPV is exactly affine in net_acres at fixed financials and horizon, so two
    evaluations pin the line.
    """
    d = default_scenario(variant, loccode)
    zero = [0.0] * len(d["species_tpa"])
    df_carbon, _ = _carbon_for_inputs(d["variant"], loccode, d["survival"], d["si"], zero, pct)
    df_cu = compute_carbon_units(df_carbon, [PROTOCOL], _load_base_json("protocol_rules.json"))
    n1 = _proforma_for_protocol(df_cu, PROTOCOL, fin, 1.0, NPV_YEAR)[1]["npv_yr"]
    n2 = _proforma_for_protocol(df_cu, PROTOCOL, fin, 2.0, NPV_YEAR)[1]["npv_yr"]
    slope = n2 - n1
    return slope, n1 - slope


def _training_moments(filename: str) -> dict[str, tuple[float, float, float]]:
    """First three moments per raw feature, recovered from the fitted StandardScaler.

    The scaler is fitted on the degree-3 expansion, so scaler.mean_ holds every
    monomial's training mean; the pure powers of each feature give its moments --
    enough to reconstruct the design grid without the training data.

    joblib.load reads this repo's own artifacts, same as model_service/model.py.
    """
    models = joblib.load(f"data/models/{filename}")
    pipeline = next(iter(models.values()))
    poly, scaler = pipeline.steps[0][1], pipeline.steps[1][1]
    names = list(poly.feature_names_in_)

    combos: list[tuple[int, ...]] = []
    for degree in (1, 2, 3):
        combos += list(combinations_with_replacement(range(len(names)), degree))
    if len(combos) != len(scaler.mean_):
        raise RuntimeError(
            f"polynomial layout mismatch: {len(combos)} monomials vs {len(scaler.mean_)} scaler means"
        )
    idx = {c: i for i, c in enumerate(combos)}

    out = {}
    for i, name in enumerate(names):
        out[name] = (
            float(scaler.mean_[idx[(i,)]]),
            float(scaler.mean_[idx[(i, i)]]),
            float(scaler.mean_[idx[(i, i, i)]]),
        )
    out["_n_samples"] = (float(scaler.n_samples_seen_), 0.0, 0.0)
    return out


def fit_level_grid(m1: float, m2: float, m3: float, max_levels: int = 14) -> tuple[int, float, float, float]:
    """Best equally-spaced L-level grid matching the first three moments.

    Such a grid is symmetric about its mean, so hi = 2*m1 - lo is exact and only
    lo and L are free; scanning lo against the 2nd and 3rd moments jointly beats
    solving lo from the variance alone. Returns (L, lo, hi, relative_error).

    Meaningless for skewed features -- callers gate on skew (see _print_design).
    """
    sd = np.sqrt(max(m2 - m1**2, 0.0))
    if sd == 0:
        return (1, m1, m1, 0.0)
    best = None
    # Widest plausible half-width is the 2-level case (all mass at the extremes).
    for L in range(2, max_levels + 1):
        for lo in np.linspace(m1 - 2.5 * sd, m1 - 0.5 * sd, 400):
            levels = np.linspace(lo, 2 * m1 - lo, L)
            e2 = abs((levels**2).mean() - m2) / abs(m2) if m2 else 0.0
            e3 = abs((levels**3).mean() - m3) / abs(m3) if m3 else 0.0
            err = e2 + e3
            if best is None or err < best[3]:
                best = (L, float(lo), float(2 * m1 - lo), float(err))
    return best


# --------------------------------------------------------------------------- #
# scan: every registered model
# --------------------------------------------------------------------------- #
def cmd_scan(args) -> None:
    fin = _fin_params()
    rows = []
    entries = _registry_models()
    for n, entry in enumerate(entries, 1):
        variant, loccode = entry["variant"], str(entry["loccode"])
        pct = entry.get("pct_level", "PCT0")
        try:
            d = default_scenario(variant, loccode)
            models = get_fvs_models(d["variant"], loccode, pct)
            if models is None:
                continue
            base = [float(x) for x in d["species_tpa"]]
            zero = [0.0] * len(base)

            wide_zero = predict_fvs_metrics(models, d["survival"], d["si"], zero)
            wide_base = predict_fvs_metrics(models, d["survival"], d["si"], base)
            if wide_zero.empty or "ABLD_C" not in wide_zero:
                continue
            floor = float(wide_zero["ABLD_C"].iloc[-1])
            signal = float(wide_base["ABLD_C"].iloc[-1])

            slope, intercept = npv_line_at_tpa0(variant, loccode, pct, fin)
            rows.append(
                {
                    "variant": variant,
                    "loccode": loccode,
                    "pct_level": pct,
                    "survival": d["survival"],
                    "si": d["si"],
                    "base_total_tpa": sum(base),
                    "final_year": int(wide_zero["Year"].iloc[-1]),
                    "ABLD_C_at_tpa0": floor,
                    "ABLD_C_at_base": signal,
                    "floor_pct_of_signal": 100 * floor / signal if signal else np.nan,
                    "npv_per_acre_at_tpa0": slope,
                    "npv_fixed_costs": intercept,
                    "acres_where_tpa0_breaks_even": (-intercept / slope) if slope > 0 else np.inf,
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep scanning past bad entries
            print(f"  ! {variant}/{loccode}/{pct}: {exc}")
        if args.verbose and n % 50 == 0:
            print(f"  ...{n}/{len(entries)}")

    df = pd.DataFrame(rows)
    print(f"\nmodels evaluated: {len(df)}")
    print(f"\nzero-TPA floor, tons C/ac (final projection year):")
    print(df["ABLD_C_at_tpa0"].describe(percentiles=[0.1, 0.5, 0.9]).to_string())
    print(f"\nexactly zero: {(df['ABLD_C_at_tpa0'] == 0).sum()}   nonzero: {(df['ABLD_C_at_tpa0'] > 0).sum()}")

    print("\nper-acre NPV at TPA=0 (ACR, 40yr) -- the metric that drives the artifact:")
    print(df["npv_per_acre_at_tpa0"].describe(percentiles=[0.1, 0.5, 0.9]).to_string())
    print(f"\nmodels with positive $/ac at zero density: "
          f"{(df['npv_per_acre_at_tpa0'] > 0).sum()} / {len(df)}")
    for acres in (1_000, 5_000, 10_000, 50_000):
        n = int((df["acres_where_tpa0_breaks_even"] <= acres).sum())
        print(f"  breakeven TPA collapses to 0 at <= {acres:>6,} acres: {n:>3} / {len(df)}")

    print("\nby variant, ranked by financial impact (median $/ac at TPA=0):")
    by_variant = (
        df.groupby("variant")
        .agg(
            models=("variant", "size"),
            median_npv_per_acre=("npv_per_acre_at_tpa0", "median"),
            max_npv_per_acre=("npv_per_acre_at_tpa0", "max"),
            median_floor_pct=("floor_pct_of_signal", "median"),
        )
        .sort_values("median_npv_per_acre", ascending=False)
    )
    print(by_variant.to_string(float_format=lambda x: f"{x:10.2f}"))
    print(
        "\nNOTE: floor_pct_of_signal is measured at the FINAL projection year (~2124),"
        "\nwhich overstates financial impact for variants whose floor grows late."
        "\nRank on npv_per_acre_at_tpa0, not on floor_pct_of_signal."
    )

    if args.out:
        df.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")


# --------------------------------------------------------------------------- #
# case: one variant/loccode in depth
# --------------------------------------------------------------------------- #
def cmd_case(args) -> None:
    variant, loccode, pct = args.variant, args.loccode, args.pct
    d = default_scenario(variant, loccode)
    base = [float(x) for x in d["species_tpa"]]
    zero = [0.0] * len(base)
    models = get_fvs_models(d["variant"], loccode, pct)
    if models is None:
        raise SystemExit(f"no model for {variant}/{loccode}/{pct}")

    print(f"=== {variant}/{loccode} {pct} ===")
    print(f"resolved variant={d['variant']} survival={d['survival']} si={d['si']}")
    print(f"base mix={base} total={sum(base):.0f} TPA")

    wide_base = predict_fvs_metrics(models, d["survival"], d["si"], base)
    wide_zero = predict_fvs_metrics(models, d["survival"], d["si"], zero)

    # 1. units cross-check -- is ABLD_C tons/acre or pounds/acre?
    last = wide_base.iloc[-1]
    if "TCuFt" in wide_base:
        implied = last["TCuFt"] * _TONS_PER_CUFT * _CARBON_FRACTION / _STEM_SHARE_OF_AGL
        print(f"\n[units] final yr {int(last['Year'])}: TCuFt={last['TCuFt']:,.0f}/ac "
              f"BA={last.get('BA', float('nan')):.1f} QMD={last.get('QMD', float('nan')):.1f}")
        print(f"        ABLD_C={last['ABLD_C']:.2f}  volume-implied={implied:.2f} tons C/ac  "
              f"ratio={last['ABLD_C']/implied:.2f}   (~1.0 confirms tons/acre)")

    # 2. the floor, year by year
    floor = wide_zero[["Year", "ABLD_C"]].merge(
        wide_base[["Year", "ABLD_C"]], on="Year", suffixes=("_tpa0", "_base")
    )
    floor["floor_%"] = 100 * floor["ABLD_C_tpa0"] / floor["ABLD_C_base"].replace(0, np.nan)
    print(f"\n[floor by year] carbon predicted with ALL species_tpa = 0")
    print(floor.iloc[:: args.every].to_string(index=False, float_format=lambda x: f"{x:10.4f}"))

    # 3. what it does to NPV
    print(f"\n[npv at TPA=0] protocol={PROTOCOL} horizon={NPV_YEAR}yr")
    for label, pc in (("as configured", None), ("planting_cost=0", 0.0)):
        slope, intercept = npv_line_at_tpa0(variant, loccode, pct, _fin_params(pc))
        acres = (-intercept / slope) if slope > 0 else float("inf")
        print(f"  {label:>16}: ${slope:10,.2f}/ac   fixed ${intercept:12,.0f}   "
              f"NPV>=0 at {acres:,.0f} acres" if slope > 0 else
              f"  {label:>16}: ${slope:10,.2f}/ac   fixed ${intercept:12,.0f}   never (slope<=0)")

    # 4. was TPA=0 anywhere near the training data?
    entry = next(
        (e for e in _registry_models()
         if e["variant"] == d["variant"] and str(e["loccode"]) == loccode
         and e.get("pct_level", "PCT0") == pct),
        None,
    )
    if entry:
        _print_design(entry["filename"], base_total=sum(base))


# --------------------------------------------------------------------------- #
# design: recover the training grid
# --------------------------------------------------------------------------- #
def _print_design(filename: str, base_total: float | None = None) -> None:
    mom = _training_moments(filename)
    n_train = int(mom.pop("_n_samples")[0])
    print(f"\n[training design] {filename}  n_train={n_train:,}")
    print(f"{'feature':>10} {'mean':>10} {'sd':>10} {'skew':>8} {'z of 0':>8}   fitted grid")
    for name, (m1, m2, m3) in mom.items():
        var = max(m2 - m1**2, 0.0)
        sd = np.sqrt(var)
        skew = (m3 - 3 * m1 * var - m1**3) / sd**3 if sd > 0 else np.nan
        z0 = -m1 / sd if sd > 0 else np.nan
        # SP*_TPA is ~50/50 "absent" vs a spread of levels -- not a symmetric
        # grid, so a fit here would only mislead.
        if abs(skew) > 0.5:
            grid = "skewed -- not a uniform grid (mass at 0 + positive levels)"
        else:
            L, lo, hi, err = fit_level_grid(m1, m2, m3)
            grid = f"{L:>2} levels {lo:7.0f}..{hi:<7.0f} (err {err:.1e})"
        print(f"{name:>10} {m1:10.2f} {sd:10.2f} {skew:8.2f} {z0:8.2f}   {grid}")

    m1, m2, m3 = mom["total_TPA"]
    sd = np.sqrt(max(m2 - m1**2, 0.0))

    # Three moments underdetermine the grid -- several (L, lo, hi) fit equally
    # well -- so report the spread, not a falsely precise point estimate.
    cands = []
    for L in range(2, 15):
        for lo in np.linspace(m1 - 2.5 * sd, m1 - 0.5 * sd, 400):
            levels = np.linspace(lo, 2 * m1 - lo, L)
            e2 = abs((levels**2).mean() - m2) / abs(m2)
            e3 = abs((levels**3).mean() - m3) / abs(m3)
            cands.append((e2 + e3, L, lo))
    cands.sort()
    good = [c for c in cands if c[0] < 5e-3][:200] or cands[:200]
    los = [c[2] for c in good]
    lo_min, lo_max = min(los), max(los)

    print(f"\n  total_TPA training support: mean={m1:.0f} sd={sd:.0f}, "
          f"and 0 sits {-m1/sd:.1f} sd below the mean.")
    print(f"  fitted design floor: ~{lo_min:.0f}-{lo_max:.0f} TPA "
          f"(NOT a precise number -- 3 moments underdetermine the grid;")
    print("   different fitting choices move it by tens of TPA. What is robust is that "
          "the\n   support does not come close to 0.)")
    print("  Ask Dave for the actual design grid rather than relying on this estimate.")
    print("  (per-species skew ~+1.5 with z(0) ~ -0.85 means individual species ARE "
          "often 0 in training;\n   it is specifically TOTAL density near zero that is out of range)")
    if base_total is not None:
        print(f"  preset total {base_total:.0f} TPA vs that floor range -> "
              f"{'inside' if base_total >= lo_max else 'below' if base_total < lo_min else 'AMBIGUOUS -- straddles the estimate'}")


def cmd_design(args) -> None:
    d = default_scenario(args.variant, args.loccode)
    entry = next(
        (e for e in _registry_models()
         if e["variant"] == d["variant"] and str(e["loccode"]) == args.loccode
         and e.get("pct_level", "PCT0") == args.pct),
        None,
    )
    if entry is None:
        raise SystemExit(f"no registry entry for {args.variant}/{args.loccode}/{args.pct}")
    _print_design(entry["filename"], base_total=sum(d["species_tpa"]))


# --------------------------------------------------------------------------- #
# costs: the planting_cost bug found alongside this
# --------------------------------------------------------------------------- #
def cmd_costs(args) -> None:
    """planting_cost is booked on year_start, but that row is dropped upstream."""
    d = default_scenario(args.variant, args.loccode)
    fin = _fin_params()
    df_carbon, _ = _carbon_for_inputs(
        d["variant"], args.loccode, d["survival"], d["si"], d["species_tpa"], args.pct
    )
    df_cu = compute_carbon_units(df_carbon, [PROTOCOL], _load_base_json("protocol_rules.json"))
    df_pf, _ = _proforma_for_protocol(df_cu, PROTOCOL, fin, 1000.0, NPV_YEAR)

    acres = 1000.0
    expected = fin["planting_cost"] * acres
    booked = df_pf.loc[df_pf["Planting_Cost"] > 0, "Year"]

    print(f"=== upfront cost trace: {args.variant}/{args.loccode} at {acres:,.0f} acres ===")
    print(f"carbon df first years : {df_carbon['Year'].head(3).tolist()}")
    print(f"cu df first years     : {sorted(df_cu['Year'].unique())[:3]}   "
          f"<- year_start dropped by the .diff() in compute_carbon_units")
    print(f"proforma first years  : {df_pf['Year'].head(3).tolist()}")
    print(f"\nplanting_cost   ${fin['planting_cost']:>10,.0f}/ac  -> booked "
          f"${df_pf['Planting_Cost'].sum():>12,.0f}  (expect ${expected:,.0f})  "
          f"{'OK' if abs(df_pf['Planting_Cost'].sum() - expected) < 1 else 'MISSING'}")
    print(f"validation_cost ${fin['validation_cost']:>10,.0f}     -> V&V total "
          f"${df_pf['Validation_and_Verification'].sum():>9,.0f} (incl. recurring verification)")
    print(f"\nupfront costs booked in year(s): {booked.tolist()}  "
          f"(t=0 for npf.npv, so undiscounted)")


# --------------------------------------------------------------------------- #
# mechanism: why does the floor grow with stand age?
# --------------------------------------------------------------------------- #
# Hypothesis: density's influence on carbon genuinely decays with stand age
# (self-thinning -- by age ~100 the site's carrying capacity sets biomass, not
# initial TPA). Nothing in training constrains what the surviving non-density
# terms imply at TPA=0, so the floor is what's left, and it grows as the density
# signal fades.
#
#   P1  in-range density sensitivity falls with age. Load-bearing: it's an
#       INTERPOLATION quantity, so it measures real stand behaviour.
#   P2  floor share rises with age, mirroring P1.
#   P3  in-range SI sensitivity rises as density sensitivity falls. Measured at
#       realistic TPA within each variant's own SI bounds -- interpolation on
#       both axes, independent of anything at TPA=0.
#
# P3 previously evaluated the floor at SI=0. Bad test: SI=0 is itself extrapolation
# (z between -2.2 and -7.6) and produced floors 419x LARGER when zeroed. Don't
# reintroduce it.
#
# The cross-section at fixed age is partly coupled by algebra (both are ratios off
# one surface); the temporal trend and P3 carry the weight.

_MECH_LOW_TOTAL = 115.0   # a realistic planting density (the common preset total)
_MECH_HIGH_TOTAL = 435.0  # the TPA cap / top of the trained range


def _scaled_mix(base: list[float], total: float) -> list[float]:
    s = sum(base)
    return [total * b / s for b in base] if s else [total / max(len(base), 1)] * len(base)


def cmd_mechanism(args) -> None:
    from scipy.stats import spearmanr

    rows = []
    entries = _registry_models()
    for n, entry in enumerate(entries, 1):
        variant, loccode = entry["variant"], str(entry["loccode"])
        pct = entry.get("pct_level", "PCT0")
        try:
            d = default_scenario(variant, loccode)
            models = get_fvs_models(d["variant"], loccode, pct)
            if models is None:
                continue
            base = [float(x) for x in d["species_tpa"]]
            surv, si = d["survival"], d["si"]
            zero = [0.0] * len(base)
            low = _scaled_mix(base, _MECH_LOW_TOTAL)
            high = _scaled_mix(base, _MECH_HIGH_TOTAL)

            w0 = predict_fvs_metrics(models, surv, si, zero)
            wl = predict_fvs_metrics(models, surv, si, low)
            wh = predict_fvs_metrics(models, surv, si, high)
            if any(w.empty or "ABLD_C" not in w for w in (w0, wl, wh)):
                continue

            # P3: in-range SI sensitivity, measured at a realistic planting
            # density and between the variant's OWN configured SI bounds, so
            # both axes stay inside the trained region.
            preset = load_effective_preset_map().get(d["variant"], {})
            si_lo = float(preset.get("si_min", si))
            si_hi = float(preset.get("si_max", si))
            w_si_lo = predict_fvs_metrics(models, surv, si_lo, low)
            w_si_hi = predict_fvs_metrics(models, surv, si_hi, low)

            for i, year in enumerate(w0["Year"]):
                p0 = float(w0["ABLD_C"].iloc[i])
                pl = float(wl["ABLD_C"].iloc[i])
                ph = float(wh["ABLD_C"].iloc[i])
                p_si_lo = float(w_si_lo["ABLD_C"].iloc[i])
                p_si_hi = float(w_si_hi["ABLD_C"].iloc[i])
                rows.append(
                    {
                        "variant": variant, "loccode": loccode, "pct_level": pct,
                        "year": int(year), "stand_age": int(year) - 2026, "si": si,
                        "si_min": si_lo, "si_max": si_hi,
                        "floor": p0, "at_low_tpa": pl, "at_high_tpa": ph,
                        "at_si_min": p_si_lo, "at_si_max": p_si_hi,
                        # P1: in-range sensitivity. Share of the high-density
                        # prediction explained by tripling density from 115->435.
                        "density_sensitivity": (ph - pl) / ph if ph > 0 else np.nan,
                        # P2
                        "floor_share": p0 / pl if pl > 0 else np.nan,
                        # P3: same shape as P1 but along the SI axis.
                        "si_sensitivity": (
                            (p_si_hi - p_si_lo) / p_si_hi if p_si_hi > 0 and si_hi > si_lo else np.nan
                        ),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {variant}/{loccode}/{pct}: {exc}")
        if args.verbose and n % 50 == 0:
            print(f"  ...{n}/{len(entries)}")

    df = pd.DataFrame(rows)
    print(f"\nmodels x years evaluated: {len(df):,} "
          f"({df.groupby(['variant','loccode','pct_level']).ngroups} models)")

    print("\n" + "=" * 74)
    print("P1/P2  fleet medians by stand age (P1 should FALL, P2 should RISE)")
    print("=" * 74)
    by_age = df.groupby("stand_age").agg(
        n=("floor", "size"),
        density_sensitivity=("density_sensitivity", "median"),
        floor_share=("floor_share", "median"),
        si_sensitivity=("si_sensitivity", "median"),
    )
    for col in ("density_sensitivity", "floor_share", "si_sensitivity"):
        by_age[col] = (100 * by_age[col]).round(1)
    by_age.columns = ["n_models", "P1 density sens %", "P2 floor share %", "P3 SI sens %"]
    print(by_age.to_string())

    s_age = df.groupby("stand_age")["density_sensitivity"].median()
    f_age = df.groupby("stand_age")["floor_share"].median()
    r1 = spearmanr(s_age.index, s_age.values)
    r2 = spearmanr(f_age.index, f_age.values)
    print(f"\nP1  density sensitivity vs stand age: rho={r1.statistic:+.3f} p={r1.pvalue:.2e}")
    print(f"P2  floor share        vs stand age: rho={r2.statistic:+.3f} p={r2.pvalue:.2e}")
    rr = spearmanr(s_age.values, f_age.values)
    print(f"    the two against each other      : rho={rr.statistic:+.3f} p={rr.pvalue:.2e}")

    print("\n" + "=" * 74)
    print("P3  does explanatory weight shift from density onto site quality?")
    print("=" * 74)
    si_age = df.groupby("stand_age")["si_sensitivity"].median().dropna()
    r3 = spearmanr(si_age.index, si_age.values)
    print(f"in-range SI sensitivity vs stand age: rho={r3.statistic:+.3f} p={r3.pvalue:.2e}")
    print(f"  young (age {si_age.index[0]}): {100*si_age.iloc[0]:.1f}%   "
          f"old (age {si_age.index[-1]}): {100*si_age.iloc[-1]:.1f}%")
    # Age 3 is degenerate: nothing has grown, the surface is ~0 and SI sensitivity
    # goes slightly negative, so anchor on the first age class with a positive one.
    ratio = df.groupby("stand_age").apply(
        lambda g: g["si_sensitivity"].median() / g["density_sensitivity"].median(),
        include_groups=False,
    ).dropna()
    ratio = ratio[ratio > 0]
    rr3 = spearmanr(ratio.index, ratio.values)
    print(f"\nSI-sensitivity / density-sensitivity ratio vs age "
          f"(excluding the degenerate age-3 class): rho={rr3.statistic:+.3f} p={rr3.pvalue:.2e}")
    print(f"  age {ratio.index[0]}: {ratio.iloc[0]:.2f}   age {ratio.index[-1]}: {ratio.iloc[-1]:.2f}   "
          f"({ratio.iloc[-1]/ratio.iloc[0]:.2f}x shift toward site quality)")
    print("  NOTE: SI sensitivity is high at every age (peaks mid-rotation, then eases),")
    print("  so P3 supports the weight-shift story only directionally -- it is the")
    print("  RATIO that moves, driven mostly by density sensitivity falling (P1).")

    print("\n" + "=" * 74)
    print("cross-section at the NPV-relevant horizon (stand age ~40)")
    print("=" * 74)
    mid = df[(df["stand_age"] >= 35) & (df["stand_age"] <= 45)].dropna(
        subset=["density_sensitivity", "floor_share"]
    )
    if len(mid) > 2:
        rho = spearmanr(mid["density_sensitivity"], mid["floor_share"])
        print(f"models with LOWER in-range density sensitivity have HIGHER floor share:")
        print(f"  rho={rho.statistic:+.3f} p={rho.pvalue:.2e}  (n={len(mid):,})")
    print("\nNOTE: this cross-sectional correlation is partly mechanical -- both are")
    print("ratios off the same response surface. The load-bearing evidence is the")
    print("temporal trend (P1, an interpolation quantity) and the SI test (P3).")

    if args.out:
        df.to_csv(args.out, index=False)
        print(f"\nwrote {args.out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="every registered model")
    s.add_argument("--out", help="write per-model CSV here")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("case", help="one variant/loccode in depth")
    s.add_argument("variant")
    s.add_argument("loccode")
    s.add_argument("--pct", default="PCT0")
    s.add_argument("--every", type=int, default=2, help="print every Nth projection year")
    s.set_defaults(func=cmd_case)

    s = sub.add_parser("design", help="recover the training grid from the scaler")
    s.add_argument("variant")
    s.add_argument("loccode")
    s.add_argument("--pct", default="PCT0")
    s.set_defaults(func=cmd_design)

    s = sub.add_parser("costs", help="show planting_cost never reaching the proforma")
    s.add_argument("variant")
    s.add_argument("loccode")
    s.add_argument("--pct", default="PCT0")
    s.set_defaults(func=cmd_costs)

    s = sub.add_parser("mechanism", help="fleet-wide test of why the floor grows with age")
    s.add_argument("--out", help="write per-model-per-year CSV here")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(func=cmd_mechanism)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

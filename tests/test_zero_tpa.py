"""Zero total TPA must produce zero carbon.

The surrogates were trained at ~100-435 total TPA and extrapolate a phantom stand
at 0 (WS_1/503: 22 trees/ac, 69 tons C/ac), which let the breakeven solvers clear
target with nothing planted. A single species at 0 is in-distribution (~half of
training rows), so these pin *total* density only.
"""

import pandas as pd
import pytest

from model_service.model import _carbon_for_inputs
from model_service.tpa_sweep import solve_tpa_range

VARIANT, LOCCODE = "PN", "609"


def _carbon(species_tpa, survival=70.0, si=110.0, pct="PCT0"):
    df, source = _carbon_for_inputs(VARIANT, LOCCODE, survival, si, species_tpa, pct)
    return df, source


def test_zero_total_tpa_gives_zero_carbon():
    df, _ = _carbon([0.0, 0.0, 0.0, 0.0])
    assert (df["ABLD_C"] == 0.0).all()
    assert (df["Annual_ABLD_C"] == 0.0).all()


def test_zero_total_tpa_zeroes_every_metric_not_just_carbon():
    """Callers read BA/TCuFt/Tpa too; leaving those nonzero would be incoherent."""
    df, _ = _carbon([0.0, 0.0, 0.0, 0.0])
    for col in df.columns:
        if col == "Year":
            continue
        assert (df[col] == 0.0).all(), f"{col} not zeroed at zero total TPA"


def test_zero_carbon_holds_across_survival_and_si():
    """The floor was driven by the Survival/SI terms, so vary both."""
    for survival in (50.0, 70.0, 90.0):
        for si in (60.0, 110.0):
            df, _ = _carbon([0.0, 0.0, 0.0, 0.0], survival=survival, si=si)
            assert (df["ABLD_C"] == 0.0).all(), f"nonzero at survival={survival} si={si}"


def test_single_species_zero_is_untouched():
    """A species at 0 with others planted is in-distribution; don't zero it."""
    df, _ = _carbon([60.0, 0.0, 20.0, 20.0])
    assert (df["ABLD_C"] > 0).any()


def test_partial_mix_carbon_is_unchanged_by_the_guard():
    """The guard must not perturb any nonzero-density scenario."""
    mixed, _ = _carbon([60.0, 15.0, 20.0, 20.0])
    assert (mixed["ABLD_C"] > 0).any()
    assert mixed["ABLD_C"].iloc[-1] > mixed["ABLD_C"].iloc[0]


def test_tpa_sweep_no_longer_breaks_even_at_zero_density():
    """The original bug: the feasible range ran down to 0 TPA on large projects."""
    result = solve_tpa_range(
        {
            "variant": VARIANT,
            "loccode": LOCCODE,
            "survival": 70.0,
            "si": 110.0,
            "species_tpa": [60.0, 15.0, 20.0, 20.0],
            "pct_level": "PCT0",
            "net_acres": 50_000.0,
            "protocols": ["ACR"],
            "npv_year": 40,
            "mode": "scalar",
            "target_npv": 0.0,
            "op": ">=",
            "grid": {"lo": 0.0, "hi": 2.0, "steps": 11},
            "include_curve": True,
        }
    )
    res = result["results"][0]
    curve = {round(p["x"], 3): p["npv"] for p in res["curve"]}
    # At zero density there is no carbon, so NPV is just the fixed cost block.
    assert curve[0.0] < 0, "zero density should not clear a $0 NPV target"
    rng = res["range"]
    if rng is not None:
        assert rng["lo"] > 0.0, "breakeven density must be above zero"

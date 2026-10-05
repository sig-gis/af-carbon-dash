"""Upfront costs must reach the proforma.

planting_cost and validation_cost were booked on ``year_start``, a row
compute_carbon_units .diff()s away, so both were silently discarded. Symptom:
zero-density NPV was identical at 1 acre and at 10,000. Both solver paths and
planting design share compute_proforma, so fixing it there covers all three.
"""

import pandas as pd
import pytest

from model_service.model import (
    PROFORMA_YEAR_START,
    _carbon_for_inputs,
    _load_base_json,
    _normalize_financial_params,
    _proforma_for_protocol,
    _solve_acreage_for_metric,
    compute_carbon_units,
    default_scenario,
    run_scenario,
)

VARIANT, LOCCODE, PROTOCOL = "PN", "609", "ACR"


@pytest.fixture(scope="module")
def cu():
    d = default_scenario(VARIANT, LOCCODE)
    df, _ = _carbon_for_inputs(
        VARIANT, LOCCODE, d["survival"], d["si"], d["species_tpa"], "PCT0"
    )
    return compute_carbon_units(df, [PROTOCOL], _load_base_json("protocol_rules.json"))


@pytest.fixture(scope="module")
def fin():
    return _normalize_financial_params([PROTOCOL], None)[PROTOCOL]


def test_planting_cost_reaches_the_proforma(cu, fin):
    df, _ = _proforma_for_protocol(cu, PROTOCOL, fin, 1_000.0, 40)
    assert df["Planting_Cost"].sum() == pytest.approx(fin["planting_cost"] * 1_000.0)


def test_planting_cost_scales_linearly_with_acreage(cu, fin):
    for acres in (100.0, 1_000.0, 10_000.0):
        df, _ = _proforma_for_protocol(cu, PROTOCOL, fin, acres, 40)
        assert df["Planting_Cost"].sum() == pytest.approx(fin["planting_cost"] * acres)


def test_planting_cost_is_charged_once_not_annually(cu, fin):
    df, _ = _proforma_for_protocol(cu, PROTOCOL, fin, 1_000.0, 40)
    assert (df["Planting_Cost"] > 0).sum() == 1


def test_validation_cost_reaches_the_proforma(cu, fin):
    """One-time validation shares a column with recurring verification."""
    df, _ = _proforma_for_protocol(cu, PROTOCOL, fin, 1_000.0, 40)
    first = df["Year"].min()
    charged_first = float(df.loc[df["Year"] == first, "Validation_and_Verification"].iloc[0])
    assert charged_first >= fin["validation_cost"]


def test_upfront_costs_land_on_the_first_row_so_they_are_undiscounted(cu, fin):
    df, _ = _proforma_for_protocol(cu, PROTOCOL, fin, 1_000.0, 40)
    first = df["Year"].min()
    assert first == PROFORMA_YEAR_START + 1  # year_start row is dropped upstream
    assert float(df.loc[df["Year"] == first, "Planting_Cost"].iloc[0]) > 0


def test_acreage_solver_sees_the_planting_cost(cu, fin):
    """Negative per-acre margin must raise, not return a plausible acreage."""
    rich = {**fin, "planting_cost": 10_000_000.0}  # dwarfs any carbon revenue
    with pytest.raises(ValueError):
        _solve_acreage_for_metric(cu, PROTOCOL, rich, 40, 0.0, metric="npv")


def test_zero_density_npv_now_varies_with_acreage():
    """The original symptom: identical NPV at 1 acre and 10,000 acres."""
    d = default_scenario(VARIANT, LOCCODE)
    zero = [0.0] * len(d["species_tpa"])
    small = run_scenario({
        "variant": VARIANT, "loccode": LOCCODE, "species_tpa": zero,
        "net_acres": 1.0, "protocols": [PROTOCOL], "npv_year": 40,
    })["summaries"][0]["npv_yr"]
    large = run_scenario({
        "variant": VARIANT, "loccode": LOCCODE, "species_tpa": zero,
        "net_acres": 10_000.0, "protocols": [PROTOCOL], "npv_year": 40,
    })["summaries"][0]["npv_yr"]
    assert large < small, "planting cost must scale the loss with acreage"

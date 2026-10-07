"""Tests for the Solver view's pure scenario builders (utils.functions.solver).

These are Streamlit-free: they assert the payload shapes sent to /scenario/run,
/scenario/bulk, and /scenario/solve-tpa, including the percent→fraction handling
the UI relies on. The TPA engine itself is covered by tests/test_tpa_sweep.py;
here we also model_validate the payloads against the request schemas so a builder
that drifts from the API contract fails fast.
"""

import pytest

from model_service.schemas import ScenarioRequest, TpaSweepRequest
from utils.functions.solver import (
    _coerce_lever_values,
    _planting_payload,
    _scalar_breakdown_df,
    build_grid_scenarios,
    build_solve_scenario,
    build_tpa_breakeven_scenario,
)

# Rate fields are entered in percent in the UI; the builders convert to fractions.
FIN_PCT = {
    "planting_cost": 500.0,
    "price_per_ert_initial": 25.0,
    "issuance_fee_per_ert": 0.30,
    "discount_rate": 8.0,            # -> 0.08
    "anticipated_inflation": 2.0,    # -> 0.02
    "credit_price_increase": 3.0,    # -> 0.03
}

BASE = dict(
    variant="PN", loccode="609", pct_level="PCT0", survival=70, si=120,
    species_tpa=[60, 15, 20, 20], protocol="ACR", financial_params_pct=FIN_PCT,
    npv_year=40, target_npv=0.0,
)


# ----- build_solve_scenario (acreage) ---------------------------------------


def test_solve_scenario_shape_and_solve_directive():
    p = build_solve_scenario(**BASE)
    assert p["solve"] == {"variable": "net_acres", "target": "npv", "value": 0.0}
    assert "net_acres" not in p  # the solve directive computes it
    assert p["protocols"] == ["ACR"]
    assert p["loccode"] == "609" and isinstance(p["loccode"], str)
    assert all(isinstance(v, float) for v in p["species_tpa"])
    ScenarioRequest.model_validate(p)  # contract check


def test_solve_scenario_percent_to_fraction():
    fp = build_solve_scenario(**BASE)["financial_params"]["ACR"]
    assert fp["discount_rate"] == pytest.approx(0.08)
    assert fp["anticipated_inflation"] == pytest.approx(0.02)
    assert fp["credit_price_increase"] == pytest.approx(0.03)
    # absolute fields untouched
    assert fp["price_per_ert_initial"] == pytest.approx(25.0)


def test_solve_scenario_nonzero_target():
    p = build_solve_scenario(**{**BASE, "target_npv": 250_000})
    assert p["solve"]["value"] == 250_000.0


# ----- build_grid_scenarios (sensitivity sweep) -----------------------------


def test_grid_cross_product_count_and_labels():
    sweep = {"discount_rate": [6.0, 8.0, 10.0], "price_per_ert_initial": [25.0, 45.0]}
    scenarios, cells = build_grid_scenarios(dict(BASE), sweep)
    assert len(scenarios) == len(cells) == 6  # 3 x 2
    assert cells[0] == {"discount_rate": 6.0, "price_per_ert_initial": 25.0}
    # each scenario reflects its cell (discount_rate converted to fraction)
    for scen, cell in zip(scenarios, cells):
        fp = scen["financial_params"]["ACR"]
        assert fp["discount_rate"] == pytest.approx(cell["discount_rate"] / 100.0)
        assert fp["price_per_ert_initial"] == pytest.approx(cell["price_per_ert_initial"])


def test_grid_npv_year_lever_overrides_horizon():
    scenarios, cells = build_grid_scenarios(dict(BASE), {"npv_year": [20, 30, 40]})
    for scen, cell in zip(scenarios, cells):
        assert scen["npv_year"] == cell["npv_year"]


def test_grid_does_not_mutate_base_financials():
    base = dict(BASE)
    build_grid_scenarios(base, {"discount_rate": [6.0, 12.0]})
    assert base["financial_params_pct"]["discount_rate"] == 8.0  # untouched


# ----- _coerce_lever_values (custom sweep values) ---------------------------


def test_coerce_mixes_presets_and_typed_strings():
    # presets come back as floats, typed customs as strings
    assert _coerce_lever_values("discount_rate", [6.0, "7.5", 10.0]) == [6.0, 7.5, 10.0]


def test_coerce_npv_year_to_int():
    assert _coerce_lever_values("npv_year", [20, "25", 30.0]) == [20, 25, 30]
    assert all(isinstance(v, int) for v in _coerce_lever_values("npv_year", ["40"]))


def test_coerce_drops_unparseable_and_dedupes():
    assert _coerce_lever_values("price_per_ert_initial", ["abc", 25.0, "25", ""]) == [25.0]


def test_scalar_breakdown_per_species_and_total():
    df = _scalar_breakdown_df("PN", [60, 15, 20, 20], 0.5)
    assert len(df) == 5  # 4 species + Total row
    assert df.iloc[0]["Breakeven (TPA)"] == pytest.approx(30.0)   # 0.5 * 60
    assert df.iloc[-1]["Species"] == "Total"
    assert df.iloc[-1]["Breakeven (TPA)"] == pytest.approx(57.5)  # 0.5 * 115


# ----- build_tpa_breakeven_scenario (density) -------------------------------


def test_tpa_scenario_scalar_shape():
    p = build_tpa_breakeven_scenario(**BASE, mode="scalar")
    assert p["mode"] == "scalar"
    assert p["op"] == ">="
    assert p["target_npv"] == 0.0
    assert p["include_curve"] is True
    assert "solve" not in p          # TPA endpoint, not the acreage solve directive
    assert "species" not in p        # only for single-species mode
    assert "grid" not in p
    assert p["protocols"] == ["ACR"]
    assert p["financial_params"]["ACR"]["discount_rate"] == pytest.approx(0.08)
    TpaSweepRequest.model_validate(p)


def test_tpa_scenario_species_passthrough():
    p = build_tpa_breakeven_scenario(**BASE, mode="species", species=2)
    assert p["mode"] == "species" and p["species"] == 2
    TpaSweepRequest.model_validate(p)


def test_tpa_scenario_per_species_no_curve():
    p = build_tpa_breakeven_scenario(**BASE, mode="per_species", include_curve=False)
    assert p["mode"] == "per_species" and p["include_curve"] is False
    TpaSweepRequest.model_validate(p)


def test_tpa_scenario_grid_and_op_passthrough():
    grid = {"lo": 10.0, "hi": 50.0, "steps": 5}
    p = build_tpa_breakeven_scenario(**BASE, mode="species", species=0, op="==", grid=grid)
    assert p["op"] == "==" and p["grid"] == grid
    TpaSweepRequest.model_validate(p)


# ----- _planting_payload (Apply to Planting Design) -------------------------


def test_planting_payload_acres_mode():
    p = _planting_payload({**BASE, "tpa_cap": 435}, net_acres=1234)
    assert p["net_acres"] == 1234
    assert p["species_tpa"] == [60, 15, 20, 20]
    assert p["variant"] == "PN" and p["pct_level"] == "PCT0"
    assert p["survival"] == 70 and p["si"] == 120
    assert p["protocol"] == "ACR" and p["npv_year"] == 40
    assert p["planting_cost"] == pytest.approx(500.0)
    assert p["price_per_ert_initial"] == pytest.approx(25.0)


def test_planting_payload_tpa_mode_overrides_mix_without_acres():
    p = _planting_payload({**BASE, "tpa_cap": 435}, species_tpa=[120, 30, 40, 40])
    assert p["species_tpa"] == [120, 30, 40, 40]
    assert "net_acres" not in p


def test_planting_payload_excludes_fixed_financials():
    p = _planting_payload({**BASE, "tpa_cap": 435}, net_acres=1)
    # Planting Design resets fixed financials from protocol presets; only the
    # editable pair carries.
    for fixed in ("discount_rate", "anticipated_inflation", "credit_price_increase",
                  "issuance_fee_per_ert", "tpa_cap", "target_npv", "financial_params_pct"):
        assert fixed not in p

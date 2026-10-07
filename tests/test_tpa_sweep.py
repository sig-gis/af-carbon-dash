"""Tests for the TPA range solver (model_service.tpa_sweep + client wrapper).

Pure interval-extraction logic is tested against synthetic curves (including a
two-sided NPV hump) so correctness doesn't depend on the model. Integration
tests run in-process via LocalBackend's coefficient fallback (no joblib models
needed), so they assert structure/invariants rather than exact NPV values.
"""

import math

import pytest

from model_service.tpa_sweep import _feasible_intervals, solve_tpa_range

VARIANT, LOCCODE = "PN", "609"


# ----- pure interval extraction (synthetic curves) --------------------------


def test_threshold_interpolates_single_crossing():
    xs = [0.0, 1.0, 2.0, 3.0]
    npvs = [0.0, 100.0, 200.0, 300.0]  # strictly increasing
    ivs = _feasible_intervals(xs, npvs, target=150.0, op=">=")
    assert len(ivs) == 1
    # 150 sits halfway between x=1 (100) and x=2 (200) -> 1.5
    assert ivs[0]["lo"] == pytest.approx(1.5)
    assert ivs[0]["lo_clipped"] is False
    assert ivs[0]["hi"] == 3.0 and ivs[0]["hi_clipped"] is True


def test_hump_yields_two_sided_interval():
    # Unimodal hump peaking at x=2; threshold 50 crosses on both flanks.
    xs = [0.0, 1.0, 2.0, 3.0, 4.0]
    npvs = [0.0, 40.0, 100.0, 40.0, 0.0]
    ivs = _feasible_intervals(xs, npvs, target=50.0, op=">=")
    assert len(ivs) == 1
    iv = ivs[0]
    # rising flank: between (1,40) and (2,100) -> 1 + (50-40)/60 = 1.1667
    assert iv["lo"] == pytest.approx(1 + 10 / 60)
    # falling flank: between (2,100) and (3,40) -> 2 + (50-100)/(40-100) = 2.8333
    assert iv["hi"] == pytest.approx(2 + (50 - 100) / (40 - 100))
    assert iv["lo_clipped"] is False and iv["hi_clipped"] is False


def test_all_feasible_clips_both_edges():
    xs = [0.0, 1.0, 2.0]
    npvs = [100.0, 200.0, 300.0]
    ivs = _feasible_intervals(xs, npvs, target=50.0, op=">=")
    assert ivs == [{"lo": 0.0, "hi": 2.0, "lo_clipped": True, "hi_clipped": True}]


def test_none_feasible_returns_empty():
    xs = [0.0, 1.0, 2.0]
    npvs = [10.0, 20.0, 30.0]
    assert _feasible_intervals(xs, npvs, target=1000.0, op=">=") == []


def test_equality_finds_crossing_point():
    xs = [0.0, 1.0, 2.0]
    npvs = [0.0, 100.0, 200.0]
    ivs = _feasible_intervals(xs, npvs, target=150.0, op="==")
    assert len(ivs) == 1
    assert ivs[0]["lo"] == ivs[0]["hi"] == pytest.approx(1.5)


def test_op_le_mirrors_ge():
    xs = [0.0, 1.0, 2.0, 3.0]
    npvs = [0.0, 100.0, 200.0, 300.0]
    ivs = _feasible_intervals(xs, npvs, target=150.0, op="<=")
    assert len(ivs) == 1
    assert ivs[0]["lo"] == 0.0 and ivs[0]["lo_clipped"] is True
    assert ivs[0]["hi"] == pytest.approx(1.5) and ivs[0]["hi_clipped"] is False


# ----- integration via the model (coefficient fallback) ---------------------


def test_scalar_sweep_structure():
    out = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "scalar",
         "target_npv": 600_000, "op": ">="}
    )
    assert out["mode"] == "scalar" and out["metric"] == "total_npv"
    assert len(out["results"]) == 1
    res = out["results"][0]
    assert res["species_index"] is None and res["variable"] == "k"
    assert len(res["curve"]) == 25
    # default grid is 0.25x-4x of k=1
    assert res["curve"][0]["x"] == pytest.approx(0.25)
    assert res["curve"][-1]["x"] == pytest.approx(4.0)
    # NPV should be monotone-ish increasing in the coefficient model
    npvs = [p["npv"] for p in res["curve"]]
    assert npvs[-1] > npvs[0]


def test_per_species_returns_one_result_per_species():
    out = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "per_species",
         "target_npv": 600_000, "include_curve": False}
    )
    n = len(out["base_species_tpa"])
    assert n == len(out["species_codes"]) == len(out["results"]) > 1
    for i, res in enumerate(out["results"]):
        assert res["species_index"] == i
        assert res.get("curve") is None


def test_species_by_index_and_code_agree():
    by_code = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "species",
         "species": "DF", "target_npv": 600_000, "include_curve": False}
    )["results"][0]
    by_index = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "species",
         "species": 0, "target_npv": 600_000, "include_curve": False}
    )["results"][0]
    assert by_code["species_code"] == "DF"
    assert by_code["range"] == by_index["range"]


def test_explicit_absolute_grid_bounds_respected():
    out = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "species", "species": 0,
         "target_npv": 600_000, "grid": {"lo": 10.0, "hi": 50.0, "steps": 5}}
    )
    curve = out["results"][0]["curve"]
    assert len(curve) == 5
    assert curve[0]["x"] == pytest.approx(10.0)
    assert curve[-1]["x"] == pytest.approx(50.0)


def test_grid_max_value_clamps_upper_bound():
    # base DF=60, hi_factor 100 would reach 6000; max_value caps it at 300
    out = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "species", "species": 0,
         "target_npv": 0, "grid": {"hi_factor": 100.0, "max_value": 300.0, "steps": 5}}
    )
    curve = out["results"][0]["curve"]
    assert curve[-1]["x"] == pytest.approx(300.0)


def test_unreachable_target_gives_no_range():
    out = solve_tpa_range(
        {"variant": VARIANT, "loccode": LOCCODE, "mode": "scalar",
         "target_npv": 1e15, "include_curve": False}
    )
    res = out["results"][0]
    assert res["range"] is None and res["intervals"] == []


# ----- validation -----------------------------------------------------------


@pytest.mark.parametrize(
    "patch, msg",
    [
        ({"mode": "bogus"}, "mode must be"),
        ({"op": "!="}, "op must be"),
        ({"mode": "species", "species": None}, "requires a 'species'"),
        ({"mode": "species", "species": 99}, "out of range"),
        ({"mode": "species", "species": "ZZ"}, "not in"),
        ({"target_npv": None}, "target_npv is required"),
    ],
)
def test_validation_errors(patch, msg):
    inputs = {"variant": VARIANT, "loccode": LOCCODE, "mode": "scalar",
              "target_npv": 600_000}
    inputs.update(patch)
    with pytest.raises(ValueError, match=msg):
        solve_tpa_range(inputs)


# ----- client wrapper -------------------------------------------------------


def test_client_box_keys_match_species(monkeypatch):
    from aff_dash_client import AFFDashClient
    from aff_dash_client.backends import LocalBackend

    client = AFFDashClient()
    client._backend = LocalBackend()
    # box() drops infeasible species, so equality needs a target all four can
    # reach. 600_000 stopped qualifying for RC once planting_cost began reaching
    # the proforma; the target is incidental to what's under test (code-keyed,
    # not index-keyed), so lower it rather than weaken the assertion.
    res = client.solve_tpa_range(
        variant=VARIANT, loccode=LOCCODE, target_npv=300_000,
        mode="per_species", include_curve=False,
    )
    box = res.box()
    assert set(box) <= set(res.species_codes)  # keys are codes, never indices
    assert set(box) == set(res.species_codes)
    for lo, hi in box.values():
        assert hi > lo and math.isfinite(lo) and math.isfinite(hi)

"""Trees-per-acre (TPA) sweep / range solver.

NPV is nonlinear in ``species_tpa`` (a unimodal hump: too few trees -> little
carbon; too many -> competition/mortality + planting cost), so unlike the
acreage solver there's no closed-form inverse. We grid-evaluate NPV and read the
feasible range off the curve, recovering both edges of the hump.

See ``solve_tpa_range`` for the inputs/modes and the returned shape.
"""

from __future__ import annotations

from typing import Any

from model_service.model import default_scenario, run_scenario

DEFAULT_LO_FACTOR = 0.25
DEFAULT_HI_FACTOR = 4.0
DEFAULT_STEPS = 25

_VALID_OPS = (">=", "<=", "==")
_VALID_MODES = ("scalar", "species", "per_species")

# Base scenario fields forwarded to run_scenario for each grid evaluation.
_SCENARIO_FIELDS = (
    "survival",
    "si",
    "pct_level",
    "net_acres",
    "protocols",
    "financial_params",
    "npv_year",
)


def solve_tpa_range(inputs: dict) -> dict:
    """Sweep species_tpa and return the feasible TPA range(s).

    ``inputs`` extends the ScenarioRequest fields with:
      mode        : "scalar" | "species" | "per_species"  (default "scalar")
      species     : int index or species code; required for mode="species"
      target_npv  : float (required); the total-NPV hurdle
      op          : ">=" | "<=" | "=="  (default ">=")
      grid        : optional {"lo_factor","hi_factor","steps"} or
                    {"lo","hi","steps"} (explicit absolute bounds)
      include_curve : bool (default True); return the full swept curve

    Returns a dict matching TpaSweepResponse.
    """
    mode = inputs.get("mode", "scalar")
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {_VALID_MODES}; got {mode!r}")

    op = inputs.get("op", ">=")
    if op not in _VALID_OPS:
        raise ValueError(f"op must be one of {_VALID_OPS}; got {op!r}")

    if inputs.get("target_npv") is None:
        raise ValueError("target_npv is required")
    target = float(inputs["target_npv"])
    include_curve = bool(inputs.get("include_curve", True))

    # Resolve the base scenario so we have the base mix + species codes even
    # when the caller didn't pass them explicitly.
    defaults = default_scenario(inputs["variant"], inputs["loccode"])
    base_tpa = [
        float(x) for x in (inputs.get("species_tpa") or defaults["species_tpa"])
    ]
    species_codes = list(defaults["species_codes"])
    if len(species_codes) < len(base_tpa):  # pad if registry slot count lags
        species_codes += [""] * (len(base_tpa) - len(species_codes))

    grid_cfg = inputs.get("grid") or {}

    if mode == "scalar":
        results = [_sweep_scalar(inputs, base_tpa, target, op, grid_cfg, include_curve)]
    elif mode == "species":
        idx = _resolve_species_index(inputs.get("species"), species_codes, base_tpa)
        results = [
            _sweep_species(
                inputs,
                base_tpa,
                idx,
                species_codes,
                target,
                op,
                grid_cfg,
                include_curve,
            )
        ]
    else:  # per_species
        results = [
            _sweep_species(
                inputs,
                base_tpa,
                idx,
                species_codes,
                target,
                op,
                grid_cfg,
                include_curve,
            )
            for idx in range(len(base_tpa))
        ]

    return {
        "mode": mode,
        "op": op,
        "target_npv": target,
        "metric": "total_npv",
        "base_species_tpa": base_tpa,
        "species_codes": species_codes,
        "results": results,
    }


# ----- per-mode sweeps ------------------------------------------------------


def _sweep_scalar(
    inputs: dict,
    base_tpa: list[float],
    target: float,
    op: str,
    grid_cfg: dict,
    include_curve: bool,
) -> dict:
    """Sweep a multiplier k on the whole mix; x-axis is k (k=1 is the base)."""
    lo, hi, steps = _grid_bounds(grid_cfg, base_value=1.0)
    xs = _linspace(lo, hi, steps)
    npvs = [_eval_npv(inputs, [k * t for t in base_tpa]) for k in xs]
    return _build_result(
        species_index=None,
        species_code=None,
        variable="k",
        xs=xs,
        npvs=npvs,
        species_tpas=[[k * t for t in base_tpa] for k in xs],
        target=target,
        op=op,
        include_curve=include_curve,
    )


def _sweep_species(
    inputs: dict,
    base_tpa: list[float],
    idx: int,
    species_codes: list[str],
    target: float,
    op: str,
    grid_cfg: dict,
    include_curve: bool,
) -> dict:
    """Sweep one species' TPA, holding the others fixed; x-axis is that TPA."""
    lo, hi, steps = _grid_bounds(grid_cfg, base_value=base_tpa[idx])
    xs = _linspace(lo, hi, steps)
    species_tpas = []
    for v in xs:
        tpa = list(base_tpa)
        tpa[idx] = v
        species_tpas.append(tpa)
    npvs = [_eval_npv(inputs, tpa) for tpa in species_tpas]
    return _build_result(
        species_index=idx,
        species_code=species_codes[idx] if idx < len(species_codes) else None,
        variable="tpa",
        xs=xs,
        npvs=npvs,
        species_tpas=species_tpas,
        target=target,
        op=op,
        include_curve=include_curve,
    )


# ----- evaluation -----------------------------------------------------------


def _eval_npv(inputs: dict, species_tpa: list[float]) -> float:
    """Total NPV (summed over protocols) for the scenario at this species_tpa."""
    payload: dict[str, Any] = {
        "variant": inputs["variant"],
        "loccode": inputs["loccode"],
    }
    for field in _SCENARIO_FIELDS:
        if inputs.get(field) is not None:
            payload[field] = inputs[field]
    payload["species_tpa"] = list(species_tpa)
    result = run_scenario(payload)
    return float(sum(s["npv_yr"] for s in result["summaries"]))


# ----- range extraction -----------------------------------------------------


def _build_result(
    *,
    species_index: int | None,
    species_code: str | None,
    variable: str,
    xs: list[float],
    npvs: list[float],
    species_tpas: list[list[float]],
    target: float,
    op: str,
    include_curve: bool,
) -> dict:
    intervals = _feasible_intervals(xs, npvs, target, op)
    bounding = _bounding_range(intervals)
    result = {
        "species_index": species_index,
        "species_code": species_code,
        "variable": variable,
        "range": bounding,
        "intervals": intervals,
    }
    if include_curve:
        result["curve"] = [
            {"x": x, "npv": npv, "species_tpa": tpa}
            for x, npv, tpa in zip(xs, npvs, species_tpas)
        ]
    return result


def _feasible_intervals(
    xs: list[float], npvs: list[float], target: float, op: str
) -> list[dict]:
    """Maximal runs of the grid where ``npv op target`` holds.

    Edges are linear-interpolated at the crossing between adjacent grid points.
    For "==" each sign change of (npv - target) yields a zero-width interval at
    the interpolated crossing. ``lo_clipped`` / ``hi_clipped`` mark a feasible
    region that runs off the swept range (true edge lies beyond the grid).
    """
    if op == "==":
        return _equality_crossings(xs, npvs, target)

    feasible = [_satisfies(v, target, op) for v in npvs]
    intervals: list[dict] = []
    i = 0
    n = len(xs)
    while i < n:
        if not feasible[i]:
            i += 1
            continue
        start = i
        while i + 1 < n and feasible[i + 1]:
            i += 1
        end = i  # inclusive run [start, end] of feasible points

        if start == 0:
            lo, lo_clipped = xs[0], True
        else:
            lo, lo_clipped = _interp_x(xs, npvs, start - 1, start, target), False
        if end == n - 1:
            hi, hi_clipped = xs[-1], True
        else:
            hi, hi_clipped = _interp_x(xs, npvs, end, end + 1, target), False

        intervals.append(
            {"lo": lo, "hi": hi, "lo_clipped": lo_clipped, "hi_clipped": hi_clipped}
        )
        i += 1
    return intervals


def _equality_crossings(
    xs: list[float], npvs: list[float], target: float
) -> list[dict]:
    crossings: list[dict] = []
    for i in range(len(xs) - 1):
        a, b = npvs[i] - target, npvs[i + 1] - target
        if a == 0.0:
            crossings.append(_point_interval(xs[i]))
        if (a < 0) != (b < 0) and a != 0 and b != 0:
            x = _interp_x(xs, npvs, i, i + 1, target)
            crossings.append(_point_interval(x))
    if npvs and npvs[-1] - target == 0.0:
        crossings.append(_point_interval(xs[-1]))
    return crossings


def _point_interval(x: float) -> dict:
    return {"lo": x, "hi": x, "lo_clipped": False, "hi_clipped": False}


def _bounding_range(intervals: list[dict]) -> dict | None:
    """Outer [min,max] over all feasible intervals. The box for a Q2 optimizer."""
    if not intervals:
        return None
    lo = min(iv["lo"] for iv in intervals)
    hi = max(iv["hi"] for iv in intervals)
    return {
        "lo": lo,
        "hi": hi,
        "lo_clipped": any(iv["lo_clipped"] for iv in intervals if iv["lo"] == lo),
        "hi_clipped": any(iv["hi_clipped"] for iv in intervals if iv["hi"] == hi),
    }


# ----- helpers --------------------------------------------------------------


def _satisfies(value: float, target: float, op: str) -> bool:
    if op == ">=":
        return value >= target
    if op == "<=":
        return value <= target
    return value == target


def _interp_x(
    xs: list[float], npvs: list[float], i: int, j: int, target: float
) -> float:
    """Linear-interpolate the x where npv crosses target between points i and j."""
    x0, x1 = xs[i], xs[j]
    y0, y1 = npvs[i], npvs[j]
    if y1 == y0:
        return x0
    return x0 + (target - y0) * (x1 - x0) / (y1 - y0)


def _grid_bounds(grid_cfg: dict, base_value: float) -> tuple[float, float, int]:
    steps = int(grid_cfg.get("steps", DEFAULT_STEPS))
    if steps < 2:
        raise ValueError("grid.steps must be >= 2")
    abs_lo, abs_hi = grid_cfg.get("lo"), grid_cfg.get("hi")
    if abs_lo is not None or abs_hi is not None:
        lo = float(abs_lo) if abs_lo is not None else base_value * DEFAULT_LO_FACTOR
        hi = float(abs_hi) if abs_hi is not None else base_value * DEFAULT_HI_FACTOR
    else:
        lo_factor = float(grid_cfg.get("lo_factor") or DEFAULT_LO_FACTOR)
        hi_factor = float(grid_cfg.get("hi_factor") or DEFAULT_HI_FACTOR)
        lo, hi = base_value * lo_factor, base_value * hi_factor
    max_value = grid_cfg.get("max_value")
    if max_value is not None:
        hi = min(hi, float(max_value))  # never sweep past the model's valid range
    if hi <= lo:
        raise ValueError(f"grid hi ({hi}) must be greater than lo ({lo})")
    return lo, hi, steps


def _linspace(lo: float, hi: float, steps: int) -> list[float]:
    span = hi - lo
    return [lo + span * i / (steps - 1) for i in range(steps)]


def _resolve_species_index(
    species: Any, species_codes: list[str], base_tpa: list[float]
) -> int:
    """Resolve a species selector (int index or str code) to a list index."""
    if species is None:
        raise ValueError("mode='species' requires a 'species' index or code")
    if isinstance(species, bool):  # bool is an int subclass; reject explicitly
        raise ValueError(f"invalid species selector: {species!r}")
    if isinstance(species, int):
        if not 0 <= species < len(base_tpa):
            raise ValueError(
                f"species index {species} out of range 0..{len(base_tpa) - 1}"
            )
        return species
    if isinstance(species, str):
        for i, code in enumerate(species_codes):
            if code == species:
                return i
        raise ValueError(f"species code {species!r} not in {species_codes}")
    raise ValueError(
        f"species must be an int index or str code; got {type(species).__name__}"
    )

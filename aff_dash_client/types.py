from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ScenarioSummary:
    protocol: str
    net_acres: float
    total_net: float
    npv_yr: float
    npv_year: int
    npv_per_acre: float

    @classmethod
    def from_api(cls, row: dict) -> "ScenarioSummary":
        return cls(
            protocol=row["Protocol"],
            net_acres=float(row["net_acres"]),
            total_net=float(row["total_net"]),
            npv_yr=float(row["npv_yr"]),
            npv_year=int(row["npv_year"]),
            npv_per_acre=float(row["npv_per_acre"]),
        )

    def as_dict(self) -> dict:
        return {
            "protocol": self.protocol,
            "net_acres": self.net_acres,
            "total_net": self.total_net,
            "npv_yr": self.npv_yr,
            "npv_year": self.npv_year,
            "npv_per_acre": self.npv_per_acre,
        }


@dataclass
class ScenarioResult:
    """Result of one scenario evaluation.

    ``summaries`` is one entry per protocol. For typical AFF use (single
    protocol, possibly with a solve directive), use the ``acreage``, ``tnr``,
    and ``npv`` convenience properties.
    """

    inputs: dict[str, Any]
    summaries: list[ScenarioSummary]
    model_source: str
    proforma_df: pd.DataFrame | None = None
    carbon_df: pd.DataFrame | None = None
    cu_df: pd.DataFrame | None = None

    @classmethod
    def from_api(cls, payload: dict) -> "ScenarioResult":
        return cls(
            inputs=payload["inputs"],
            summaries=[ScenarioSummary.from_api(s) for s in payload["summaries"]],
            model_source=payload.get("model_source", ""),
            proforma_df=_rows_to_df(payload.get("proforma_rows")),
            carbon_df=_rows_to_df(payload.get("carbon_rows")),
            cu_df=_rows_to_df(payload.get("cu_rows")),
        )

    @property
    def acreage(self) -> float:
        return float(self.inputs["net_acres"])

    @property
    def tnr(self) -> dict[str, float]:
        return {s.protocol: s.total_net for s in self.summaries}

    @property
    def npv(self) -> dict[str, float]:
        return {s.protocol: s.npv_yr for s in self.summaries}

    @property
    def npv_per_acre(self) -> dict[str, float]:
        return {s.protocol: s.npv_per_acre for s in self.summaries}

    def as_dict(self) -> dict:
        out = {
            "inputs": self.inputs,
            "summaries": [s.as_dict() for s in self.summaries],
            "model_source": self.model_source,
        }
        return out


@dataclass
class TpaInterval:
    lo: float
    hi: float
    lo_clipped: bool  # feasible region runs off the low edge of the swept grid
    hi_clipped: bool  # ...off the high edge

    @classmethod
    def from_api(cls, d: dict) -> "TpaInterval":
        return cls(
            lo=float(d["lo"]),
            hi=float(d["hi"]),
            lo_clipped=bool(d["lo_clipped"]),
            hi_clipped=bool(d["hi_clipped"]),
        )

    def as_tuple(self) -> tuple[float, float]:
        return (self.lo, self.hi)


@dataclass
class TpaRangeResult:
    """Feasible TPA range for one swept dimension (a species, or the mix multiplier)."""

    species_index: int | None  # required for per-species and fixed-species modes
    species_code: str | None
    variable: str  # "k" for mix multiplier, "tpa" for species TPA
    range: TpaInterval | None  # outer min/max box; None if nothing feasible
    intervals: list[TpaInterval]  # feasible region(s)
    curve: pd.DataFrame | None = None

    @classmethod
    def from_api(cls, d: dict) -> "TpaRangeResult":
        rng = d.get("range")
        return cls(
            species_index=d.get("species_index"),
            species_code=d.get("species_code"),
            variable=d["variable"],
            range=TpaInterval.from_api(rng) if rng else None,
            intervals=[TpaInterval.from_api(iv) for iv in d.get("intervals", [])],
            curve=_rows_to_df(d.get("curve")),
        )


@dataclass
class TpaSweepResult:
    """Result of a ``solve_tpa_range`` call.

    ``results`` is one entry per swept dimension: a single entry for ``scalar``
    and ``species`` modes, one per species for ``per_species``. Use ``box()``
    to get the ``{species_code: (lo, hi)}`` mapping that seeds a Q2 optimizer.
    """

    mode: str
    op: str
    target_npv: float
    metric: str
    base_species_tpa: list[float]
    species_codes: list[str]
    results: list[TpaRangeResult]

    @classmethod
    def from_api(cls, payload: dict) -> "TpaSweepResult":
        return cls(
            mode=payload["mode"],
            op=payload["op"],
            target_npv=float(payload["target_npv"]),
            metric=payload.get("metric", ""),
            base_species_tpa=[float(x) for x in payload["base_species_tpa"]],
            species_codes=list(payload["species_codes"]),
            results=[TpaRangeResult.from_api(r) for r in payload["results"]],
        )

    def box(self) -> dict[str, tuple[float, float]]:
        """Per-species ``(lo, hi)`` feasible TPA bounds, keyed by species code.

        Only meaningful for ``per_species`` mode. A non-binding species (feasible
        across the whole grid) shows up at the grid edges; check its
        ``range.lo_clipped``/``hi_clipped`` to tell.
        """
        out: dict[str, tuple[float, float]] = {}
        for r in self.results:
            if r.range is None:
                continue
            key = r.species_code or f"SP{(r.species_index or 0) + 1}"
            out[key] = r.range.as_tuple()
        return out


@dataclass
class Defaults:
    """Defaults for a (variant, loccode) pair, ready to feed into ``run``."""

    variant: str
    loccode: str
    survival: float
    si: float
    species_tpa: list[float]
    species_codes: list[str]
    pct_level: str
    net_acres: float
    protocols: list[str]
    financial_params: dict[str, dict[str, float]]
    npv_year: int

    @classmethod
    def from_api(cls, payload: dict) -> "Defaults":
        return cls(**payload)

    def as_dict(self) -> dict:
        return {
            "variant": self.variant,
            "loccode": self.loccode,
            "survival": self.survival,
            "si": self.si,
            "species_tpa": list(self.species_tpa),
            "species_codes": list(self.species_codes),
            "pct_level": self.pct_level,
            "net_acres": self.net_acres,
            "protocols": list(self.protocols),
            "financial_params": {k: dict(v) for k, v in self.financial_params.items()},
            "npv_year": self.npv_year,
        }

    def with_overrides(self, **kwargs: Any) -> dict:
        """Merge keyword overrides on top of the defaults and return a dict
        suitable for ``AFFDashClient.run(**...)``.

        ``species_codes`` is informational only and is dropped from the result
        since it isn't a request field.
        """
        merged = self.as_dict()
        merged.pop("species_codes", None)
        for key, value in kwargs.items():
            merged[key] = value
        return merged


def _rows_to_df(rows: list[dict] | None) -> pd.DataFrame | None:
    if not rows:
        return None
    return pd.DataFrame(rows)

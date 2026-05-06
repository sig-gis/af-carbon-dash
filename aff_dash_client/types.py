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

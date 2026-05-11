"""High-level client for AFF scenario evaluation."""

from __future__ import annotations

import os
from typing import Any

from aff_dash_client.backends import HTTPBackend, LocalBackend
from aff_dash_client.types import Defaults, ScenarioResult

DEFAULT_API_URL = "https://model-service-api-dev-526758851260.us-west1.run.app"


class AFFDashClient:
    """Client for AFF carbon scenario evaluation.

    By default, calls the deployed dev API. Override the URL with the
    ``api_base_url`` argument or the ``CARBON_API_BASE_URL`` env var. To run
    in-process against local model files, pass ``local_models_dir=<path>``.

    Examples
    --------
    Hit the deployed API::

        client = AFFDashClient()
        result = client.solve_for_tnr(
            variant="PN", loccode="609", target_tnr=500_000, npv_year=40,
        )
        print(result.acreage, result.tnr, result.npv)

    Run against a local API server::

        os.environ["CARBON_API_BASE_URL"] = "http://localhost:8001"
        client = AFFDashClient()

    Run in-process against local joblib models::

        client = AFFDashClient(local_models_dir="./data/models")
    """

    def __init__(
        self,
        api_base_url: str | None = None,
        *,
        local_models_dir: str | os.PathLike | None = None,
        timeout: float = 60.0,
    ) -> None:
        if local_models_dir is not None:
            self._backend = LocalBackend(local_models_dir)
        else:
            url = api_base_url or os.environ.get("CARBON_API_BASE_URL") or DEFAULT_API_URL
            self._backend = HTTPBackend(url, timeout=timeout)

    # ----- public API -------------------------------------------------------

    def defaults(self, variant: str, loccode: str) -> Defaults:
        """Fetch the authoritative defaults dict for a (variant, loccode) pair."""
        return Defaults.from_api(self._backend.defaults(variant, loccode))

    def run(
        self,
        *,
        variant: str,
        loccode: str,
        survival: float | None = None,
        si: float | None = None,
        species_tpa: list[float] | None = None,
        pct_level: str | None = None,
        net_acres: float | None = None,
        protocols: list[str] | None = None,
        financial_params: dict[str, dict[str, float]] | None = None,
        npv_year: int | None = None,
        return_dataframes: bool = False,
    ) -> ScenarioResult:
        """Evaluate one scenario at a fixed acreage.

        Any field left ``None`` is filled with the default for the given
        (variant, loccode). ``net_acres`` falls back to the default 1000 acres
        unless overridden.
        """
        payload = self._build_payload(
            variant=variant, loccode=loccode, survival=survival, si=si,
            species_tpa=species_tpa, pct_level=pct_level, net_acres=net_acres,
            protocols=protocols, financial_params=financial_params,
            npv_year=npv_year, return_dataframes=return_dataframes,
        )
        return ScenarioResult.from_api(self._backend.run(payload))

    def solve_for_tnr(
        self,
        *,
        variant: str,
        loccode: str,
        target_tnr: float,
        survival: float | None = None,
        si: float | None = None,
        species_tpa: list[float] | None = None,
        pct_level: str | None = None,
        protocols: list[str] | None = None,
        financial_params: dict[str, dict[str, float]] | None = None,
        npv_year: int | None = None,
        return_dataframes: bool = False,
    ) -> ScenarioResult:
        """Find the net_acres value that produces the requested Total Net Revenue.

        Single-protocol only — TNR is linear in acres for a fixed protocol, so
        the server solves it in closed form. If multiple protocols are passed,
        the server raises 400.
        """
        payload = self._build_payload(
            variant=variant, loccode=loccode, survival=survival, si=si,
            species_tpa=species_tpa, pct_level=pct_level, net_acres=None,
            protocols=protocols, financial_params=financial_params,
            npv_year=npv_year, return_dataframes=return_dataframes,
        )
        payload["solve"] = {
            "variable": "net_acres",
            "target": "tnr",
            "value": float(target_tnr),
        }
        return ScenarioResult.from_api(self._backend.run(payload))

    def solve_for_npv(
        self,
        *,
        variant: str,
        loccode: str,
        target_npv: float,
        survival: float | None = None,
        si: float | None = None,
        species_tpa: list[float] | None = None,
        pct_level: str | None = None,
        protocols: list[str] | None = None,
        financial_params: dict[str, dict[str, float]] | None = None,
        npv_year: int | None = None,
        return_dataframes: bool = False,
    ) -> ScenarioResult:
        """Find the net_acres value that produces the requested NPV at npv_year.

        Single-protocol only — NPV is linear in acres for a fixed protocol,
        fixed financial params, and fixed horizon, so the server solves it in
        closed form. ``npv_year`` is the year horizon the target applies to;
        defaults to the server-side default (40) if omitted. To target NPV
        under a different discount rate or carbon price, pass those via
        ``financial_params``.
        """
        payload = self._build_payload(
            variant=variant, loccode=loccode, survival=survival, si=si,
            species_tpa=species_tpa, pct_level=pct_level, net_acres=None,
            protocols=protocols, financial_params=financial_params,
            npv_year=npv_year, return_dataframes=return_dataframes,
        )
        payload["solve"] = {
            "variable": "net_acres",
            "target": "npv",
            "value": float(target_npv),
        }
        return ScenarioResult.from_api(self._backend.run(payload))

    # ----- internals --------------------------------------------------------

    def _build_payload(self, **kwargs: Any) -> dict:
        payload = {k: v for k, v in kwargs.items() if v is not None}
        payload["variant"] = kwargs["variant"]
        payload["loccode"] = kwargs["loccode"]
        return payload

"""Programmatic client for the AF Carbon Dashboard model service.

Quick start:

    from aff_dash_client import AFFDashClient

    client = AFFDashClient()  # hits the deployed dev API by default

    # Single scenario at fixed acreage
    result = client.run(variant="PN", loccode="609", net_acres=1000)
    print(result.tnr, result.npv)

    # Solver: find the acreage that produces a target Total Net Revenue
    result = client.solve_for_tnr(
        variant="PN", loccode="609", target_tnr=500_000, npv_year=40,
    )
    print(result.acreage, result.npv)

Set ``CARBON_API_BASE_URL`` to override the default API URL, or pass
``local_models_dir=...`` to evaluate scenarios in-process against a local
joblib model directory.
"""

from aff_dash_client.client import AFFDashClient
from aff_dash_client.types import (
    Defaults,
    ScenarioResult,
    ScenarioSummary,
    TpaInterval,
    TpaRangeResult,
    TpaSweepResult,
)

__all__ = [
    "AFFDashClient",
    "Defaults",
    "ScenarioResult",
    "ScenarioSummary",
    "TpaInterval",
    "TpaRangeResult",
    "TpaSweepResult",
]

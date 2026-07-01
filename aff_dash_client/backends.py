"""Backends for AFFDashClient.

HTTPBackend talks to a deployed (or locally-running) FastAPI service.
LocalBackend imports the service code and evaluates scenarios in-process,
optionally pointed at a custom local-models directory via MODEL_STORE_PATH.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import requests


class _Backend(Protocol):
    def defaults(self, variant: str, loccode: str) -> dict: ...
    def run(self, payload: dict) -> dict: ...
    def run_bulk(self, payload: dict) -> dict: ...
    def solve_tpa(self, payload: dict) -> dict: ...


class HTTPBackend:
    """Backend that calls /scenario/run and /scenario/defaults over HTTP."""

    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def defaults(self, variant: str, loccode: str) -> dict:
        resp = requests.get(
            f"{self.base_url}/scenario/defaults",
            params={"variant": variant, "loccode": loccode},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def run(self, payload: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}/scenario/run",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def run_bulk(self, payload: dict, *, timeout: float | None = None) -> dict:
        resp = requests.post(
            f"{self.base_url}/scenario/bulk",
            json=payload,
            timeout=timeout if timeout is not None else max(self.timeout, 300.0),
        )
        resp.raise_for_status()
        return resp.json()

    def solve_tpa(self, payload: dict, *, timeout: float | None = None) -> dict:
        resp = requests.post(
            f"{self.base_url}/scenario/solve-tpa",
            json=payload,
            timeout=timeout if timeout is not None else max(self.timeout, 300.0),
        )
        resp.raise_for_status()
        return resp.json()


class LocalBackend:
    """Backend that runs scenarios in-process by importing model_service.

    If ``models_dir`` is given, it overrides where joblib model files are
    loaded from (sets MODEL_STORE_PATH). Useful for testing locally with a
    custom directory of models without spinning up the FastAPI server.
    """

    def __init__(self, models_dir: str | os.PathLike | None = None) -> None:
        os.environ["MODEL_STORE_BACKEND"] = "local"
        if models_dir is not None:
            os.environ["MODEL_STORE_PATH"] = os.fspath(models_dir)

        # Reset cached store + model collections so env changes take effect.
        try:
            from model_service.store import get_store
            get_store.cache_clear()
        except Exception:
            pass
        try:
            from model_service.model import get_fvs_models
            get_fvs_models.cache_clear()
        except Exception:
            pass

    def defaults(self, variant: str, loccode: str) -> dict:
        from model_service.model import default_scenario
        return default_scenario(variant, loccode)

    def run(self, payload: dict) -> dict:
        from model_service.model import run_scenario
        return run_scenario(payload)

    def run_bulk(self, payload: dict, *, timeout: float | None = None) -> dict:
        from model_service.main import scenario_bulk
        from model_service.schemas import BulkScenarioRequest, BulkScenarioResponse
        req = BulkScenarioRequest(scenarios=payload.get("scenarios", []))
        raw = scenario_bulk(req)
        return BulkScenarioResponse.model_validate(raw).model_dump()

    def solve_tpa(self, payload: dict, *, timeout: float | None = None) -> dict:
        from model_service.schemas import TpaSweepRequest, TpaSweepResponse
        from model_service.tpa_sweep import solve_tpa_range
        req = TpaSweepRequest.model_validate(payload)
        raw = solve_tpa_range(req.model_dump(exclude_none=False))
        return TpaSweepResponse.model_validate(raw).model_dump()

"""Tests for the model service's machine-to-machine bearer-key auth.

Streamlit- and scipy-free: builds a minimal FastAPI app around
model_service.auth rather than importing model_service.main, and substitutes
an in-memory store for the model store.
"""

import json

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from model_service import auth
from model_service import store as store_mod

KEYS = {
    "sig-dashboard": {"keys": ["admin-key"], "role": "admin"},
    "af-dashboard": {"keys": ["af-key", "af-key-next"], "role": "client"},
    "script": "bare-key",
}


class MemoryStore:
    """Just enough of the ModelStore protocol for api_keys.json."""

    def __init__(self, docs: dict | None = None):
        self.docs = dict(docs or {})
        self.writes = 0

    def get_json(self, key):
        if key not in self.docs:
            raise FileNotFoundError(key)
        return json.loads(json.dumps(self.docs[key]))

    def put_json(self, data, key):
        self.writes += 1
        self.docs[key] = json.loads(json.dumps(data))


@pytest.fixture
def store(monkeypatch):
    """Route model_service.store.get_store() to an in-memory store."""
    mem = MemoryStore()
    monkeypatch.setattr(store_mod, "get_store", lambda: mem)
    monkeypatch.delenv(auth.ENV_VAR, raising=False)
    monkeypatch.delenv(auth.DISABLE_VAR, raising=False)
    monkeypatch.setenv("ENV", "local")
    auth.reset_cache()
    yield mem
    auth.reset_cache()


def make_app() -> TestClient:
    app = FastAPI(dependencies=[Depends(auth.require_client)])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/whoami")
    def whoami(client: auth.Client = Depends(auth.require_client)):
        return {"name": client.name, "role": client.role}

    @app.post("/admin", dependencies=[Depends(auth.require_admin)])
    def admin():
        return {"ok": True}

    return TestClient(app)


@pytest.fixture
def client(store):
    store.docs[auth.STORE_KEY] = KEYS
    return make_app()


def bearer(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# --- request authentication ------------------------------------------------


def test_missing_key_is_401(client):
    r = client.get("/whoami")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_wrong_key_is_401(client):
    assert client.get("/whoami", headers=bearer("nope")).status_code == 401


def test_valid_key_identifies_client(client):
    assert client.get("/whoami", headers=bearer("af-key")).json() == {
        "name": "af-dashboard",
        "role": "client",
    }


def test_rotating_key_also_works(client):
    assert client.get("/whoami", headers=bearer("af-key-next")).json()["name"] == "af-dashboard"


def test_bare_string_is_client_role(client):
    assert client.get("/whoami", headers=bearer("bare-key")).json() == {
        "name": "script",
        "role": "client",
    }


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_non_bearer_scheme_is_rejected(client):
    r = client.get("/whoami", headers={"Authorization": "Basic YWY6a2V5"})
    assert r.status_code == 401


# --- roles -----------------------------------------------------------------


def test_client_role_cannot_hit_admin(client):
    assert client.post("/admin", headers=bearer("af-key")).status_code == 403


def test_admin_role_can_hit_admin(client):
    assert client.post("/admin", headers=bearer("admin-key")).status_code == 200


def test_admin_requires_auth_first(client):
    assert client.post("/admin").status_code == 401


# --- store provisioning ------------------------------------------------------


def test_missing_file_is_provisioned_with_dashboard_admin_key(store):
    doc = auth.ensure_store_keys(store)
    assert store.writes == 1
    entry = doc[auth.DASHBOARD_CLIENT]
    assert entry["role"] == "admin"
    assert len(entry["keys"]) == 1 and len(entry["keys"][0]) >= 32


def test_existing_file_is_not_rewritten(store):
    store.docs[auth.STORE_KEY] = KEYS
    assert auth.ensure_store_keys(store) == KEYS
    assert store.writes == 0


def test_service_and_dashboard_agree_on_provisioned_key(store):
    """Whoever provisions first, both sides read the same key back."""
    from utils.config import get_api_key

    doc = auth.ensure_store_keys(store)  # "service" starts first
    assert get_api_key() == doc[auth.DASHBOARD_CLIENT]["keys"][0]
    c = make_app()
    assert c.get("/whoami", headers=bearer(get_api_key())).json()["name"] == auth.DASHBOARD_CLIENT


def test_dashboard_env_key_overrides_store(store, monkeypatch):
    from utils.config import get_api_key

    monkeypatch.setenv("CARBON_API_KEY", "from-env")
    assert get_api_key() == "from-env"


def test_new_client_in_store_is_picked_up_without_restart(client, store, monkeypatch):
    assert client.get("/whoami", headers=bearer("late-key")).status_code == 401
    store.docs[auth.STORE_KEY] = {**KEYS, "late": "late-key"}
    monkeypatch.setattr(auth, "_REFRESH_INTERVAL", 0.0)
    assert client.get("/whoami", headers=bearer("late-key")).json()["name"] == "late"


def test_refresh_is_throttled(client, store):
    assert client.get("/whoami", headers=bearer("admin-key")).status_code == 200  # warm
    store.docs[auth.STORE_KEY] = {**KEYS, "late": "late-key"}
    # Loaded < _REFRESH_INTERVAL ago, so the unknown key does not trigger a re-read.
    assert client.get("/whoami", headers=bearer("late-key")).status_code == 401


def test_revoked_key_is_rejected_after_max_age(client, store, monkeypatch):
    assert client.get("/whoami", headers=bearer("af-key")).status_code == 200  # warm
    store.docs[auth.STORE_KEY] = {k: v for k, v in KEYS.items() if k != "af-dashboard"}
    # Still cached: nothing unknown was presented and the set is fresh.
    assert client.get("/whoami", headers=bearer("af-key")).status_code == 200
    monkeypatch.setattr(auth, "_MAX_AGE", 0.0)
    monkeypatch.setattr(auth, "_REFRESH_INTERVAL", 0.0)
    assert client.get("/whoami", headers=bearer("af-key")).status_code == 401


def test_broken_store_on_refresh_keeps_last_good_keys(client, store, monkeypatch):
    monkeypatch.setattr(auth, "_REFRESH_INTERVAL", 0.0)
    assert client.get("/whoami", headers=bearer("admin-key")).status_code == 200  # warm

    def boom(key):
        raise RuntimeError("store down")

    store.get_json = boom
    assert client.get("/whoami", headers=bearer("nope")).status_code == 401
    assert client.get("/whoami", headers=bearer("af-key")).status_code == 200


# --- env override and disable flag ---------------------------------------------


def test_env_var_overrides_store(store, monkeypatch):
    store.docs[auth.STORE_KEY] = KEYS
    monkeypatch.setenv(auth.ENV_VAR, json.dumps({"only": "env-key"}))
    auth.reset_cache()
    c = make_app()
    assert c.get("/whoami", headers=bearer("env-key")).json()["name"] == "only"
    assert c.get("/whoami", headers=bearer("admin-key")).status_code == 401


def test_auth_off_is_open(store, monkeypatch):
    monkeypatch.setenv(auth.DISABLE_VAR, "off")
    c = make_app()
    assert c.get("/whoami").json() == {"name": "anonymous", "role": "admin"}
    assert c.post("/admin").status_code == 200


def test_auth_off_refused_in_production(store, monkeypatch):
    monkeypatch.setenv(auth.DISABLE_VAR, "off")
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(auth.AuthConfigError):
        auth.validate_startup()


def test_startup_provisions_when_missing(store):
    auth.validate_startup()
    assert auth.STORE_KEY in store.docs


def test_startup_rejects_malformed_store_file(store):
    store.docs[auth.STORE_KEY] = {"x": {"keys": []}}
    with pytest.raises(auth.AuthConfigError):
        auth.validate_startup()


# --- config parsing --------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '["list"]',
        '{"x": 42}',
        '{"x": {"role": "client"}}',
        '{"x": {"keys": []}}',
        '{"x": {"keys": ["k"], "role": "root"}}',
        '{"a": "same", "b": "same"}',
    ],
)
def test_malformed_config_is_rejected(raw):
    with pytest.raises(auth.AuthConfigError):
        auth.parse_key_config(raw)


def test_empty_config_means_no_keys():
    assert auth.parse_key_config(None) == []
    assert auth.parse_key_config("   ") == []

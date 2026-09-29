"""Sandbox boot and persistent health checks."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from agentguard.api import create_app


def config(tmp_path):
    return {"identities": [{"agent_id": "finance-sandbox", "role": "finance", "key": "a" * 64}],
            "admin_key": "b" * 64, "secret": "c" * 64,
            "db_path": str(tmp_path / "guard.db")}


def test_sandbox_rejects_demo_and_reused_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_DEPLOYMENT_MODE", "sandbox")
    values = config(tmp_path)
    for change in ({"admin_key": "change-admin-key"}, {"admin_key": "a" * 64},
                   {"db_path": "data/guard.db"}):
        with pytest.raises(ValueError):
            create_app(**{**values, **change})


def test_sandbox_ready_and_persists_audit_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_DEPLOYMENT_MODE", "sandbox")
    values = config(tmp_path)
    with TestClient(create_app(**values)) as client:
        assert client.get("/ready").status_code == 200
        assert client.post("/v1/authorize", headers={"X-Agent-Key": "a" * 64},
                           json={"tool": "payments.refund", "resource": "customer/1",
                                 "arguments": {"amount": 10}}).json()["decision"] == "ALLOW"
    with TestClient(create_app(**values)) as client:
        data = client.get("/v1/events", headers={"X-Admin-Key": "b" * 64}).json()
        assert data["chain_valid"] and len(data["events"]) == 1
        with sqlite3.connect(values["db_path"]) as db:
            db.execute("DROP TABLE support_orders")
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503


def test_public_staging_requires_password_and_gates_api_and_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_DEPLOYMENT_MODE", "sandbox")
    monkeypatch.setenv("AGENTGUARD_REQUIRE_STAGING_PASSWORD", "1")
    values = config(tmp_path)
    with pytest.raises(ValueError, match="required"):
        create_app(**values)
    monkeypatch.setenv("AGENTGUARD_STAGING_PASSWORD", "d" * 64)
    with TestClient(create_app(**values)) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/dashboard").status_code == 401
        assert client.get("/").status_code == 401
        assert client.get("/docs").status_code == 401
        assert client.post("/v1/authorize", headers={"X-Agent-Key": "a" * 64},
                           json={"tool": "payments.refund", "resource": "customer/1",
                                 "arguments": {"amount": 10}}).status_code == 401
        auth = ("reviewer", "d" * 64)
        assert client.get("/dashboard", auth=auth).status_code == 200
        assert client.get("/", auth=auth).status_code == 200
        assert client.get("/v1/events", auth=auth).status_code == 401
        assert client.get("/v1/events", auth=auth,
                          headers={"X-Admin-Key": "b" * 64}).status_code == 200

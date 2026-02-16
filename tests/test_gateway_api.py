import importlib
import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))


def _build_client(tmp_path):
    os.environ["MCP_GATEWAY_DB_PATH"] = str(tmp_path / "gateway.db")
    os.environ["MCP_GATEWAY_ADMIN_TOKEN"] = "test-admin"

    if "mcp_gateway.api" in sys.modules:
        del sys.modules["mcp_gateway.api"]

    api_module = importlib.import_module("mcp_gateway.api")
    app = FastAPI()
    app.include_router(api_module.router)
    return TestClient(app)


def test_gateway_health_endpoint(tmp_path) -> None:
    client = _build_client(tmp_path)
    response = client.get("/gateway/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_list_and_dry_run_policy(tmp_path) -> None:
    client = _build_client(tmp_path)

    payload = {
        "server_id": "srv-1",
        "name": "github-mcp",
        "tenant_id": "tenant-a",
        "transport": "sse",
        "endpoint": "https://example.com/sse",
    }

    create = client.post(
        "/gateway/servers",
        json=payload,
        headers={"x-gateway-admin-token": "test-admin"},
    )
    assert create.status_code == 200

    listed = client.get("/gateway/servers", params={"tenant_id": "tenant-a"})
    assert listed.status_code == 200
    assert any(item["server_id"] == "srv-1" for item in listed.json()["items"])

    deny_before_rule = client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "server_id": "srv-1"},
    )
    assert deny_before_rule.status_code == 200
    assert deny_before_rule.json()["allowed"] is False

    allow_rule = {
        "name": "allow-tenant-a-plan-srv1",
        "effect": "allow",
        "actions": ["plan"],
        "resources": ["gateway.server.srv-1"],
        "tenants": ["tenant-a"],
    }
    rule_resp = client.post(
        "/gateway/policy/rules",
        json=allow_rule,
        headers={"x-gateway-admin-token": "test-admin"},
    )
    assert rule_resp.status_code == 200

    allow_after_rule = client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "server_id": "srv-1"},
    )
    assert allow_after_rule.status_code == 200
    assert allow_after_rule.json()["allowed"] is True


def test_admin_token_required(tmp_path) -> None:
    client = _build_client(tmp_path)
    payload = {
        "server_id": "srv-2",
        "name": "x",
        "tenant_id": "tenant-a",
        "transport": "sse",
        "endpoint": "https://example.com/sse",
    }
    resp = client.post("/gateway/servers", json=payload)
    assert resp.status_code == 403

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


def test_admin_token_bootstrap_and_health(tmp_path) -> None:
    client = _build_client(tmp_path)
    response = client.get("/gateway/health")
    assert response.status_code == 200


def _create_tenant_operator(client: TestClient, token: str = "tenant-a-token") -> None:
    token_resp = client.post(
        "/gateway/access/tokens",
        json={
            "token": token,
            "subject_id": "tenant-a-op",
            "tenant_id": "tenant-a",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:plan"],
        },
        headers={"x-gateway-token": "test-admin"},
    )
    assert token_resp.status_code == 200


def test_flow_register_rule_and_dry_run(tmp_path) -> None:
    client = _build_client(tmp_path)
    _create_tenant_operator(client)

    create = client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-1",
            "name": "github-mcp",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
        },
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert create.status_code == 200

    rule_resp = client.post(
        "/gateway/policy/rules",
        json={
            "name": "allow-plan",
            "effect": "allow",
            "actions": ["plan"],
            "resources": ["gateway.server.srv-1"],
            "tenants": ["tenant-a"],
        },
        headers={"x-gateway-token": "test-admin"},
    )
    assert rule_resp.status_code == 200

    dry = client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "server_id": "srv-1"},
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert dry.status_code == 200
    assert dry.json()["allowed"] is True


def test_missing_scope_returns_403(tmp_path) -> None:
    client = _build_client(tmp_path)

    token_resp = client.post(
        "/gateway/access/tokens",
        json={
            "token": "read-only-token",
            "subject_id": "tenant-a-reader",
            "tenant_id": "tenant-a",
            "role": "reader",
            "scopes": ["gateway:read"],
        },
        headers={"x-gateway-token": "test-admin"},
    )
    assert token_resp.status_code == 200

    create = client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-nope",
            "name": "github-mcp",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
        },
        headers={"x-gateway-token": "read-only-token"},
    )
    assert create.status_code == 403
    assert "Missing scope" in create.json()["detail"]


def test_malformed_payload_returns_422(tmp_path) -> None:
    client = _build_client(tmp_path)
    _create_tenant_operator(client)

    bad_payload = {
        "server_id": "srv-bad",
        "name": "broken-server",
        "tenant_id": "tenant-a",
        "transport": "grpc",  # unsupported transport
        "endpoint": "not-a-url",
    }

    response = client.post(
        "/gateway/servers",
        json=bad_payload,
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert response.status_code == 422

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


def test_admin_can_create_tenant_token_and_register_server(tmp_path) -> None:
    client = _build_client(tmp_path)

    token_resp = client.post(
        "/gateway/access/tokens",
        json={
            "token": "tenant-a-token",
            "subject_id": "tenant-a-op",
            "tenant_id": "tenant-a",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:plan"],
        },
        headers={"x-gateway-token": "test-admin"},
    )
    assert token_resp.status_code == 200

    create = client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-1",
            "name": "github-mcp",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
            "weight": 3,
            "priority": 10,
        },
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert create.status_code == 200
    assert create.json()["weight"] == 3


def test_transport_validation_rejects_bad_endpoint(tmp_path) -> None:
    client = _build_client(tmp_path)

    bad = client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-bad",
            "name": "bad",
            "tenant_id": "tenant-a",
            "transport": "ws",
            "endpoint": "https://not-ws.example.com",
        },
        headers={"x-gateway-token": "test-admin"},
    )
    assert bad.status_code == 400


def test_tenant_scope_blocks_cross_tenant_writes(tmp_path) -> None:
    client = _build_client(tmp_path)

    client.post(
        "/gateway/access/tokens",
        json={
            "token": "tenant-a-token",
            "subject_id": "tenant-a-op",
            "tenant_id": "tenant-a",
            "role": "tenant-operator",
            "scopes": ["gateway:write"],
        },
        headers={"x-gateway-token": "test-admin"},
    )

    forbidden = client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-x",
            "name": "cross-tenant",
            "tenant_id": "tenant-b",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
        },
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert forbidden.status_code == 403


def test_weighted_and_failover_route_planning(tmp_path) -> None:
    client = _build_client(tmp_path)

    # Tenant token with planning + write
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "tenant-a-token",
            "subject_id": "tenant-a-op",
            "tenant_id": "tenant-a",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:plan"],
        },
        headers={"x-gateway-token": "test-admin"},
    )

    # policy author token
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "policy-token",
            "subject_id": "policy",
            "role": "tenant-operator",
            "scopes": ["gateway:policy:write", "gateway:policy:read"],
        },
        headers={"x-gateway-token": "test-admin"},
    )

    # create two servers
    client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-1",
            "name": "one",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
            "weight": 1,
            "priority": 20,
        },
        headers={"x-gateway-token": "tenant-a-token"},
    )
    client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-2",
            "name": "two",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse2",
            "weight": 5,
            "priority": 10,
        },
        headers={"x-gateway-token": "tenant-a-token"},
    )

    # allow planning on both servers
    client.post(
        "/gateway/policy/rules",
        json={
            "name": "allow-tenant-a-plan",
            "effect": "allow",
            "actions": ["plan"],
            "resources": ["gateway.server.srv-1", "gateway.server.srv-2"],
            "tenants": ["tenant-a"],
        },
        headers={"x-gateway-token": "policy-token"},
    )

    failover = client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "strategy": "failover"},
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert failover.status_code == 200
    assert failover.json()["selected_server_id"] == "srv-2"  # lower priority wins
    assert failover.json()["allowed"] is True

    weighted = client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "strategy": "weighted"},
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert weighted.status_code == 200
    assert weighted.json()["selected_server_id"] in {"srv-1", "srv-2"}


def test_auth_required(tmp_path) -> None:
    client = _build_client(tmp_path)
    resp = client.get("/gateway/servers")
    assert resp.status_code == 401

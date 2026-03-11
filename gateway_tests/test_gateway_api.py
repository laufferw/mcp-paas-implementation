import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
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
    body = dry.json()
    assert body["allowed"] is True
    assert body["event_id"]
    assert body["decided_at"]
    assert body["actor"]["subject_id"] == "tenant-a-op"
    assert body["request"]["tenant_id"] == "tenant-a"


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


def test_expired_token_returns_401(tmp_path) -> None:
    client = _build_client(tmp_path)

    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    token_resp = client.post(
        "/gateway/access/tokens",
        json={
            "token": "expired-token",
            "subject_id": "tenant-a-expired",
            "tenant_id": "tenant-a",
            "role": "tenant-operator",
            "scopes": ["gateway:read"],
            "expires_at": expired_at,
        },
        headers={"x-gateway-token": "test-admin"},
    )
    assert token_resp.status_code == 200

    response = client.get("/gateway/servers", headers={"x-gateway-token": "expired-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired"


def test_revoked_token_returns_403(tmp_path) -> None:
    client = _build_client(tmp_path)
    _create_tenant_operator(client, token="revocable-token")

    revoke = client.post(
        "/gateway/access/tokens/revocable-token/revoke",
        headers={"x-gateway-token": "test-admin"},
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    response = client.get("/gateway/servers", headers={"x-gateway-token": "revocable-token"})
    assert response.status_code == 403
    assert response.json()["detail"] in ("Gateway token disabled", "Token disabled", "Token revoked")


# ---------- Negative test cases (Workstream A) ----------


def test_missing_auth_header_returns_401(tmp_path) -> None:
    client = _build_client(tmp_path)
    response = client.get("/gateway/servers")
    assert response.status_code == 401
    assert response.json()["detail"] == "x-gateway-token required"


def test_invalid_token_returns_401(tmp_path) -> None:
    client = _build_client(tmp_path)
    response = client.get("/gateway/servers", headers={"x-gateway-token": "bogus-token-xyz"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid gateway token"


def test_reader_cannot_write_server(tmp_path) -> None:
    client = _build_client(tmp_path)
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "reader-token",
            "subject_id": "reader-1",
            "tenant_id": "tenant-a",
            "role": "reader",
            "scopes": ["gateway:read"],
        },
        headers={"x-gateway-token": "test-admin"},
    )
    resp = client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-x",
            "name": "test",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
        },
        headers={"x-gateway-token": "reader-token"},
    )
    assert resp.status_code == 403
    assert "Missing scope" in resp.json()["detail"]


def test_register_server_missing_required_fields(tmp_path) -> None:
    client = _build_client(tmp_path)
    _create_tenant_operator(client)

    resp = client.post(
        "/gateway/servers",
        json={"server_id": "srv-incomplete"},
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert resp.status_code == 422


def test_dry_run_unknown_server_id(tmp_path) -> None:
    client = _build_client(tmp_path)
    _create_tenant_operator(client)

    resp = client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "server_id": "nonexistent-srv"},
        headers={"x-gateway-token": "tenant-a-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is False
    assert body["decision"] == "deny"
    assert "not registered" in body["reason"]


def test_disabled_token_returns_403(tmp_path) -> None:
    client = _build_client(tmp_path)
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "disabled-token",
            "subject_id": "disabled-user",
            "tenant_id": "tenant-a",
            "role": "tenant-operator",
            "scopes": ["gateway:read"],
            "enabled": False,
        },
        headers={"x-gateway-token": "test-admin"},
    )
    resp = client.get("/gateway/servers", headers={"x-gateway-token": "disabled-token"})
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"].lower()


def test_audit_log_export(tmp_path) -> None:
    client = _build_client(tmp_path)
    _create_tenant_operator(client)

    client.post(
        "/gateway/servers",
        json={
            "server_id": "srv-audit",
            "name": "audit-test",
            "tenant_id": "tenant-a",
            "transport": "sse",
            "endpoint": "https://example.com/sse",
        },
        headers={"x-gateway-token": "tenant-a-token"},
    )
    client.post(
        "/gateway/policy/rules",
        json={
            "name": "allow-audit-plan",
            "effect": "allow",
            "actions": ["plan"],
            "resources": ["gateway.server.srv-audit"],
            "tenants": ["tenant-a"],
        },
        headers={"x-gateway-token": "test-admin"},
    )
    client.post(
        "/gateway/routes/dry-run",
        json={"tenant_id": "tenant-a", "action": "plan", "server_id": "srv-audit"},
        headers={"x-gateway-token": "tenant-a-token"},
    )

    resp = client.get(
        "/gateway/audit",
        params={"tenant_id": "tenant-a"},
        headers={"x-gateway-token": "test-admin"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert items[0]["event_id"]
    assert items[0]["decision"] in ("allow", "deny")

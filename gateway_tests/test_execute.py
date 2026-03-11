"""Integration tests for POST /gateway/routes/execute.

Exercises real transport execution against the echo MCP server fixture.
"""
import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
sys.path.append(str(Path(__file__).resolve().parents[1] / "tests"))

from fixtures.echo_mcp_server import start_echo_server  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_TOKEN = "test-admin-exec"


def _build_client(tmp_path) -> TestClient:
    os.environ["MCP_GATEWAY_DB_PATH"] = str(tmp_path / "gateway.db")
    os.environ["MCP_GATEWAY_ADMIN_TOKEN"] = ADMIN_TOKEN

    if "mcp_gateway.api" in sys.modules:
        del sys.modules["mcp_gateway.api"]

    api_module = importlib.import_module("mcp_gateway.api")
    app = FastAPI()
    app.include_router(api_module.router)
    return TestClient(app)


def _setup_tenant_and_server(client: TestClient, endpoint: str) -> None:
    """Create a tenant token, register the echo server, and add an allow rule."""
    # Tenant token with execute scope
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "exec-token",
            "subject_id": "exec-op",
            "tenant_id": "tenant-e",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:plan", "gateway:execute"],
        },
        headers={"x-gateway-token": ADMIN_TOKEN},
    )

    # Register the echo MCP server
    client.post(
        "/gateway/servers",
        json={
            "server_id": "echo-srv",
            "name": "Echo MCP",
            "tenant_id": "tenant-e",
            "transport": "streamable-http",
            "endpoint": endpoint,
        },
        headers={"x-gateway-token": "exec-token"},
    )

    # Policy: allow tools/* methods
    client.post(
        "/gateway/policy/rules",
        json={
            "name": "allow-tools",
            "effect": "allow",
            "actions": ["tools/list", "tools/call"],
            "resources": ["gateway.server.echo-srv"],
            "tenants": ["tenant-e"],
        },
        headers={"x-gateway-token": ADMIN_TOKEN},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def echo_server():
    """Start the echo MCP server once for the whole module."""
    server, port = start_echo_server()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_execute_tools_list(tmp_path, echo_server):
    """Allow path: execute tools/list and get a real response."""
    client = _build_client(tmp_path)
    _setup_tenant_and_server(client, echo_server)

    resp = client.post(
        "/gateway/routes/execute",
        json={"server_id": "echo-srv", "method": "tools/list", "params": {}},
        headers={"x-gateway-token": "exec-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "allowed"
    assert body["result"]["tools"][0]["name"] == "echo"
    assert body["audit_id"]
    assert body["duration_ms"] >= 0
    assert body["policy_decision"]["decision"] == "allow"


def test_execute_tools_call_echo(tmp_path, echo_server):
    """Execute tools/call with echo tool and get params echoed back."""
    client = _build_client(tmp_path)
    _setup_tenant_and_server(client, echo_server)

    resp = client.post(
        "/gateway/routes/execute",
        json={
            "server_id": "echo-srv",
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "hello"}},
        },
        headers={"x-gateway-token": "exec-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "allowed"
    assert '"msg": "hello"' in body["result"]["content"][0]["text"]


def test_execute_denied_by_policy(tmp_path, echo_server):
    """Deny path: execute a method not covered by any allow rule."""
    client = _build_client(tmp_path)
    _setup_tenant_and_server(client, echo_server)

    resp = client.post(
        "/gateway/routes/execute",
        json={"server_id": "echo-srv", "method": "resources/list", "params": {}},
        headers={"x-gateway-token": "exec-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "denied"
    assert body["result"] is None
    assert body["policy_decision"]["decision"] == "deny"


def test_execute_dry_run(tmp_path, echo_server):
    """dry_run=true: policy check but no actual call."""
    client = _build_client(tmp_path)
    _setup_tenant_and_server(client, echo_server)

    resp = client.post(
        "/gateway/routes/execute",
        json={
            "server_id": "echo-srv",
            "method": "tools/list",
            "params": {},
            "dry_run": True,
        },
        headers={"x-gateway-token": "exec-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "allowed"
    assert body["result"] is None  # No actual call was made
    assert body["dry_run"] is True


def test_execute_unknown_server(tmp_path):
    """Unknown server_id returns 404."""
    client = _build_client(tmp_path)

    resp = client.post(
        "/gateway/routes/execute",
        json={"server_id": "nonexistent", "method": "tools/list", "params": {}},
        headers={"x-gateway-token": ADMIN_TOKEN},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_execute_transport_error(tmp_path):
    """Server registered but unreachable → graceful error response."""
    client = _build_client(tmp_path)

    # Tenant token
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "err-token",
            "subject_id": "err-op",
            "tenant_id": "tenant-err",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:execute"],
        },
        headers={"x-gateway-token": ADMIN_TOKEN},
    )

    # Register server with unreachable endpoint
    client.post(
        "/gateway/servers",
        json={
            "server_id": "dead-srv",
            "name": "Dead MCP",
            "tenant_id": "tenant-err",
            "transport": "streamable-http",
            "endpoint": "http://127.0.0.1:1",  # unreachable port
        },
        headers={"x-gateway-token": "err-token"},
    )

    # Allow rule
    client.post(
        "/gateway/policy/rules",
        json={
            "name": "allow-dead",
            "effect": "allow",
            "actions": ["tools/list"],
            "resources": ["gateway.server.dead-srv"],
            "tenants": ["tenant-err"],
        },
        headers={"x-gateway-token": ADMIN_TOKEN},
    )

    resp = client.post(
        "/gateway/routes/execute",
        json={"server_id": "dead-srv", "method": "tools/list", "params": {}},
        headers={"x-gateway-token": "err-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["error"]  # Should contain transport error message
    assert body["audit_id"]

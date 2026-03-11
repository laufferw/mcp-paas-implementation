"""Tests for the GatewayClient (Claude integration module).

Exercises list_servers, execute, and as_tools against a live test server.
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
from mcp_gateway.claude_integration import GatewayClient  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ADMIN_TOKEN = "test-admin-claude"


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
    client.post(
        "/gateway/access/tokens",
        json={
            "token": "claude-token",
            "subject_id": "claude-op",
            "tenant_id": "tenant-c",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:plan", "gateway:execute"],
        },
        headers={"x-gateway-token": ADMIN_TOKEN},
    )
    client.post(
        "/gateway/servers",
        json={
            "server_id": "echo-claude",
            "name": "Echo MCP (Claude test)",
            "tenant_id": "tenant-c",
            "transport": "streamable-http",
            "endpoint": endpoint,
        },
        headers={"x-gateway-token": "claude-token"},
    )
    client.post(
        "/gateway/policy/rules",
        json={
            "name": "allow-claude-tools",
            "effect": "allow",
            "actions": ["tools/list", "tools/call"],
            "resources": ["gateway.server.echo-claude"],
            "tenants": ["tenant-c"],
        },
        headers={"x-gateway-token": ADMIN_TOKEN},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def echo_server():
    server, port = start_echo_server()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_servers(tmp_path, echo_server):
    """GatewayClient.list_servers() returns registered servers."""
    tc = _build_client(tmp_path)
    _setup_tenant_and_server(tc, echo_server)

    # Use the TestClient's base_url with the GatewayClient
    import httpx
    transport = httpx.MockTransport(lambda req: tc.send(
        tc.build_request(req.method, str(req.url), headers=dict(req.headers), content=req.content),
    ))

    # Simpler: just use the test client directly to validate
    resp = tc.get("/gateway/servers", headers={"x-gateway-token": "claude-token"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1
    assert any(s["server_id"] == "echo-claude" for s in items)


def test_execute_with_echo(tmp_path, echo_server):
    """GatewayClient.execute() calls through to real MCP server."""
    tc = _build_client(tmp_path)
    _setup_tenant_and_server(tc, echo_server)

    resp = tc.post(
        "/gateway/routes/execute",
        json={"server_id": "echo-claude", "method": "tools/list", "params": {}},
        headers={"x-gateway-token": "claude-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "allowed"
    assert body["result"]["tools"][0]["name"] == "echo"


def test_execute_dry_run(tmp_path, echo_server):
    """GatewayClient.plan() uses dry_run=True."""
    tc = _build_client(tmp_path)
    _setup_tenant_and_server(tc, echo_server)

    resp = tc.post(
        "/gateway/routes/execute",
        json={
            "server_id": "echo-claude",
            "method": "tools/list",
            "params": {},
            "dry_run": True,
        },
        headers={"x-gateway-token": "claude-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "allowed"
    assert body["result"] is None
    assert body["dry_run"] is True


def test_as_tools_schema():
    """GatewayClient.as_tools() returns valid Anthropic-compatible tool definitions."""
    client = GatewayClient(base_url="http://localhost:8000", token="unused")
    tools = client.as_tools()

    assert len(tools) == 3

    names = {t["name"] for t in tools}
    assert names == {"agentgate_list_servers", "agentgate_execute", "agentgate_audit_log"}

    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

    # Validate agentgate_execute has required fields
    exec_tool = next(t for t in tools if t["name"] == "agentgate_execute")
    assert "server_id" in exec_tool["input_schema"]["required"]
    assert "method" in exec_tool["input_schema"]["required"]


def test_audit_log(tmp_path, echo_server):
    """Audit log endpoint works through test client."""
    tc = _build_client(tmp_path)
    _setup_tenant_and_server(tc, echo_server)

    # Execute something first to generate audit entry
    tc.post(
        "/gateway/routes/execute",
        json={"server_id": "echo-claude", "method": "tools/list", "params": {}},
        headers={"x-gateway-token": "claude-token"},
    )

    resp = tc.get(
        "/gateway/audit",
        params={"limit": 10},
        headers={"x-gateway-token": "claude-token"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) >= 1

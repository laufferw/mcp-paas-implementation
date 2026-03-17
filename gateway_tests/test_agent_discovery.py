"""Tests for agent-native discovery and self-registration endpoints."""

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


# ---------- GET /gateway/agent-info ----------


def test_agent_info_no_auth(tmp_path) -> None:
    client = _build_client(tmp_path)
    resp = client.get("/gateway/agent-info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "AgentGate"
    assert "self_registration" in body
    assert "endpoints" in body
    assert "policy_examples" in body
    assert "dry_run" in body


def test_agent_info_has_registration_schema(tmp_path) -> None:
    client = _build_client(tmp_path)
    body = client.get("/gateway/agent-info").json()
    schema = body["self_registration"]["request_schema"]
    assert "agent_name" in schema
    assert schema["agent_name"]["required"] is True
    assert "capabilities" in schema


def test_agent_info_lists_all_key_endpoints(tmp_path) -> None:
    client = _build_client(tmp_path)
    body = client.get("/gateway/agent-info").json()
    paths = [e["path"] for e in body["endpoints"]]
    assert "/gateway/agents/register" in paths
    assert "/gateway/agents" in paths
    assert "/gateway/routes/dry-run" in paths
    assert "/gateway/routes/execute" in paths


# ---------- POST /gateway/agents/register ----------


def test_agent_register_returns_credentials(tmp_path) -> None:
    client = _build_client(tmp_path)
    resp = client.post(
        "/gateway/agents/register",
        json={"agent_name": "test-agent", "agent_description": "A test agent", "capabilities": ["testing"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"].startswith("agent-")
    assert body["api_token"].startswith("agt-")
    assert body["tenant_id"].startswith("agent-")
    assert "getting_started" in body


def test_agent_register_token_works(tmp_path) -> None:
    """The returned token should authenticate against gateway endpoints."""
    client = _build_client(tmp_path)
    reg = client.post(
        "/gateway/agents/register",
        json={"agent_name": "auth-test-agent"},
    ).json()

    # Use the returned token to list servers (should work, empty list)
    resp = client.get("/gateway/servers", headers={"x-gateway-token": reg["api_token"]})
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_agent_register_stores_metadata(tmp_path) -> None:
    client = _build_client(tmp_path)
    client.post(
        "/gateway/agents/register",
        json={
            "agent_name": "metadata-agent",
            "agent_description": "Does metadata things",
            "model": "claude-opus-4-6",
            "owner_handle": "@tester",
            "capabilities": ["analysis", "summarization"],
        },
    )

    # Verify via public directory
    resp = client.get("/gateway/agents")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    agent = items[0]
    assert agent["agent_name"] == "metadata-agent"
    assert agent["description"] == "Does metadata things"
    assert agent["model"] == "claude-opus-4-6"
    assert "analysis" in agent["capabilities"]
    assert "summarization" in agent["capabilities"]


def test_agent_register_missing_name_returns_422(tmp_path) -> None:
    client = _build_client(tmp_path)
    resp = client.post("/gateway/agents/register", json={"agent_description": "no name"})
    assert resp.status_code == 422


def test_agent_register_minimal_payload(tmp_path) -> None:
    client = _build_client(tmp_path)
    resp = client.post("/gateway/agents/register", json={"agent_name": "minimal"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"]
    assert body["api_token"]


# ---------- GET /gateway/agents (public directory) ----------


def test_agents_directory_no_auth(tmp_path) -> None:
    client = _build_client(tmp_path)
    resp = client.get("/gateway/agents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1


def test_agents_directory_pagination(tmp_path) -> None:
    client = _build_client(tmp_path)

    # Register 3 agents
    for i in range(3):
        client.post("/gateway/agents/register", json={"agent_name": f"agent-{i}"})

    # Page 1 with page_size=2
    resp = client.get("/gateway/agents", params={"page": 1, "page_size": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["page_size"] == 2

    # Page 2
    resp2 = client.get("/gateway/agents", params={"page": 2, "page_size": 2})
    body2 = resp2.json()
    assert len(body2["items"]) == 1


def test_agents_directory_shows_registered_agents(tmp_path) -> None:
    client = _build_client(tmp_path)
    client.post(
        "/gateway/agents/register",
        json={"agent_name": "visible-agent", "capabilities": ["coding"]},
    )

    resp = client.get("/gateway/agents")
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["agent_name"] == "visible-agent"
    assert "coding" in items[0]["capabilities"]
    assert items[0]["registered_at"]
    # Should NOT expose api_token
    assert "api_token" not in items[0]
    assert "api_token_ref" not in items[0]


# ---------- Rate limiting ----------


def test_agent_register_rate_limit(tmp_path) -> None:
    """Registration should be rate-limited to 5/hour per IP."""
    client = _build_client(tmp_path)

    # First 5 should succeed
    for i in range(5):
        resp = client.post("/gateway/agents/register", json={"agent_name": f"rate-agent-{i}"})
        assert resp.status_code == 200, f"Registration {i} failed unexpectedly"

    # 6th should be rate-limited
    resp = client.post("/gateway/agents/register", json={"agent_name": "rate-agent-6"})
    assert resp.status_code == 429
    assert "Rate limit" in resp.json()["detail"]

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request as FastAPIRequest
from fastapi.responses import Response
from prometheus_client import generate_latest
from pydantic import BaseModel, Field

from .authz import AccessToken, AuthzStore, require_scope
from .observability import GatewayMetrics
from .policy import PolicyDecision, PolicyEngine, PolicyEvaluation, PolicyRequest, PolicyRule
from .registry import GatewayRegistry, RegisteredServer
from .storage import GatewayStorage
from .transport_adapters import get_adapter
from .transports import validate_transport_endpoint

router = APIRouter(prefix="/gateway", tags=["gateway"])

# Code Mode sub-router (mounted after this module's routes are defined)
def mount_codemode_router(app_router: APIRouter) -> None:
    from .api_codemode import router as codemode_router
    app_router.include_router(codemode_router)

_DB_PATH = os.getenv(
    "MCP_GATEWAY_DB_PATH",
    str((Path(__file__).resolve().parents[2] / "data" / "gateway_control_plane.db")),
)
_ADMIN_TOKEN = os.getenv("MCP_GATEWAY_ADMIN_TOKEN", "dev-gateway-token")

storage = GatewayStorage(db_path=_DB_PATH)
authz = AuthzStore(storage=storage)
registry = GatewayRegistry(storage=storage)
metrics = GatewayMetrics.create()
policy = PolicyEngine(storage=storage, default_decision=PolicyDecision.DENY)


def _bootstrap_access_tokens() -> None:
    authz.upsert_token(
        AccessToken(
            token=_ADMIN_TOKEN,
            subject_id="bootstrap-admin",
            tenant_id=None,
            role="admin",
            scopes={"gateway:*"},
        )
    )


_bootstrap_access_tokens()


def _require_actor(x_gateway_token: str | None = Header(default=None)) -> AccessToken:
    if not x_gateway_token:
        raise HTTPException(status_code=401, detail="x-gateway-token required")
    actor = authz.get_token(x_gateway_token)
    if actor is None:
        raise HTTPException(status_code=401, detail="Invalid gateway token")
    if not actor.enabled:
        raise HTTPException(status_code=403, detail="Gateway token disabled")
    if actor.expires_at:
        expires = datetime.fromisoformat(actor.expires_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expires:
            raise HTTPException(status_code=401, detail="Token expired")
    return actor


class RegisterServerRequest(BaseModel):
    server_id: str
    name: str
    tenant_id: str
    transport: Literal["stdio", "sse", "streamable-http", "ws"]
    endpoint: str
    tags: list[str] = Field(default_factory=list)
    weight: int = Field(default=1, ge=1, le=100)
    priority: int = Field(default=100, ge=1, le=1000)


class RouteDryRunRequest(BaseModel):
    tenant_id: str
    action: str
    server_id: str | None = None
    preferred_server_id: str | None = None
    strategy: Literal["preferred", "weighted", "failover"] = "preferred"


class PolicyRuleCreate(BaseModel):
    name: str
    effect: PolicyDecision
    actions: list[str]
    resources: list[str]
    tenants: list[str] | None = None


class ExecuteRequest(BaseModel):
    server_id: str
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class AccessTokenCreate(BaseModel):
    token: str
    subject_id: str
    tenant_id: str | None = None
    role: Literal["admin", "tenant-operator", "reader"] = "reader"
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = True
    expires_at: str | None = None


class AgentRegisterRequest(BaseModel):
    agent_name: str
    agent_description: str | None = None
    model: str | None = None
    owner_handle: str | None = None
    capabilities: list[str] = Field(default_factory=list)


# --- Rate limiter for agent registration (5/hour per IP) ---
_agent_register_timestamps: dict[str, list[float]] = defaultdict(list)
_AGENT_REGISTER_LIMIT = 5
_AGENT_REGISTER_WINDOW = 3600  # 1 hour


def _check_agent_register_rate(ip: str) -> None:
    now = time.monotonic()
    window = [t for t in _agent_register_timestamps[ip] if now - t < _AGENT_REGISTER_WINDOW]
    _agent_register_timestamps[ip] = window
    if len(window) >= _AGENT_REGISTER_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded: 5 registrations per hour")
    window.append(now)


@router.get("/health")
async def gateway_health() -> dict:
    return {
        "status": "ok",
        "db_path": _DB_PATH,
        "servers": len(registry.list_servers()),
        "policy_rules": len(policy.list_rules()),
        "metrics": metrics.snapshot(),
    }


@router.get("/metrics")
async def gateway_metrics() -> Response:
    return Response(content=generate_latest().decode(), media_type="text/plain")


@router.get("/servers")
async def list_servers(
    tenant_id: str | None = None,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    scope_tenant = tenant_id if actor.role == "admin" else actor.tenant_id
    require_scope(actor, "gateway:read", tenant_id=scope_tenant)

    metrics.increment("gateway_servers_list")
    servers = registry.list_servers(tenant_id=scope_tenant)
    return {
        "items": [
            {
                "server_id": s.server_id,
                "name": s.name,
                "tenant_id": s.tenant_id,
                "transport": s.transport,
                "endpoint": s.endpoint,
                "tags": s.tags,
                "healthy": s.healthy,
                "weight": s.weight,
                "priority": s.priority,
            }
            for s in servers
        ]
    }


@router.post("/servers")
async def register_server(
    payload: RegisterServerRequest,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:write", tenant_id=payload.tenant_id)

    validate_transport_endpoint(payload.transport, payload.endpoint)

    metrics.increment("gateway_servers_register")
    record = RegisteredServer(
        server_id=payload.server_id,
        name=payload.name,
        endpoint=payload.endpoint,
        transport=payload.transport,
        tenant_id=payload.tenant_id,
        tags=payload.tags,
        weight=payload.weight,
        priority=payload.priority,
    )
    registry.register(record)
    return {
        "server_id": record.server_id,
        "name": record.name,
        "tenant_id": record.tenant_id,
        "transport": record.transport,
        "endpoint": record.endpoint,
        "tags": record.tags,
        "healthy": record.healthy,
        "weight": record.weight,
        "priority": record.priority,
    }


@router.post("/servers/{server_id}/health")
async def set_server_health(
    server_id: str,
    healthy: bool = Query(...),
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)

    server = registry.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    require_scope(actor, "gateway:write", tenant_id=server.tenant_id)

    registry.set_health(server_id=server_id, healthy=healthy)
    return {"status": "ok", "server_id": server_id, "healthy": healthy}


@router.get("/policy/rules")
async def list_policy_rules(x_gateway_token: str | None = Header(default=None)) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:policy:read")

    rules = policy.list_rules()
    return {
        "items": [
            {
                "name": r.name,
                "effect": r.effect.value,
                "actions": sorted(r.actions),
                "resources": sorted(r.resources),
                "tenants": sorted(r.tenants) if r.tenants is not None else None,
            }
            for r in rules
        ]
    }


@router.post("/policy/rules")
async def create_policy_rule(
    payload: PolicyRuleCreate,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:policy:write")

    policy.add_rule(
        PolicyRule(
            name=payload.name,
            effect=payload.effect,
            actions=set(payload.actions),
            resources=set(payload.resources),
            tenants=set(payload.tenants) if payload.tenants else None,
        )
    )
    return {"status": "ok", "name": payload.name}


@router.delete("/policy/rules/{name}")
async def delete_policy_rule(name: str, x_gateway_token: str | None = Header(default=None)) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:policy:write")

    policy.remove_rule(name)
    return {"status": "ok", "name": name}


@router.post("/access/tokens")
async def create_access_token(payload: AccessTokenCreate, x_gateway_token: str | None = Header(default=None)) -> dict:
    actor = _require_actor(x_gateway_token)
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    authz.upsert_token(
        AccessToken(
            token=payload.token,
            subject_id=payload.subject_id,
            tenant_id=payload.tenant_id,
            role=payload.role,
            scopes=set(payload.scopes),
            enabled=payload.enabled,
            expires_at=payload.expires_at,
        )
    )
    return {"status": "ok", "subject_id": payload.subject_id}


@router.post("/access/tokens/{token}/revoke")
async def revoke_access_token(token: str, x_gateway_token: str | None = Header(default=None)) -> dict:
    actor = _require_actor(x_gateway_token)
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")

    revoked = authz.revoke_token(token)
    if not revoked:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok", "token": token, "revoked": True}


@router.get("/agent-info")
async def agent_info() -> dict:
    """Machine-readable endpoint describing AgentGate for AI agents."""
    return {
        "service": "AgentGate",
        "description": (
            "AgentGate is an MCP gateway and control plane for AI agents. "
            "It sits in front of MCP servers and business APIs, adding policy-governed "
            "routing, multi-tenant access control, audit logging, and health-aware "
            "server selection. Agents use AgentGate to safely invoke tools across "
            "organizational boundaries."
        ),
        "self_registration": {
            "endpoint": "POST /gateway/agents/register",
            "description": "Register your agent to get an API token and start routing requests.",
            "request_schema": {
                "agent_name": {"type": "string", "required": True},
                "agent_description": {"type": "string", "required": False},
                "model": {"type": "string", "required": False, "example": "claude-opus-4-6"},
                "owner_handle": {"type": "string", "required": False},
                "capabilities": {"type": "array[string]", "required": False, "example": ["code-review", "data-analysis"]},
            },
            "rate_limit": "5 registrations per hour per IP",
        },
        "endpoints": [
            {"method": "GET", "path": "/gateway/health", "auth": False, "description": "Health check"},
            {"method": "GET", "path": "/gateway/agent-info", "auth": False, "description": "This endpoint — agent-readable gateway info"},
            {"method": "POST", "path": "/gateway/agents/register", "auth": False, "description": "Self-register an agent"},
            {"method": "GET", "path": "/gateway/agents", "auth": False, "description": "Public directory of registered agents"},
            {"method": "GET", "path": "/gateway/servers", "auth": True, "scope": "gateway:read", "description": "List MCP servers"},
            {"method": "POST", "path": "/gateway/servers", "auth": True, "scope": "gateway:write", "description": "Register an MCP server"},
            {"method": "POST", "path": "/gateway/routes/dry-run", "auth": True, "scope": "gateway:plan", "description": "Test a route without executing"},
            {"method": "POST", "path": "/gateway/routes/execute", "auth": True, "scope": "gateway:execute", "description": "Execute a method on an MCP server"},
            {"method": "GET", "path": "/gateway/policy/rules", "auth": True, "scope": "gateway:policy:read", "description": "List policy rules"},
            {"method": "POST", "path": "/gateway/access/tokens", "auth": True, "scope": "admin", "description": "Create access tokens"},
            {"method": "GET", "path": "/gateway/audit", "auth": True, "scope": "gateway:read", "description": "Export audit log"},
        ],
        "policy_examples": [
            {
                "name": "allow-tools-list",
                "effect": "allow",
                "actions": ["tools/list"],
                "resources": ["gateway.server.*"],
                "description": "Allow listing tools on any server",
            },
            {
                "name": "deny-destructive",
                "effect": "deny",
                "actions": ["tools/call"],
                "resources": ["gateway.server.prod-*"],
                "description": "Block tool calls to production servers",
            },
        ],
        "dry_run": {
            "endpoint": "POST /gateway/routes/dry-run",
            "description": "Test whether a route would be allowed before executing. Requires gateway:plan scope.",
            "example_body": {
                "tenant_id": "your-tenant",
                "action": "tools/list",
                "server_id": "target-server-id",
            },
        },
    }


async def _register_agent_impl(payload: AgentRegisterRequest, client_ip: str = "unknown") -> dict:
    _check_agent_register_rate(client_ip)

    agent_id = f"agent-{uuid4().hex[:12]}"
    api_token = f"agt-{secrets.token_urlsafe(32)}"
    tenant_id = f"agent-{hashlib.sha256(agent_id.encode()).hexdigest()[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    # Create access token for this agent
    authz.upsert_token(
        AccessToken(
            token=api_token,
            subject_id=agent_id,
            tenant_id=tenant_id,
            role="tenant-operator",
            scopes={"gateway:read", "gateway:write", "gateway:plan", "gateway:execute"},
        )
    )

    # Store agent metadata
    storage.execute(
        """
        INSERT INTO registered_agents (id, agent_name, description, model, owner_handle, capabilities_json, api_token_ref, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_id,
            payload.agent_name,
            payload.agent_description,
            payload.model,
            payload.owner_handle,
            json.dumps(payload.capabilities),
            api_token,
            now,
        ),
    )

    return {
        "agent_id": agent_id,
        "api_token": api_token,
        "tenant_id": tenant_id,
        "getting_started": {
            "step_1": "Save your api_token securely — it will not be shown again.",
            "step_2": f"Use header 'x-gateway-token: {api_token}' for all authenticated requests.",
            "step_3": "Register MCP servers: POST /gateway/servers",
            "step_4": "Create policy rules (ask your admin) or use dry-run to test routing.",
            "step_5": "Execute tool calls: POST /gateway/routes/execute",
        },
    }


@router.post("/agents/register")
async def register_agent(payload: AgentRegisterRequest, request: FastAPIRequest) -> dict:
    """Agent self-registration: creates a tenant-scoped token and returns credentials."""
    client_ip = request.client.host if request.client else "unknown"
    return await _register_agent_impl(payload, client_ip=client_ip)


@router.get("/agents")
async def list_agents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Public directory of registered agents."""
    offset = (page - 1) * page_size
    rows = storage.query_all(
        "SELECT id, agent_name, description, model, capabilities_json, registered_at FROM registered_agents ORDER BY registered_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    )
    count_row = storage.query_one("SELECT COUNT(*) as total FROM registered_agents")
    total = count_row["total"] if count_row else 0

    return {
        "items": [
            {
                "agent_id": r["id"],
                "agent_name": r["agent_name"],
                "description": r["description"],
                "model": r["model"],
                "capabilities": json.loads(r["capabilities_json"] or "[]"),
                "registered_at": r["registered_at"],
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def _dry_run_audit_fields(actor: AccessToken, tenant_id: str, action: str) -> dict:
    return {
        "event_id": str(uuid4()),
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "actor": {
            "subject_id": actor.subject_id,
            "role": actor.role,
            "tenant_id": actor.tenant_id,
        },
        "request": {
            "tenant_id": tenant_id,
            "action": action,
        },
    }


def _store_audit_entry(result: dict) -> None:
    storage.execute(
        """
        INSERT INTO gateway_audit_log (
            event_id, decided_at, subject_id, role, tenant_id,
            action, decision, reason, matched_rule,
            selected_server_id, server_healthy, strategy, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result["event_id"],
            result["decided_at"],
            result["actor"]["subject_id"],
            result["actor"]["role"],
            result["request"]["tenant_id"],
            result["request"]["action"],
            result["decision"],
            result.get("reason"),
            result.get("matched_rule"),
            result.get("selected_server_id"),
            1 if result.get("server_healthy") else 0 if result.get("server_healthy") is not None else None,
            result.get("strategy"),
            json.dumps(result),
        ),
    )


@router.post("/routes/dry-run")
async def route_dry_run(payload: RouteDryRunRequest, x_gateway_token: str | None = Header(default=None)) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:plan", tenant_id=payload.tenant_id)
    audit = _dry_run_audit_fields(actor=actor, tenant_id=payload.tenant_id, action=payload.action)

    target_server = registry.get(payload.server_id) if payload.server_id else None

    if payload.server_id and target_server is None:
        metrics.observe_dry_run("deny")
        result = {
            **audit,
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: target server not registered",
            "matched_rule": None,
            "selected_server_id": None,
            "server_healthy": None,
            "strategy": payload.strategy,
        }
        _store_audit_entry(result)
        return result

    if target_server and not target_server.healthy:
        metrics.observe_dry_run("deny")
        result = {
            **audit,
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: target server unhealthy",
            "matched_rule": None,
            "selected_server_id": target_server.server_id,
            "server_healthy": False,
            "strategy": payload.strategy,
        }
        _store_audit_entry(result)
        return result

    selected = target_server or registry.pick_server(
        tenant_id=payload.tenant_id,
        strategy=payload.strategy,
        preferred_server_id=payload.preferred_server_id,
        require_healthy=True,
    )

    if selected is None:
        metrics.observe_dry_run("deny")
        result = {
            **audit,
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: no healthy server available for tenant",
            "matched_rule": None,
            "selected_server_id": None,
            "server_healthy": None,
            "strategy": payload.strategy,
        }
        _store_audit_entry(result)
        return result

    request = PolicyRequest(
        action=payload.action,
        resource=f"gateway.server.{selected.server_id}",
        tenant_id=payload.tenant_id,
    )
    evaluation: PolicyEvaluation = policy.evaluate(request)
    metrics.observe_dry_run(evaluation.decision.value)

    result = {
        **audit,
        "allowed": evaluation.decision == PolicyDecision.ALLOW,
        "decision": evaluation.decision.value,
        "reason": evaluation.reason,
        "matched_rule": evaluation.matched_rule,
        "selected_server_id": selected.server_id,
        "server_healthy": selected.healthy,
        "strategy": payload.strategy,
    }
    _store_audit_entry(result)
    return result


@router.post("/routes/execute")
async def route_execute(
    payload: ExecuteRequest,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)

    # 1. Look up server from registry
    server = registry.get(payload.server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="Server not found")

    require_scope(actor, "gateway:execute", tenant_id=server.tenant_id)

    audit_id = str(uuid4())
    start = time.monotonic()

    # 2. Policy check
    policy_request = PolicyRequest(
        action=payload.method,
        resource=f"gateway.server.{server.server_id}",
        tenant_id=server.tenant_id,
    )
    evaluation: PolicyEvaluation = policy.evaluate(policy_request)
    policy_decision = {
        "decision": evaluation.decision.value,
        "reason": evaluation.reason,
        "matched_rule": evaluation.matched_rule,
    }

    if evaluation.decision != PolicyDecision.ALLOW:
        duration_ms = int((time.monotonic() - start) * 1000)
        result_payload: dict[str, Any] = {
            "server_id": payload.server_id,
            "method": payload.method,
            "status": "denied",
            "result": None,
            "policy_decision": policy_decision,
            "audit_id": audit_id,
            "duration_ms": duration_ms,
        }
        _store_execute_audit(audit_id, actor, server, payload, "denied", evaluation, None, duration_ms)
        return result_payload

    # 3. If dry_run, skip actual call
    if payload.dry_run:
        duration_ms = int((time.monotonic() - start) * 1000)
        result_payload = {
            "server_id": payload.server_id,
            "method": payload.method,
            "status": "allowed",
            "result": None,
            "policy_decision": policy_decision,
            "audit_id": audit_id,
            "duration_ms": duration_ms,
            "dry_run": True,
        }
        _store_execute_audit(audit_id, actor, server, payload, "allowed", evaluation, None, duration_ms)
        return result_payload

    # 4. Execute via transport adapter
    try:
        adapter = get_adapter(server.transport)
    except ValueError:
        duration_ms = int((time.monotonic() - start) * 1000)
        result_payload = {
            "server_id": payload.server_id,
            "method": payload.method,
            "status": "error",
            "result": None,
            "error": f"No adapter for transport: {server.transport}",
            "policy_decision": policy_decision,
            "audit_id": audit_id,
            "duration_ms": duration_ms,
        }
        _store_execute_audit(audit_id, actor, server, payload, "error", evaluation, None, duration_ms)
        return result_payload

    transport_result = await adapter.call(
        endpoint=server.endpoint,
        method=payload.method,
        params=payload.params,
        timeout=30,
    )
    duration_ms = int((time.monotonic() - start) * 1000)

    if transport_result["error"] is not None:
        status = "error"
    else:
        status = "allowed"

    result_payload = {
        "server_id": payload.server_id,
        "method": payload.method,
        "status": status,
        "result": transport_result["result"],
        "policy_decision": policy_decision,
        "audit_id": audit_id,
        "duration_ms": duration_ms,
    }
    if transport_result["error"] is not None:
        result_payload["error"] = transport_result["error"]

    _store_execute_audit(audit_id, actor, server, payload, status, evaluation, transport_result, duration_ms)
    return result_payload


def _store_execute_audit(
    audit_id: str,
    actor: AccessToken,
    server: Any,
    payload: ExecuteRequest,
    status: str,
    evaluation: PolicyEvaluation,
    transport_result: dict | None,
    duration_ms: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    full_payload = {
        "event_id": audit_id,
        "decided_at": now,
        "actor": {"subject_id": actor.subject_id, "role": actor.role, "tenant_id": actor.tenant_id},
        "request": {"tenant_id": server.tenant_id, "action": payload.method},
        "decision": evaluation.decision.value,
        "reason": evaluation.reason,
        "matched_rule": evaluation.matched_rule,
        "selected_server_id": server.server_id,
        "server_healthy": server.healthy,
        "strategy": "execute",
        "status": status,
        "duration_ms": duration_ms,
    }
    storage.execute(
        """
        INSERT INTO gateway_audit_log (
            event_id, decided_at, subject_id, role, tenant_id,
            action, decision, reason, matched_rule,
            selected_server_id, server_healthy, strategy, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            now,
            actor.subject_id,
            actor.role,
            server.tenant_id,
            payload.method,
            evaluation.decision.value,
            evaluation.reason,
            evaluation.matched_rule,
            server.server_id,
            1 if server.healthy else 0,
            "execute",
            json.dumps(full_payload),
        ),
    )


@router.get("/audit")
async def export_audit_log(
    tenant_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:read", tenant_id=tenant_id)

    if tenant_id:
        rows = storage.query_all(
            "SELECT payload_json FROM gateway_audit_log WHERE tenant_id = ? ORDER BY decided_at DESC LIMIT ?",
            (tenant_id, limit),
        )
    else:
        rows = storage.query_all(
            "SELECT payload_json FROM gateway_audit_log ORDER BY decided_at DESC LIMIT ?",
            (limit,),
        )

    return {"items": [json.loads(r["payload_json"]) for r in rows]}

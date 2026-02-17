from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from prometheus_client import generate_latest
from pydantic import BaseModel, Field

from .authz import AccessToken, AuthzStore, require_scope
from .observability import GatewayMetrics
from .policy import PolicyDecision, PolicyEngine, PolicyEvaluation, PolicyRequest, PolicyRule
from .registry import GatewayRegistry, RegisteredServer
from .storage import GatewayStorage
from .transports import validate_transport_endpoint

router = APIRouter(prefix="/gateway", tags=["gateway"])

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


class AccessTokenCreate(BaseModel):
    token: str
    subject_id: str
    tenant_id: str | None = None
    role: Literal["admin", "tenant-operator", "reader"] = "reader"
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = True
    expires_at: str | None = None


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


@router.post("/routes/dry-run")
async def route_dry_run(payload: RouteDryRunRequest, x_gateway_token: str | None = Header(default=None)) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:plan", tenant_id=payload.tenant_id)
    audit = _dry_run_audit_fields(actor=actor, tenant_id=payload.tenant_id, action=payload.action)

    target_server = registry.get(payload.server_id) if payload.server_id else None

    if payload.server_id and target_server is None:
        metrics.observe_dry_run("deny")
        return {
            **audit,
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: target server not registered",
            "matched_rule": None,
            "selected_server_id": None,
            "server_healthy": None,
            "strategy": payload.strategy,
        }

    if target_server and not target_server.healthy:
        metrics.observe_dry_run("deny")
        return {
            **audit,
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: target server unhealthy",
            "matched_rule": None,
            "selected_server_id": target_server.server_id,
            "server_healthy": False,
            "strategy": payload.strategy,
        }

    selected = target_server or registry.pick_server(
        tenant_id=payload.tenant_id,
        strategy=payload.strategy,
        preferred_server_id=payload.preferred_server_id,
        require_healthy=True,
    )

    if selected is None:
        metrics.observe_dry_run("deny")
        return {
            **audit,
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: no healthy server available for tenant",
            "matched_rule": None,
            "selected_server_id": None,
            "server_healthy": None,
            "strategy": payload.strategy,
        }

    request = PolicyRequest(
        action=payload.action,
        resource=f"gateway.server.{selected.server_id}",
        tenant_id=payload.tenant_id,
    )
    evaluation: PolicyEvaluation = policy.evaluate(request)
    metrics.observe_dry_run(evaluation.decision.value)

    return {
        **audit,
        "allowed": evaluation.decision == PolicyDecision.ALLOW,
        "decision": evaluation.decision.value,
        "reason": evaluation.reason,
        "matched_rule": evaluation.matched_rule,
        "selected_server_id": selected.server_id,
        "server_healthy": selected.healthy,
        "strategy": payload.strategy,
    }

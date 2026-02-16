from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response
from prometheus_client import generate_latest
from pydantic import BaseModel, Field

from .observability import GatewayMetrics
from .policy import PolicyDecision, PolicyEngine, PolicyEvaluation, PolicyRequest, PolicyRule
from .registry import GatewayRegistry, RegisteredServer
from .storage import GatewayStorage

router = APIRouter(prefix="/gateway", tags=["gateway"])

_DB_PATH = os.getenv(
    "MCP_GATEWAY_DB_PATH",
    str((Path(__file__).resolve().parents[2] / "data" / "gateway_control_plane.db")),
)
_ADMIN_TOKEN = os.getenv("MCP_GATEWAY_ADMIN_TOKEN", "dev-gateway-token")

storage = GatewayStorage(db_path=_DB_PATH)
registry = GatewayRegistry(storage=storage)
metrics = GatewayMetrics.create()
policy = PolicyEngine(storage=storage, default_decision=PolicyDecision.DENY)


def _require_admin_token(token: str | None) -> None:
    if token != _ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Admin token required")


class RegisterServerRequest(BaseModel):
    server_id: str
    name: str
    tenant_id: str
    transport: str = Field(description="stdio | sse | streamable-http | ws")
    endpoint: str
    tags: list[str] = Field(default_factory=list)


class RouteDryRunRequest(BaseModel):
    tenant_id: str
    action: str
    server_id: str


class PolicyRuleCreate(BaseModel):
    name: str
    effect: PolicyDecision
    actions: list[str]
    resources: list[str]
    tenants: list[str] | None = None


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
async def list_servers(tenant_id: str | None = None) -> dict:
    metrics.increment("gateway_servers_list")
    servers = registry.list_servers(tenant_id=tenant_id)
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
            }
            for s in servers
        ]
    }


@router.post("/servers")
async def register_server(payload: RegisterServerRequest, x_gateway_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_token(x_gateway_admin_token)
    metrics.increment("gateway_servers_register")
    record = RegisteredServer(
        server_id=payload.server_id,
        name=payload.name,
        endpoint=payload.endpoint,
        transport=payload.transport,
        tenant_id=payload.tenant_id,
        tags=payload.tags,
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
    }


@router.post("/servers/{server_id}/health")
async def set_server_health(
    server_id: str,
    healthy: bool = Query(...),
    x_gateway_admin_token: str | None = Header(default=None),
) -> dict:
    _require_admin_token(x_gateway_admin_token)
    if registry.get(server_id) is None:
        raise HTTPException(status_code=404, detail="Server not found")
    registry.set_health(server_id=server_id, healthy=healthy)
    return {"status": "ok", "server_id": server_id, "healthy": healthy}


@router.get("/policy/rules")
async def list_policy_rules() -> dict:
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
async def create_policy_rule(payload: PolicyRuleCreate, x_gateway_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_token(x_gateway_admin_token)
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
async def delete_policy_rule(name: str, x_gateway_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin_token(x_gateway_admin_token)
    policy.remove_rule(name)
    return {"status": "ok", "name": name}


@router.post("/routes/dry-run")
async def route_dry_run(payload: RouteDryRunRequest) -> dict:
    server = registry.get(payload.server_id)
    if server is None:
        metrics.observe_dry_run("deny")
        return {
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: target server not registered",
            "matched_rule": None,
            "server_healthy": None,
        }

    if not server.healthy:
        metrics.observe_dry_run("deny")
        return {
            "allowed": False,
            "decision": PolicyDecision.DENY.value,
            "reason": "deny: target server unhealthy",
            "matched_rule": None,
            "server_healthy": False,
        }

    request = PolicyRequest(
        action=payload.action,
        resource=f"gateway.server.{payload.server_id}",
        tenant_id=payload.tenant_id,
    )
    evaluation: PolicyEvaluation = policy.evaluate(request)
    metrics.observe_dry_run(evaluation.decision.value)

    return {
        "allowed": evaluation.decision == PolicyDecision.ALLOW,
        "decision": evaluation.decision.value,
        "reason": evaluation.reason,
        "matched_rule": evaluation.matched_rule,
        "server_healthy": True,
    }

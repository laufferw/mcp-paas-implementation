"""FastAPI routes for Code Mode."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from .api import _require_actor, authz, policy, storage
from .audit import AuditLogger
from .authz import require_scope
from .codemode import ApiClient, CodeModeExecutor
from .codemode_tools import CodeModeToolHandler

router = APIRouter(prefix="/codemode", tags=["codemode"])

audit = AuditLogger(storage=storage)
executor = CodeModeExecutor()
handler = CodeModeToolHandler(executor=executor, policy=policy, audit=audit)


class SearchRequest(BaseModel):
    code: str
    spec: dict


class ExecuteRequest(BaseModel):
    code: str
    server_id: str
    base_url: str
    headers: Dict[str, str] | None = None


@router.post("/search")
async def codemode_search(
    payload: SearchRequest,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:codemode:search")

    result = handler.handle_search(
        code=payload.code,
        spec=payload.spec,
        tenant_id=actor.tenant_id or "_global",
        subject_id=actor.subject_id,
    )
    return result


@router.post("/execute")
async def codemode_execute(
    payload: ExecuteRequest,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:codemode:execute")

    tenant_id = actor.tenant_id or "_global"
    api_client = ApiClient(
        base_url=payload.base_url,
        tenant_id=tenant_id,
        headers=payload.headers,
    )
    result = handler.handle_execute(
        code=payload.code,
        api_client=api_client,
        tenant_id=tenant_id,
        subject_id=actor.subject_id,
        server_id=payload.server_id,
    )
    return result


@router.get("/audit")
async def codemode_audit(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    require_scope(actor, "gateway:codemode:audit")

    tenant_id = actor.tenant_id or "_global"
    events = audit.list_events(tenant_id=tenant_id, limit=limit, offset=offset)
    return {
        "items": [
            {
                "event_id": e.event_id,
                "action": e.action,
                "code": e.code,
                "result": e.result,
                "error": e.error,
                "policy_decision": e.policy_decision,
                "status": e.status,
                "execution_ms": e.execution_ms,
                "created_at": e.created_at,
            }
            for e in events
        ]
    }


@router.post("/approve/{event_id}")
async def codemode_approve(
    event_id: str,
    x_gateway_token: str | None = Header(default=None),
) -> dict:
    actor = _require_actor(x_gateway_token)
    # Only admins can approve
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required for approval")

    event = audit.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")

    # We need an API client to execute — for now use a placeholder
    # In production, the base_url would be resolved from the server registry
    api_client = ApiClient(base_url="http://localhost", tenant_id=event.tenant_id)
    result = handler.approve_and_execute(event_id=event_id, api_client=api_client)
    return result

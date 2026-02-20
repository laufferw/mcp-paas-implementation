"""MCP-compatible tool schemas for Code Mode, wired through policy engine."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict

from .audit import AuditLogger
from .codemode import ApiClient, CodeModeExecutor, CodeResult
from .policy import PolicyDecision, PolicyEngine, PolicyRequest


# MCP tool schemas
SEARCH_TOOL_SCHEMA: Dict[str, Any] = {
    "name": "codemode_search",
    "description": "Execute Python code against an OpenAPI spec for progressive discovery. "
                   "The variable `spec` is available as a dict.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute against the spec"},
            "server_id": {"type": "string", "description": "Server whose spec to search"},
        },
        "required": ["code", "server_id"],
    },
}

EXECUTE_TOOL_SCHEMA: Dict[str, Any] = {
    "name": "codemode_execute",
    "description": "Execute Python code that can make API calls via a controlled client. "
                   "The variable `api` is available with get/post/put/delete methods.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "server_id": {"type": "string", "description": "Target server for API calls"},
        },
        "required": ["code", "server_id"],
    },
}


class CodeModeToolHandler:
    """Handles code mode tool calls with policy checks and audit logging."""

    def __init__(
        self,
        executor: CodeModeExecutor,
        policy: PolicyEngine,
        audit: AuditLogger,
    ) -> None:
        self.executor = executor
        self.policy = policy
        self.audit = audit

    def handle_search(
        self,
        code: str,
        spec: dict,
        tenant_id: str,
        subject_id: str,
    ) -> Dict[str, Any]:
        """Search an API spec. Always allowed (read-only)."""
        result = self.executor.search(code, spec)
        self.audit.log(
            tenant_id=tenant_id,
            subject_id=subject_id,
            action="search",
            code=code,
            result=json.dumps(result.output) if result.success else None,
            error=result.error,
            policy_decision="allow",
            execution_ms=result.execution_ms,
        )
        return _result_to_dict(result)

    def handle_execute(
        self,
        code: str,
        api_client: ApiClient,
        tenant_id: str,
        subject_id: str,
        server_id: str,
    ) -> Dict[str, Any]:
        """Execute code with policy gate and optional approval checkpoint."""
        # Policy check
        policy_req = PolicyRequest(
            action="codemode:execute",
            resource=f"gateway.server.{server_id}",
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        evaluation = self.policy.evaluate(policy_req)

        if evaluation.decision == PolicyDecision.DENY:
            event_id = self.audit.log(
                tenant_id=tenant_id,
                subject_id=subject_id,
                action="execute",
                code=code,
                policy_decision="deny",
                status="denied",
            )
            return {"success": False, "error": f"Policy denied: {evaluation.reason}", "event_id": event_id}

        # Check for approval-required rules (convention: rule name contains "approval")
        if evaluation.matched_rule and "approval" in evaluation.matched_rule.lower():
            event_id = self.audit.log(
                tenant_id=tenant_id,
                subject_id=subject_id,
                action="execute",
                code=code,
                policy_decision="pending_approval",
                status="pending_approval",
            )
            return {"success": False, "pending_approval": True, "event_id": event_id,
                    "message": "Execution requires approval before proceeding."}

        # Execute
        result = self.executor.execute(code, api_client, tenant_id)
        self.audit.log(
            tenant_id=tenant_id,
            subject_id=subject_id,
            action="execute",
            code=code,
            result=json.dumps(result.output) if result.success else None,
            error=result.error,
            policy_decision="allow",
            execution_ms=result.execution_ms,
        )
        return _result_to_dict(result)

    def approve_and_execute(
        self,
        event_id: str,
        api_client: ApiClient,
    ) -> Dict[str, Any]:
        """Approve a pending execution and run it."""
        event = self.audit.get_event(event_id)
        if event is None:
            return {"success": False, "error": "Event not found"}
        if event.status != "pending_approval":
            return {"success": False, "error": f"Event status is '{event.status}', not pending_approval"}

        result = self.executor.execute(event.code, api_client, event.tenant_id)
        self.audit.update_status(
            event_id,
            status="completed",
            result=json.dumps(result.output) if result.success else result.error,
            execution_ms=result.execution_ms,
        )
        resp = _result_to_dict(result)
        resp["event_id"] = event_id
        return resp


def _result_to_dict(result: CodeResult) -> Dict[str, Any]:
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "execution_ms": result.execution_ms,
    }

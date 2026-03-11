"""
AgentGate Claude Integration

Provides a GatewayClient class that Claude (or any agent) can use
to discover and call MCP servers through the gateway with full
policy enforcement and audit logging.
"""

from __future__ import annotations

from typing import Any

import httpx


class GatewayClient:
    """
    Python client for AgentGate. Use this to call MCP servers
    through the gateway from Claude or any Python agent.

    Example:
        client = GatewayClient(base_url="http://localhost:8000", token="my-token")
        servers = await client.list_servers()
        result = await client.execute("my-server", "tools/list", {})
    """

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._headers = {"x-gateway-token": token}

    async def list_servers(self) -> list[dict]:
        """List all registered MCP servers."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/gateway/servers",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json().get("items", [])

    async def execute(
        self,
        server_id: str,
        method: str,
        params: dict | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Execute an MCP method on a registered server."""
        payload: dict[str, Any] = {
            "server_id": server_id,
            "method": method,
            "params": params or {},
            "dry_run": dry_run,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/gateway/routes/execute",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def plan(
        self,
        server_id: str,
        method: str,
        params: dict | None = None,
    ) -> dict:
        """Dry-run route planning without execution."""
        return await self.execute(server_id, method, params, dry_run=True)

    async def get_audit_log(self, limit: int = 20) -> list[dict]:
        """Fetch recent audit log entries."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/gateway/audit",
                headers=self._headers,
                params={"limit": limit},
            )
            resp.raise_for_status()
            return resp.json().get("items", [])

    def as_tools(self) -> list[dict]:
        """
        Return OpenAI/Anthropic-compatible tool definitions for use
        in Claude or GPT tool_use calls. Returns 3 tools:
        - agentgate_list_servers
        - agentgate_execute
        - agentgate_audit_log
        """
        return [
            {
                "name": "agentgate_list_servers",
                "description": (
                    "List all MCP servers registered in the AgentGate gateway. "
                    "Returns server IDs, names, transport types, and health status."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "agentgate_execute",
                "description": (
                    "Execute an MCP method on a registered server through the "
                    "AgentGate gateway. The gateway enforces policy rules and "
                    "records an audit trail."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "server_id": {
                            "type": "string",
                            "description": "ID of the registered MCP server to call.",
                        },
                        "method": {
                            "type": "string",
                            "description": "MCP method to invoke (e.g. 'tools/list', 'tools/call').",
                        },
                        "params": {
                            "type": "object",
                            "description": "Parameters to pass to the MCP method.",
                            "default": {},
                        },
                    },
                    "required": ["server_id", "method"],
                },
            },
            {
                "name": "agentgate_audit_log",
                "description": (
                    "Fetch recent audit log entries from the AgentGate gateway. "
                    "Shows policy decisions, execution results, and actor details."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of audit entries to return.",
                            "default": 20,
                        },
                    },
                    "required": [],
                },
            },
        ]

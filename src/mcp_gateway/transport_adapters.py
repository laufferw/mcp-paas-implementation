"""Transport adapters that actually call MCP servers over various transports."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx


class TransportAdapter:
    """Base class for MCP transport adapters."""

    async def call(
        self, endpoint: str, method: str, params: dict, timeout: int = 30
    ) -> dict[str, Any]:
        raise NotImplementedError


class StreamableHTTPAdapter(TransportAdapter):
    """Calls MCP servers over streamable-http (POST JSON-RPC 2.0)."""

    async def call(
        self, endpoint: str, method: str, params: dict, timeout: int = 30
    ) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                body = resp.json()
                if "error" in body and body["error"] is not None:
                    return {"result": None, "error": body["error"]}
                return {"result": body.get("result"), "error": None}
        except httpx.HTTPStatusError as exc:
            return {"result": None, "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
        except httpx.RequestError as exc:
            return {"result": None, "error": f"Transport error: {exc}"}
        except Exception as exc:
            return {"result": None, "error": f"Unexpected error: {exc}"}


class SSEAdapter(TransportAdapter):
    """Calls MCP servers over SSE transport.

    Sends JSON-RPC via POST like streamable-http, but the server may
    respond with an SSE event stream.  We read lines until we get
    ``data: {...}`` containing a JSON-RPC response.
    """

    async def call(
        self, endpoint: str, method: str, params: dict, timeout: int = 30
    ) -> dict[str, Any]:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
                ) as resp:
                    resp.raise_for_status()
                    # If the response is plain JSON (not SSE), handle it directly
                    content_type = resp.headers.get("content-type", "")
                    if "application/json" in content_type:
                        body = json.loads(await resp.aread())
                        if "error" in body and body["error"] is not None:
                            return {"result": None, "error": body["error"]}
                        return {"result": body.get("result"), "error": None}

                    # Parse SSE stream for first data line with JSON-RPC response
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            try:
                                body = json.loads(data)
                                if "error" in body and body["error"] is not None:
                                    return {"result": None, "error": body["error"]}
                                return {"result": body.get("result"), "error": None}
                            except json.JSONDecodeError:
                                continue
                    return {"result": None, "error": "No JSON-RPC response in SSE stream"}
        except httpx.HTTPStatusError as exc:
            return {"result": None, "error": f"HTTP {exc.response.status_code}: {exc.response.text}"}
        except httpx.RequestError as exc:
            return {"result": None, "error": f"Transport error: {exc}"}
        except Exception as exc:
            return {"result": None, "error": f"Unexpected error: {exc}"}


class StdioAdapter(TransportAdapter):
    """Calls local MCP servers via stdio (subprocess).

    Spawns the command in *endpoint*, writes JSON-RPC to stdin,
    reads the response from stdout.
    """

    async def call(
        self, endpoint: str, method: str, params: dict, timeout: int = 30
    ) -> dict[str, Any]:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1,
        }) + "\n"
        try:
            proc = await asyncio.create_subprocess_shell(
                endpoint,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=payload.encode()),
                timeout=timeout,
            )
            if proc.returncode != 0:
                return {"result": None, "error": f"Process exited {proc.returncode}: {stderr.decode().strip()}"}
            body = json.loads(stdout.decode().strip())
            if "error" in body and body["error"] is not None:
                return {"result": None, "error": body["error"]}
            return {"result": body.get("result"), "error": None}
        except asyncio.TimeoutError:
            return {"result": None, "error": f"Stdio subprocess timed out after {timeout}s"}
        except json.JSONDecodeError as exc:
            return {"result": None, "error": f"Invalid JSON from subprocess: {exc}"}
        except Exception as exc:
            return {"result": None, "error": f"Unexpected error: {exc}"}


_ADAPTERS: dict[str, type[TransportAdapter]] = {
    "streamable-http": StreamableHTTPAdapter,
    "sse": SSEAdapter,
    "stdio": StdioAdapter,
}


def get_adapter(transport: str) -> TransportAdapter:
    """Factory: return the right adapter for a transport type."""
    cls = _ADAPTERS.get(transport)
    if cls is None:
        raise ValueError(f"No adapter for transport: {transport}")
    return cls()

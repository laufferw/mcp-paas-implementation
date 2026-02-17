from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException

SUPPORTED_TRANSPORTS = {"stdio", "sse", "streamable-http", "ws"}


def validate_transport_endpoint(transport: str, endpoint: str) -> None:
    if transport not in SUPPORTED_TRANSPORTS:
        raise HTTPException(status_code=400, detail=f"Unsupported transport: {transport}")

    if not endpoint.strip():
        raise HTTPException(status_code=400, detail="Endpoint is required")

    parsed = urlparse(endpoint)

    if transport == "stdio":
        # stdio endpoints represent local commands; reject URL-like endpoints.
        if parsed.scheme in {"http", "https", "ws", "wss"}:
            raise HTTPException(status_code=400, detail="stdio transport expects a local command, not URL")
        return

    if transport in {"sse", "streamable-http"}:
        if parsed.scheme not in {"http", "https"}:
            raise HTTPException(status_code=400, detail=f"{transport} transport requires http/https endpoint")
        return

    if transport == "ws":
        if parsed.scheme not in {"ws", "wss"}:
            raise HTTPException(status_code=400, detail="ws transport requires ws/wss endpoint")

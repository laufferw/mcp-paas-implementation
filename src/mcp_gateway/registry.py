from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .storage import GatewayStorage


@dataclass
class RegisteredServer:
    """Represents an MCP server known by the gateway."""

    server_id: str
    name: str
    endpoint: str
    transport: str = "http"
    tenant_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    healthy: bool = True
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GatewayRegistry:
    """SQLite-backed registry for server metadata."""

    def __init__(self, storage: GatewayStorage) -> None:
        self.storage = storage

    def register(self, server: RegisteredServer) -> RegisteredServer:
        self.storage.execute(
            """
            INSERT INTO gateway_servers(server_id, name, endpoint, transport, tenant_id, tags_json, healthy, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                name=excluded.name,
                endpoint=excluded.endpoint,
                transport=excluded.transport,
                tenant_id=excluded.tenant_id,
                tags_json=excluded.tags_json,
                healthy=excluded.healthy
            """,
            (
                server.server_id,
                server.name,
                server.endpoint,
                server.transport,
                server.tenant_id,
                json.dumps(server.tags),
                1 if server.healthy else 0,
                server.registered_at.isoformat(),
            ),
        )
        return server

    def set_health(self, server_id: str, healthy: bool) -> None:
        self.storage.execute(
            "UPDATE gateway_servers SET healthy = ? WHERE server_id = ?",
            (1 if healthy else 0, server_id),
        )

    def get(self, server_id: str) -> Optional[RegisteredServer]:
        row = self.storage.query_one("SELECT * FROM gateway_servers WHERE server_id = ?", (server_id,))
        if row is None:
            return None
        return self._row_to_server(row)

    def list_servers(self, tenant_id: str | None = None) -> List[RegisteredServer]:
        if tenant_id is None:
            rows = self.storage.query_all("SELECT * FROM gateway_servers ORDER BY server_id")
        else:
            rows = self.storage.query_all(
                "SELECT * FROM gateway_servers WHERE tenant_id = ? ORDER BY server_id",
                (tenant_id,),
            )
        return [self._row_to_server(r) for r in rows]

    @staticmethod
    def _row_to_server(row) -> RegisteredServer:
        return RegisteredServer(
            server_id=row["server_id"],
            name=row["name"],
            endpoint=row["endpoint"],
            transport=row["transport"],
            tenant_id=row["tenant_id"],
            tags=json.loads(row["tags_json"] or "[]"),
            healthy=bool(row["healthy"]),
            registered_at=datetime.fromisoformat(row["registered_at"]),
        )

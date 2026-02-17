from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from random import Random
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
    weight: int = 1
    priority: int = 100
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GatewayRegistry:
    """SQLite-backed registry for server metadata."""

    def __init__(self, storage: GatewayStorage) -> None:
        self.storage = storage
        self._rng = Random(42)

    def register(self, server: RegisteredServer) -> RegisteredServer:
        self.storage.execute(
            """
            INSERT INTO gateway_servers(server_id, name, endpoint, transport, tenant_id, tags_json, healthy, weight, priority, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                name=excluded.name,
                endpoint=excluded.endpoint,
                transport=excluded.transport,
                tenant_id=excluded.tenant_id,
                tags_json=excluded.tags_json,
                healthy=excluded.healthy,
                weight=excluded.weight,
                priority=excluded.priority
            """,
            (
                server.server_id,
                server.name,
                server.endpoint,
                server.transport,
                server.tenant_id,
                json.dumps(server.tags),
                1 if server.healthy else 0,
                max(1, server.weight),
                server.priority,
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

    def pick_server(
        self,
        tenant_id: str,
        strategy: str,
        preferred_server_id: str | None = None,
        require_healthy: bool = True,
    ) -> Optional[RegisteredServer]:
        servers = self.list_servers(tenant_id=tenant_id)
        if require_healthy:
            servers = [s for s in servers if s.healthy]

        if not servers:
            return None

        if preferred_server_id:
            preferred = next((s for s in servers if s.server_id == preferred_server_id), None)
            if preferred is not None:
                return preferred

        if strategy == "failover":
            return sorted(servers, key=lambda s: (s.priority, s.server_id))[0]

        # weighted default strategy
        if strategy == "weighted":
            total = sum(max(1, s.weight) for s in servers)
            pick = self._rng.randint(1, total)
            cur = 0
            for s in servers:
                cur += max(1, s.weight)
                if pick <= cur:
                    return s

        # preferred/unrecognized fallback: deterministic first healthy by id.
        return sorted(servers, key=lambda s: s.server_id)[0]

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
            weight=int(row["weight"]),
            priority=int(row["priority"]),
            registered_at=datetime.fromisoformat(row["registered_at"]),
        )

from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any, Iterable


class GatewayStorage:
    """SQLite-backed storage for gateway control-plane state."""

    def __init__(self, db_path: str = "data/gateway_control_plane.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_servers (
                    server_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    transport TEXT NOT NULL,
                    tenant_id TEXT,
                    tags_json TEXT NOT NULL,
                    healthy INTEGER NOT NULL DEFAULT 1,
                    registered_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_policy_rules (
                    name TEXT PRIMARY KEY,
                    effect TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    resources_json TEXT NOT NULL,
                    tenants_json TEXT
                )
                """
            )
            conn.commit()

    def execute(self, query: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(query, tuple(params))
                conn.commit()

    def query_all(self, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(query, tuple(params)).fetchall()
        return rows

    def query_one(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(query, tuple(params)).fetchone()
        return row

"""Audit trail for Code Mode executions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from .storage import GatewayStorage


@dataclass
class AuditEvent:
    event_id: str
    tenant_id: str
    subject_id: str
    action: str  # "search" | "execute"
    code: str
    result: Optional[str]
    error: Optional[str]
    policy_decision: str  # "allow" | "deny" | "pending_approval"
    execution_ms: float
    created_at: str
    status: str = "completed"  # "completed" | "pending_approval" | "denied"


class AuditLogger:
    """SQLite-backed audit logger for code mode operations."""

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS codemode_audit (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            action TEXT NOT NULL,
            code TEXT NOT NULL,
            result TEXT,
            error TEXT,
            policy_decision TEXT NOT NULL,
            execution_ms REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL
        )
    """

    def __init__(self, storage: GatewayStorage) -> None:
        self.storage = storage
        self.storage.execute(self._SCHEMA)

    def log(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        action: str,
        code: str,
        result: str | None = None,
        error: str | None = None,
        policy_decision: str = "allow",
        execution_ms: float = 0.0,
        status: str = "completed",
    ) -> str:
        event_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self.storage.execute(
            """INSERT INTO codemode_audit
               (event_id, tenant_id, subject_id, action, code, result, error,
                policy_decision, execution_ms, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, tenant_id, subject_id, action, code, result, error,
             policy_decision, execution_ms, status, now),
        )
        return event_id

    def get_event(self, event_id: str) -> AuditEvent | None:
        row = self.storage.query_one(
            "SELECT * FROM codemode_audit WHERE event_id = ?", (event_id,)
        )
        if row is None:
            return None
        return self._row_to_event(row)

    def update_status(self, event_id: str, status: str, result: str | None = None, execution_ms: float = 0.0) -> None:
        if result is not None:
            self.storage.execute(
                "UPDATE codemode_audit SET status = ?, result = ?, execution_ms = ? WHERE event_id = ?",
                (status, result, execution_ms, event_id),
            )
        else:
            self.storage.execute(
                "UPDATE codemode_audit SET status = ? WHERE event_id = ?",
                (status, event_id),
            )

    def list_events(self, tenant_id: str, limit: int = 50, offset: int = 0) -> list[AuditEvent]:
        rows = self.storage.query_all(
            "SELECT * FROM codemode_audit WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (tenant_id, limit, offset),
        )
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row: Any) -> AuditEvent:
        return AuditEvent(
            event_id=row["event_id"],
            tenant_id=row["tenant_id"],
            subject_id=row["subject_id"],
            action=row["action"],
            code=row["code"],
            result=row["result"],
            error=row["error"],
            policy_decision=row["policy_decision"],
            execution_ms=row["execution_ms"],
            status=row["status"],
            created_at=row["created_at"],
        )

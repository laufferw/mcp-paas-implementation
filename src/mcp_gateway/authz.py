from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Set

from fastapi import HTTPException

from .storage import GatewayStorage


@dataclass(frozen=True)
class AccessToken:
    token: str
    subject_id: str
    role: str
    tenant_id: str | None = None
    scopes: Set[str] = field(default_factory=set)
    enabled: bool = True
    expires_at: str | None = None
    revoked_at: str | None = None


class AuthzStore:
    def __init__(self, storage: GatewayStorage) -> None:
        self.storage = storage

    def upsert_token(self, token: AccessToken) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.storage.execute(
            """
            INSERT INTO gateway_access_tokens(
                token, subject_id, tenant_id, role, scopes_json, enabled, created_at, expires_at, revoked_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET
                subject_id=excluded.subject_id,
                tenant_id=excluded.tenant_id,
                role=excluded.role,
                scopes_json=excluded.scopes_json,
                enabled=excluded.enabled,
                expires_at=excluded.expires_at,
                revoked_at=excluded.revoked_at,
                updated_at=excluded.updated_at
            """,
            (
                token.token,
                token.subject_id,
                token.tenant_id,
                token.role,
                json.dumps(sorted(token.scopes)),
                1 if token.enabled else 0,
                now,
                token.expires_at,
                token.revoked_at,
                now,
            ),
        )

    def get_token(self, raw_token: str) -> AccessToken | None:
        row = self.storage.query_one(
            "SELECT * FROM gateway_access_tokens WHERE token = ?",
            (raw_token,),
        )
        if row is None:
            return None
        return AccessToken(
            token=row["token"],
            subject_id=row["subject_id"],
            role=row["role"],
            tenant_id=row["tenant_id"],
            scopes=set(json.loads(row["scopes_json"] or "[]")),
            enabled=bool(row["enabled"]),
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
        )

    def revoke_token(self, raw_token: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.storage.query_one("SELECT token FROM gateway_access_tokens WHERE token = ?", (raw_token,))
        if existing is None:
            return False
        self.storage.execute(
            """
            UPDATE gateway_access_tokens
            SET enabled = 0, revoked_at = ?, updated_at = ?
            WHERE token = ?
            """,
            (now, now, raw_token),
        )
        return True


def require_scope(token: AccessToken, scope: str, tenant_id: str | None = None) -> None:
    if not token.enabled:
        raise HTTPException(status_code=403, detail="Token disabled")

    if token.revoked_at:
        raise HTTPException(status_code=403, detail="Token revoked")

    if token.expires_at:
        expires = datetime.fromisoformat(token.expires_at.replace("Z", "+00:00"))
        if datetime.now(timezone.utc) >= expires:
            raise HTTPException(status_code=403, detail="Token expired")

    if token.role == "admin":
        return

    if scope not in token.scopes and "gateway:*" not in token.scopes:
        raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")

    if tenant_id is not None and token.tenant_id not in (None, tenant_id):
        raise HTTPException(status_code=403, detail="Token not permitted for tenant")

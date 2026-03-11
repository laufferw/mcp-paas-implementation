#!/usr/bin/env python3
"""Gateway DB migration script.

Ensures the SQLite gateway control-plane schema is up to date.
Safe to run repeatedly — all DDL uses CREATE TABLE IF NOT EXISTS and
ALTER TABLE ADD COLUMN with column-existence checks.

Usage:
    python scripts/migrate.py                         # default path
    MCP_GATEWAY_DB_PATH=./data/gw.db python scripts/migrate.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_gateway.storage import GatewayStorage  # noqa: E402


def main() -> None:
    db_path = os.getenv(
        "MCP_GATEWAY_DB_PATH",
        str(Path(__file__).resolve().parents[1] / "data" / "gateway_control_plane.db"),
    )
    print(f"[migrate] Ensuring gateway schema at: {db_path}")
    storage = GatewayStorage(db_path=db_path)

    # Verify tables exist
    tables = [r[0] for r in storage.query_all("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    expected = {"gateway_servers", "gateway_policy_rules", "gateway_access_tokens", "gateway_audit_log"}
    present = expected & set(tables)
    missing = expected - set(tables)

    print(f"[migrate] Tables present: {sorted(present)}")
    if missing:
        print(f"[migrate] WARNING: missing tables (re-run or check storage.py): {sorted(missing)}")
    else:
        print("[migrate] All gateway tables verified.")

    # Report row counts
    for table in sorted(present):
        count = storage.query_one(f"SELECT count(*) as cnt FROM {table}")  # noqa: S608
        print(f"  {table}: {count['cnt']} rows")

    print("[migrate] Done.")


if __name__ == "__main__":
    main()

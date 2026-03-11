#!/usr/bin/env python3
"""
Finance stub demo — exercises the AgentGate control plane end-to-end.

Steps:
  1. Boot the gateway server (in-process TestClient)
  2. Create an admin token (bootstrapped)
  3. Create a tenant token with finance scopes
  4. Register a mock finance MCP server
  5. Run a dry-run route plan (allow path)
  6. Run a dry-run route plan (deny path — no matching rule)
  7. Export the audit log
  8. Print a clean summary
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

FIXTURES = json.loads((Path(__file__).parent / "fixtures.json").read_text())


def _banner(msg: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {msg}")
    print(f"{'=' * 60}")


def main() -> None:
    _banner("AgentGate Finance Stub Demo")

    # --- Setup: isolated DB + TestClient ---
    tmp = tempfile.mkdtemp(prefix="agentgate-demo-")
    db_path = os.path.join(tmp, "demo.db")
    admin_token = "demo-admin-token"

    os.environ["MCP_GATEWAY_DB_PATH"] = db_path
    os.environ["MCP_GATEWAY_ADMIN_TOKEN"] = admin_token

    # Force fresh module load
    for mod in [k for k in sys.modules if k.startswith("mcp_gateway")]:
        del sys.modules[mod]

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api_module = importlib.import_module("mcp_gateway.api")
    app = FastAPI()
    app.include_router(api_module.router)
    client = TestClient(app)

    results: list[dict] = []

    def _step(label: str, method: str, path: str, **kwargs) -> dict:
        fn = getattr(client, method)
        resp = fn(path, **kwargs)
        entry = {"step": label, "status": resp.status_code, "body": resp.json()}
        results.append(entry)
        status_icon = "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}"
        print(f"  [{status_icon}] {label}")
        return entry

    # --- Step 1: Health check ---
    _banner("Step 1 — Health check")
    _step("health", "get", "/gateway/health")

    # --- Step 2: Admin token already bootstrapped ---
    print("\n  Admin token bootstrapped via MCP_GATEWAY_ADMIN_TOKEN")

    # --- Step 3: Create tenant token with finance scopes ---
    _banner("Step 3 — Create tenant token")
    _step(
        "create-tenant-token",
        "post",
        "/gateway/access/tokens",
        json={
            "token": "finance-tenant-token",
            "subject_id": "finance-ops",
            "tenant_id": "finance-co",
            "role": "tenant-operator",
            "scopes": ["gateway:read", "gateway:write", "gateway:plan"],
        },
        headers={"x-gateway-token": admin_token},
    )

    # --- Step 4: Register mock finance MCP server ---
    _banner("Step 4 — Register finance MCP server")
    _step(
        "register-server",
        "post",
        "/gateway/servers",
        json={
            "server_id": "finance-recon-srv",
            "name": "Finance Reconciliation MCP",
            "tenant_id": "finance-co",
            "transport": "sse",
            "endpoint": "https://mcp.finance-co.internal/recon",
            "tags": ["finance", "reconciliation"],
            "weight": 10,
            "priority": 1,
        },
        headers={"x-gateway-token": "finance-tenant-token"},
    )

    # --- Step 5: Create allow rule + dry-run (allow path) ---
    _banner("Step 5 — Dry-run: ALLOW path")
    _step(
        "create-allow-rule",
        "post",
        "/gateway/policy/rules",
        json={
            "name": "allow-recon-plan",
            "effect": "allow",
            "actions": ["plan"],
            "resources": ["gateway.server.finance-recon-srv"],
            "tenants": ["finance-co"],
        },
        headers={"x-gateway-token": admin_token},
    )
    allow_result = _step(
        "dry-run-allow",
        "post",
        "/gateway/routes/dry-run",
        json={
            "tenant_id": "finance-co",
            "action": "plan",
            "server_id": "finance-recon-srv",
        },
        headers={"x-gateway-token": "finance-tenant-token"},
    )

    # --- Step 6: Dry-run (deny path — execute action has no allow rule) ---
    _banner("Step 6 — Dry-run: DENY path")
    deny_result = _step(
        "dry-run-deny",
        "post",
        "/gateway/routes/dry-run",
        json={
            "tenant_id": "finance-co",
            "action": "execute",
            "server_id": "finance-recon-srv",
        },
        headers={"x-gateway-token": "finance-tenant-token"},
    )

    # --- Step 7: Export audit log ---
    _banner("Step 7 — Export audit log")
    audit = _step(
        "audit-export",
        "get",
        "/gateway/audit",
        params={"tenant_id": "finance-co"},
        headers={"x-gateway-token": admin_token},
    )

    # --- Summary ---
    _banner("SUMMARY")
    print(f"\n  Fixture scenario : {FIXTURES['scenario']}")
    print(f"  Accounts loaded  : {len(FIXTURES['accounts'])}")
    matched = sum(1 for a in FIXTURES["accounts"] if a["status"] == "matched")
    discrepancy = sum(1 for a in FIXTURES["accounts"] if a["status"] == "discrepancy")
    print(f"  Matched          : {matched}")
    print(f"  Discrepancies    : {discrepancy}")

    allow_body = allow_result["body"]
    deny_body = deny_result["body"]
    print(f"\n  Dry-run ALLOW    : decision={allow_body['decision']}, "
          f"server={allow_body.get('selected_server_id')}, "
          f"rule={allow_body.get('matched_rule')}")
    print(f"  Dry-run DENY     : decision={deny_body['decision']}, "
          f"reason={deny_body.get('reason')}")

    audit_items = audit["body"].get("items", [])
    print(f"\n  Audit entries    : {len(audit_items)}")
    for entry in audit_items:
        print(f"    - {entry['event_id'][:12]}... "
              f"action={entry['request']['action']} "
              f"decision={entry['decision']}")

    print(f"\n  All {len(results)} steps completed successfully.")
    print(f"  DB path: {db_path}\n")


if __name__ == "__main__":
    main()

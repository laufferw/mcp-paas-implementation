#!/usr/bin/env python3
"""
End-to-end demo of MCP Gateway Code Mode.

Prerequisites:
  - Server running: uvicorn server:app --host 0.0.0.0 --port 8000
  - pip install httpx

This script:
  1. Loads the QuickBooks sample spec
  2. Creates policy rules and access tokens
  3. Searches the spec for invoice endpoints
  4. Executes a GET (allowed by policy)
  5. Executes a POST /journal-entries (requires approval)
  6. Shows the audit trail
"""

import json
import sys
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
GATEWAY = f"{BASE}/gateway"

# ── Helpers ──────────────────────────────────────────────────────────────

def heading(msg: str):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def pp(data):
    print(json.dumps(data, indent=2, default=str))


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    client = httpx.Client(timeout=30)

    # ── Step 1: Load the QuickBooks sample spec ──────────────────────────
    heading("Step 1: Load QuickBooks sample OpenAPI spec")
    spec_path = Path(__file__).resolve().parent.parent / "docs" / "specs" / "quickbooks-sample.json"
    spec = json.loads(spec_path.read_text())
    print(f"Loaded spec: {spec['info']['title']} v{spec['info']['version']}")
    print(f"Endpoints: {len(spec['paths'])} paths")

    # ── Step 2: Create policy rules and access token ─────────────────────
    heading("Step 2: Create policy rules + access token via gateway API")

    # Create a finance-operator policy rule (journals need approval)
    rule_payload = {
        "rule_id": "demo-operator-journals",
        "name": "Journal entries require approval",
        "resource": "codemode:execute",
        "action": "execute",
        "effect": "approve",
        "conditions": {"http_method": "POST", "path_pattern": "/journal-entries"},
    }
    r = client.post(f"{GATEWAY}/policies/rules", json=rule_payload)
    print(f"Create policy rule: {r.status_code}")
    if r.status_code in (200, 201):
        pp(r.json())
    else:
        print(f"  (may already exist or endpoint differs — {r.text[:200]})")

    # Create an access token with codemode scopes
    token_payload = {
        "tenant_id": "demo-tenant",
        "subject_id": "operator@example.com",
        "role": "operator",
        "scopes": [
            "gateway:codemode:search",
            "gateway:codemode:execute",
            "gateway:codemode:audit",
        ],
    }
    r = client.post(f"{GATEWAY}/tokens", json=token_payload)
    if r.status_code in (200, 201):
        token_data = r.json()
        token = token_data.get("token") or token_data.get("access_token", "")
        print(f"Access token created: {token[:20]}...")
    else:
        print(f"Token creation: {r.status_code} — {r.text[:200]}")
        print("Using fallback header approach...")
        token = "demo-fallback"

    headers = {"X-Gateway-Token": token}

    # ── Step 3: Search the spec for invoice endpoints ────────────────────
    heading("Step 3: Search spec — find invoice endpoints")

    search_code = """
# Find all invoice-related endpoints
results = []
for path, methods in spec.get('paths', {}).items():
    if 'invoice' in path.lower():
        for method in methods:
            results.append(f"{method.upper()} {path}")
results
"""
    r = client.post(
        f"{GATEWAY}/codemode/search",
        json={"code": search_code, "spec": spec},
        headers=headers,
    )
    print(f"Search response ({r.status_code}):")
    if r.status_code == 200:
        pp(r.json())
    else:
        print(f"  Error: {r.text[:300]}")

    # ── Step 4: Execute a GET (allowed) ──────────────────────────────────
    heading("Step 4: Execute GET /invoices (should be allowed)")

    execute_code = """
response = api_client.get('/invoices', params={'per_page': 5})
response
"""
    r = client.post(
        f"{GATEWAY}/codemode/execute",
        json={
            "code": execute_code,
            "server_id": "quickbooks-demo",
            "base_url": "https://httpbin.org",  # placeholder
            "headers": {"Authorization": "Bearer demo"},
        },
        headers=headers,
    )
    print(f"Execute response ({r.status_code}):")
    if r.status_code == 200:
        pp(r.json())
    else:
        print(f"  Error: {r.text[:300]}")

    # ── Step 5: Execute POST /journal-entries (needs approval) ───────────
    heading("Step 5: Execute POST /journal-entries (should require approval)")

    journal_code = """
entry = {
    "date": "2026-01-31",
    "memo": "Month-end close adjustment",
    "lines": [
        {"account_id": "acct_5000", "debit": {"amount": 1500.00}},
        {"account_id": "acct_2000", "credit": {"amount": 1500.00}},
    ]
}
response = api_client.post('/journal-entries', json=entry)
response
"""
    r = client.post(
        f"{GATEWAY}/codemode/execute",
        json={
            "code": journal_code,
            "server_id": "quickbooks-demo",
            "base_url": "https://httpbin.org",
            "headers": {"Authorization": "Bearer demo"},
        },
        headers=headers,
    )
    print(f"Execute response ({r.status_code}):")
    if r.status_code == 200:
        result = r.json()
        pp(result)
        if result.get("status") == "pending_approval":
            print("\n✅ Correctly flagged for approval!")
    else:
        print(f"  Response: {r.text[:300]}")

    # ── Step 6: Show audit trail ─────────────────────────────────────────
    heading("Step 6: Audit trail")

    r = client.get(
        f"{GATEWAY}/codemode/audit",
        params={"limit": 10},
        headers=headers,
    )
    print(f"Audit trail ({r.status_code}):")
    if r.status_code == 200:
        items = r.json().get("items", [])
        for i, event in enumerate(items):
            print(f"\n  [{i+1}] {event.get('action', '?')} — status={event.get('status', '?')}")
            print(f"      policy: {event.get('policy_decision', '?')}")
            if event.get("code"):
                first_line = event["code"].strip().split("\n")[0]
                print(f"      code: {first_line}...")
    else:
        print(f"  Error: {r.text[:300]}")

    heading("Demo complete!")
    print("The Code Mode prototype demonstrates:")
    print("  • Sandboxed code search against OpenAPI specs")
    print("  • Policy-gated execution with approval checkpoints")
    print("  • Full audit trail for compliance")


if __name__ == "__main__":
    main()

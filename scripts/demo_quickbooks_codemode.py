#!/usr/bin/env python3
"""
Code Mode vs. Full-Spec: QuickBooks Online V3 (166 endpoints, 1.1 MB)

Demonstrates that an AI agent can navigate a REAL, large OpenAPI spec
using Code Mode's sandboxed search — consuming ~1 000 tokens instead of
the ~300 000 tokens required to stuff the entire spec into context.

No live QBO credentials are needed.  The script loads the real spec from
disk and runs searches + a mock execute locally via CodeModeExecutor.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_gateway.codemode import CodeModeExecutor, ApiClient

# ── Helpers ──────────────────────────────────────────────────────────────

def heading(msg: str):
    print(f"\n{'═'*64}")
    print(f"  {msg}")
    print(f"{'═'*64}")

def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (GPT-family heuristic)."""
    return len(text) // 4

def pp(obj):
    if isinstance(obj, str):
        print(obj)
    else:
        print(json.dumps(obj, indent=2, default=str)[:2000])

# ── Main ─────────────────────────────────────────────────────────────────

def main():
    spec_path = Path(__file__).resolve().parent.parent / "docs" / "specs" / "quickbooks-online-v3.json"
    if not spec_path.exists():
        print(f"ERROR: spec not found at {spec_path}")
        sys.exit(1)

    raw = spec_path.read_text()
    spec = json.loads(raw)
    executor = CodeModeExecutor()

    full_spec_tokens = estimate_tokens(raw)
    codemode_tokens_total = 0

    heading("QuickBooks Online V3 — Spec Overview")
    path_count = len(spec.get("paths", {}))
    schema_count = len(spec.get("components", {}).get("schemas", {}))
    print(f"  Title       : {spec.get('info',{}).get('title','?')}")
    print(f"  Version     : {spec.get('info',{}).get('version','?')}")
    print(f"  Paths       : {path_count}")
    print(f"  Schemas     : {schema_count}")
    print(f"  Spec size   : {len(raw):,} bytes")
    print(f"  Est. tokens : {full_spec_tokens:,}")

    # ── Policy rules (read-only for safety) ──────────────────────────────
    heading("Policy: read-only mode")
    print("  Rule: ALLOW  GET *")
    print("  Rule: DENY   POST/PUT/DELETE *  (demo safety)")
    print("  Rule: APPROVE POST /journal-entries (requires human sign-off)")

    # ── Search 1: invoice endpoints ──────────────────────────────────────
    heading("Search 1 — Find all invoice-related endpoints")

    code1 = """\
results = []
for path, methods in spec.get('paths', {}).items():
    if 'invoice' in path.lower():
        for method, detail in methods.items():
            if method in ('get','post','put','delete','patch'):
                summary = ''
                if isinstance(detail, dict):
                    summary = detail.get('summary', detail.get('operationId', ''))
                results.append(f"{method.upper():7s} {path}  — {summary}")
result = results
"""
    r1 = executor.search(code1, spec)
    search1_tokens = estimate_tokens(code1 + json.dumps(r1.output, default=str))
    codemode_tokens_total += search1_tokens
    print(f"  Execution: {r1.execution_ms:.1f} ms | Tokens used: ~{search1_tokens:,}")
    if r1.success:
        for line in (r1.output if isinstance(r1.output, list) else [r1.output]):
            print(f"    {line}")
    else:
        print(f"  ERROR: {r1.error}")

    # ── Search 2: invoice creation schema ────────────────────────────────
    heading("Search 2 — Schema for creating an Invoice")

    code2 = """\
# Find the POST /invoice* path and extract the request body schema ref
results = {}
for path, methods in spec.get('paths', {}).items():
    if 'invoice' in path.lower():
        for method in ('post',):
            if method in methods:
                op = methods[method]
                body = op.get('requestBody', {})
                content = body.get('content', {})
                for media, media_obj in content.items():
                    schema = media_obj.get('schema', {})
                    results[f"{method.upper()} {path}"] = {
                        'media_type': media,
                        'schema_ref': schema.get('$ref', schema),
                    }

# Resolve one level of $ref for the first hit
schemas = spec.get('components', {}).get('schemas', {})
for key, info in results.items():
    ref = info.get('schema_ref', '')
    if isinstance(ref, str) and ref.startswith('#/components/schemas/'):
        name = ref.split('/')[-1]
        if name in schemas:
            props = schemas[name].get('properties', {})
            info['fields'] = list(props.keys())[:20]
            info['required'] = schemas[name].get('required', [])
result = results
"""
    r2 = executor.search(code2, spec)
    search2_tokens = estimate_tokens(code2 + json.dumps(r2.output, default=str))
    codemode_tokens_total += search2_tokens
    print(f"  Execution: {r2.execution_ms:.1f} ms | Tokens used: ~{search2_tokens:,}")
    if r2.success:
        pp(r2.output)
    else:
        print(f"  ERROR: {r2.error}")

    # ── Search 3: month-end close endpoints ──────────────────────────────
    heading("Search 3 — Reports + journal entries for month-end close")

    code3 = """\
keywords = ['report', 'journal', 'balance', 'profit', 'trial', 'ledger', 'account']
results = []
for path, methods in spec.get('paths', {}).items():
    pl = path.lower()
    matched = False
    for k in keywords:
        if k in pl:
            matched = True
    if matched:
        for method, detail in methods.items():
            if method in ('get','post','put','delete','patch'):
                summary = ''
                if isinstance(detail, dict):
                    summary = detail.get('summary', detail.get('operationId', ''))
                results.append(f"{method.upper():7s} {path}  — {summary}")
result = sorted(set(results))
"""
    r3 = executor.search(code3, spec)
    search3_tokens = estimate_tokens(code3 + json.dumps(r3.output, default=str))
    codemode_tokens_total += search3_tokens
    print(f"  Execution: {r3.execution_ms:.1f} ms | Tokens used: ~{search3_tokens:,}")
    if r3.success:
        for line in (r3.output if isinstance(r3.output, list) else [r3.output]):
            print(f"    {line}")
    else:
        print(f"  ERROR: {r3.error}")

    # ── Mock execute: build a QBO query ──────────────────────────────────
    heading("Mock Execute — Construct a QBO query for open invoices")

    exec_code = """\
# Construct a QBO query (would hit the real API with credentials)
entity = "Invoice"
where = "Balance > '0' AND TxnDate >= '2026-01-01'"
query = f"select * from {entity} where {where} maxresults 100"
result = {
    "action": "query",
    "endpoint": "GET /v3/company/{realm_id}/query",
    "query_string": query,
    "note": "Mock — no live API call made",
}
"""
    # Use search (spec-only) since we don't have live credentials
    r4 = executor.search(exec_code, spec)
    exec_tokens = estimate_tokens(exec_code + json.dumps(r4.output, default=str))
    codemode_tokens_total += exec_tokens
    print(f"  Execution: {r4.execution_ms:.1f} ms | Tokens used: ~{exec_tokens:,}")
    if r4.success:
        pp(r4.output)
    else:
        print(f"  ERROR: {r4.error}")

    # ── Token comparison ─────────────────────────────────────────────────
    heading("Token Savings — Full Spec vs Code Mode")

    savings_pct = (1 - codemode_tokens_total / full_spec_tokens) * 100

    print(f"  Full spec in context : {full_spec_tokens:>10,} tokens")
    print(f"  Code Mode (4 calls)  : {codemode_tokens_total:>10,} tokens")
    print(f"  Savings              : {savings_pct:>9.1f}%")
    print()
    print(f"  That's a {full_spec_tokens / max(codemode_tokens_total, 1):.0f}× reduction.")
    print()
    print("  An agent using Code Mode can navigate 166 endpoints")
    print("  with the same token budget as a short chat message.")

    heading("Demo complete ✓")


if __name__ == "__main__":
    main()

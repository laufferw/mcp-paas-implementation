#!/usr/bin/env python3
"""
Month-End Close / Reconciliation Workflow

Demonstrates the full MCP Gateway Code Mode use case for finance:
  1. Discover relevant QBO endpoints via spec search
  2. Pull invoice + payment summaries (mock data)
  3. Calculate discrepancies
  4. Generate a correcting journal entry
  5. Policy checkpoint — flag for approval
  6. Produce audit trail + reconciliation report

Runs entirely offline (no QBO credentials needed).
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mcp_gateway.codemode import CodeModeExecutor

# ── Config ───────────────────────────────────────────────────────────────

PERIOD = "2026-01"
PERIOD_START = "2026-01-01"
PERIOD_END = "2026-01-31"

# ── Helpers ──────────────────────────────────────────────────────────────

def heading(msg: str):
    print(f"\n{'━'*64}")
    print(f"  {msg}")
    print(f"{'━'*64}")

def subheading(msg: str):
    print(f"\n  ── {msg} {'─'*(56 - len(msg))}")

# ── Audit log ────────────────────────────────────────────────────────────

@dataclass
class AuditEntry:
    timestamp: str
    action: str
    detail: str
    policy_decision: str = "n/a"
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

audit_trail: List[AuditEntry] = []

def audit(action: str, detail: str, decision: str = "n/a"):
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat() + "Z",
        action=action,
        detail=detail,
        policy_decision=decision,
    )
    audit_trail.append(entry)
    return entry

# ── Mock data ────────────────────────────────────────────────────────────

MOCK_INVOICES = [
    {"Id": "INV-1001", "Customer": "Acme Corp", "TotalAmt": 12_500.00, "Balance": 0.00, "TxnDate": "2026-01-05"},
    {"Id": "INV-1002", "Customer": "Globex Inc", "TotalAmt": 8_750.00, "Balance": 8_750.00, "TxnDate": "2026-01-12"},
    {"Id": "INV-1003", "Customer": "Initech LLC", "TotalAmt": 3_200.00, "Balance": 0.00, "TxnDate": "2026-01-18"},
    {"Id": "INV-1004", "Customer": "Umbrella Co", "TotalAmt": 15_000.00, "Balance": 5_000.00, "TxnDate": "2026-01-22"},
    {"Id": "INV-1005", "Customer": "Stark Ind", "TotalAmt": 6_400.00, "Balance": 6_400.00, "TxnDate": "2026-01-28"},
]

MOCK_PAYMENTS = [
    {"Id": "PMT-2001", "Customer": "Acme Corp", "TotalAmt": 12_500.00, "TxnDate": "2026-01-15"},
    {"Id": "PMT-2002", "Customer": "Initech LLC", "TotalAmt": 3_200.00, "TxnDate": "2026-01-25"},
    {"Id": "PMT-2003", "Customer": "Umbrella Co", "TotalAmt": 9_450.00, "TxnDate": "2026-01-29"},
]

# ── Main workflow ────────────────────────────────────────────────────────

def main():
    heading(f"Month-End Reconciliation — {PERIOD}")
    print(f"  Period : {PERIOD_START} to {PERIOD_END}")
    print(f"  Run at : {datetime.now(timezone.utc).isoformat()}Z")

    spec_path = Path(__file__).resolve().parent.parent / "docs" / "specs" / "quickbooks-online-v3.json"
    spec = json.loads(spec_path.read_text())
    executor = CodeModeExecutor()

    # ── Step 1: Discover endpoints ───────────────────────────────────────
    heading("Step 1 — Discover reconciliation endpoints")

    search_code = """\
keywords = ['invoice', 'payment', 'journalentry', 'journal', 'report', 'profit', 'balance']
results = []
for path, methods in spec.get('paths', {}).items():
    p = path.lower().replace('-', '').replace('_', '')
    matched = False
    for k in keywords:
        if k in p:
            matched = True
    if matched:
        for method, detail in methods.items():
            if method in ('get','post','put','delete','patch'):
                results.append(f"{method.upper():7s} {path}")
result = sorted(set(results))
"""
    r = executor.search(search_code, spec)
    audit("spec_search", f"Discovered {len(r.output)} reconciliation-related endpoints")
    for line in (r.output if isinstance(r.output, list) else []):
        print(f"    {line}")
    print(f"\n  → {len(r.output)} endpoints found via Code Mode search")

    # ── Step 2: Pull invoice summary (mock) ──────────────────────────────
    heading("Step 2 — Invoice summary")
    audit("api_read", f"GET /query?query=select * from Invoice where TxnDate >= '{PERIOD_START}'", "allow")

    total_invoiced = sum(i["TotalAmt"] for i in MOCK_INVOICES)
    total_outstanding = sum(i["Balance"] for i in MOCK_INVOICES)

    print(f"  {'Invoice':<12} {'Customer':<16} {'Amount':>12} {'Balance':>12}")
    print(f"  {'─'*12} {'─'*16} {'─'*12} {'─'*12}")
    for inv in MOCK_INVOICES:
        print(f"  {inv['Id']:<12} {inv['Customer']:<16} {inv['TotalAmt']:>12,.2f} {inv['Balance']:>12,.2f}")
    print(f"\n  Total invoiced    : ${total_invoiced:>12,.2f}")
    print(f"  Total outstanding : ${total_outstanding:>12,.2f}")

    # ── Step 3: Pull payment summary (mock) ──────────────────────────────
    heading("Step 3 — Payment summary")
    audit("api_read", f"GET /query?query=select * from Payment where TxnDate >= '{PERIOD_START}'", "allow")

    total_payments = sum(p["TotalAmt"] for p in MOCK_PAYMENTS)

    print(f"  {'Payment':<12} {'Customer':<16} {'Amount':>12}")
    print(f"  {'─'*12} {'─'*16} {'─'*12}")
    for pmt in MOCK_PAYMENTS:
        print(f"  {pmt['Id']:<12} {pmt['Customer']:<16} {pmt['TotalAmt']:>12,.2f}")
    print(f"\n  Total collected   : ${total_payments:>12,.2f}")

    # ── Step 4: Calculate discrepancies ──────────────────────────────────
    heading("Step 4 — Discrepancy analysis")

    collected = total_invoiced - total_outstanding
    discrepancy = collected - total_payments

    print(f"  Revenue invoiced  : ${total_invoiced:>12,.2f}")
    print(f"  Payments received : ${total_payments:>12,.2f}")
    print(f"  Balances cleared  : ${collected:>12,.2f}")
    print(f"  Discrepancy       : ${discrepancy:>12,.2f}")

    if abs(discrepancy) < 0.01:
        print("\n  ✅ Books are balanced — no adjustment needed.")
        audit("reconciliation", "No discrepancy found", "allow")
    else:
        print(f"\n  ⚠️  Discrepancy of ${discrepancy:,.2f} detected — adjustment required.")
        audit("reconciliation", f"Discrepancy of ${discrepancy:,.2f} detected")

    # ── Step 5: Generate correcting journal entry ────────────────────────
    if abs(discrepancy) >= 0.01:
        heading("Step 5 — Generate correcting journal entry")

        journal_entry = {
            "TxnDate": PERIOD_END,
            "DocNumber": f"ADJ-{PERIOD.replace('-', '')}",
            "PrivateNote": f"Month-end reconciliation adjustment for {PERIOD}",
            "Line": [
                {
                    "Amount": abs(discrepancy),
                    "DetailType": "JournalEntryLineDetail",
                    "JournalEntryLineDetail": {
                        "PostingType": "Debit" if discrepancy > 0 else "Credit",
                        "AccountRef": {"value": "1200", "name": "Accounts Receivable"},
                    },
                    "Description": "Reconciliation adjustment — AR",
                },
                {
                    "Amount": abs(discrepancy),
                    "DetailType": "JournalEntryLineDetail",
                    "JournalEntryLineDetail": {
                        "PostingType": "Credit" if discrepancy > 0 else "Debit",
                        "AccountRef": {"value": "4000", "name": "Revenue"},
                    },
                    "Description": "Reconciliation adjustment — Revenue",
                },
            ],
        }

        print(json.dumps(journal_entry, indent=2))

        # ── Policy checkpoint ────────────────────────────────────────────
        subheading("Policy checkpoint")

        # In production this would go through PolicyEngine with GatewayStorage.
        # Here we simulate the policy evaluation for the demo.
        policy_rule = {
            "rule": "recon-journals-approve",
            "resource": "codemode:execute",
            "action": "POST /journalentry",
            "effect": "approve",  # requires human sign-off
        }
        status = "pending_approval"
        audit("policy_check", f"POST /journalentry → {status}", status)

        print(f"  Policy decision : {status}")
        print(f"  Journal entry ADJ-{PERIOD.replace('-', '')} queued for approval.")
        print(f"  A controller must approve before it posts to QBO.")

    # ── Step 6: Audit trail ──────────────────────────────────────────────
    heading("Step 6 — Full audit trail")

    print(f"  {'#':<4} {'Timestamp':<28} {'Action':<18} {'Policy':<10} Detail")
    print(f"  {'─'*4} {'─'*28} {'─'*18} {'─'*10} {'─'*30}")
    for i, e in enumerate(audit_trail, 1):
        detail_short = e.detail[:45] + ("…" if len(e.detail) > 45 else "")
        print(f"  {i:<4} {e.timestamp:<28} {e.action:<18} {e.policy_decision:<10} {detail_short}")

    # ── Reconciliation report ────────────────────────────────────────────
    heading("Reconciliation Report")

    print(f"""
  Company         : Demo Company (Realm 1234567890)
  Period          : {PERIOD_START} — {PERIOD_END}
  Generated       : {datetime.now(timezone.utc).isoformat()}Z

  ┌──────────────────────────────────────────────┐
  │  Invoices issued          : {len(MOCK_INVOICES):>6}            │
  │  Total invoiced           : ${total_invoiced:>12,.2f}   │
  │  Payments received        : {len(MOCK_PAYMENTS):>6}            │
  │  Total collected          : ${total_payments:>12,.2f}   │
  │  Outstanding balance      : ${total_outstanding:>12,.2f}   │
  │  Discrepancy              : ${discrepancy:>12,.2f}   │
  │  Adjustment posted        : {'PENDING APPROVAL' if abs(discrepancy) >= 0.01 else 'N/A':>16}   │
  │  Audit events             : {len(audit_trail):>6}            │
  └──────────────────────────────────────────────┘

  Status: {'⚠️  PENDING — journal entry requires controller approval' if abs(discrepancy) >= 0.01 else '✅ BALANCED'}
""")


if __name__ == "__main__":
    main()

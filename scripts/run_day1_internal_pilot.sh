#!/usr/bin/env bash
set -euo pipefail

# Day-1 internal pilot execution helper
# Usage:
# ./scripts/run_day1_internal_pilot.sh <base_url> <admin_token> <tenant_id> <tenant_token>

BASE_URL="${1:-http://localhost:8000}"
ADMIN_TOKEN="${2:-dev-gateway-token}"
TENANT_ID="${3:-tenant-a}"
TENANT_TOKEN="${4:-tenant-a-token}"
TODAY="$(date -u +%Y-%m-%d)"
RUN_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
OUTDIR="pilot-artifacts/${TODAY}"

mkdir -p "$OUTDIR"

log() { printf "\n==> %s\n" "$1"; }

log "Bootstrapping pilot tenant"
./scripts/pilot_onboarding.sh "$BASE_URL" "$ADMIN_TOKEN" "$TENANT_ID" "$TENANT_TOKEN" > "$OUTDIR/onboarding.log"

log "Running failover dry-run"
curl -sS -X POST "$BASE_URL/gateway/routes/dry-run" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $TENANT_TOKEN" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"action\":\"plan\",\"strategy\":\"failover\"}" \
  > "$OUTDIR/failover-dry-run.json"

log "Running weighted dry-run"
curl -sS -X POST "$BASE_URL/gateway/routes/dry-run" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $TENANT_TOKEN" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"action\":\"plan\",\"strategy\":\"weighted\"}" \
  > "$OUTDIR/weighted-dry-run.json"

log "Running denied-path dry-run (unknown server)"
curl -sS -X POST "$BASE_URL/gateway/routes/dry-run" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $TENANT_TOKEN" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"action\":\"plan\",\"server_id\":\"missing-server\"}" \
  > "$OUTDIR/denied-dry-run.json"

# Assert denied-path is actually denied.
python3 - <<'PY' "$OUTDIR/denied-dry-run.json"
import json,sys
p=sys.argv[1]
obj=json.load(open(p))
if obj.get("allowed") is True:
    raise SystemExit("Denied-path check failed: expected allowed=false")
print("Denied-path assertion passed")
PY

log "Writing pilot artifacts"
cat > "$OUTDIR/reconciliation-summary.md" <<'EOF'
# Reconciliation Summary (Day-1 Internal Pilot)

- Internal pilot run completed.
- Route planning executed (failover + weighted).
- Denied-path control check executed and passed.
- Next: replace placeholders with real mismatch analysis from integrated systems.
EOF

cat > "$OUTDIR/proposed-actions.json" <<'EOF'
{
  "actions": [
    {"id": "act-1", "type": "journal-adjustment", "risk": "low", "status": "proposed"},
    {"id": "act-2", "type": "supporting-doc-request", "risk": "medium", "status": "proposed"}
  ]
}
EOF

cat > "$OUTDIR/approval-log.json" <<'EOF'
{
  "approvals": [
    {"actionId": "act-1", "decision": "pending"},
    {"actionId": "act-2", "decision": "pending"}
  ]
}
EOF

log "Building enriched audit report"
python3 - <<'PY' "$OUTDIR" "$TENANT_ID" "$RUN_TS"
import json,sys,os
outdir,tenant,run_ts=sys.argv[1],sys.argv[2],sys.argv[3]


def load(name):
    with open(os.path.join(outdir,name),"r") as f:
        return json.load(f)

failover=load("failover-dry-run.json")
weighted=load("weighted-dry-run.json")
denied=load("denied-dry-run.json")
proposed=load("proposed-actions.json")
approvals=load("approval-log.json")

def decision_entry(name, obj):
    return {
      "step": name,
      "eventId": obj.get("event_id"),
      "decidedAt": obj.get("decided_at"),
      "actor": obj.get("actor"),
      "request": obj.get("request"),
      "decision": obj.get("decision"),
      "reason": obj.get("reason"),
      "matchedRule": obj.get("matched_rule"),
      "selectedServerId": obj.get("selected_server_id"),
      "strategy": obj.get("strategy")
    }

trace = [
  decision_entry("failover", failover),
  decision_entry("weighted", weighted),
  decision_entry("deniedPath", denied),
]

report={
  "runId": f"day1-{run_ts}",
  "tenantId": tenant,
  "generatedAt": run_ts,
  "summary": {
    "allowCount": sum(1 for r in [failover,weighted,denied] if r.get("allowed") is True),
    "denyCount": sum(1 for r in [failover,weighted,denied] if r.get("allowed") is False),
    "proposedActionCount": len(proposed.get("actions",[])),
    "approvalCount": len(approvals.get("approvals",[]))
  },
  "actors": {
    "dryRunActor": (failover.get("actor") or weighted.get("actor") or denied.get("actor")),
  },
  "routeDecisions": {
    "failover": decision_entry("failover", failover),
    "weighted": decision_entry("weighted", weighted),
    "deniedPath": decision_entry("deniedPath", denied)
  },
  "actionTrace": trace,
  "artifacts": [
    "onboarding.log",
    "failover-dry-run.json",
    "weighted-dry-run.json",
    "denied-dry-run.json",
    "reconciliation-summary.md",
    "proposed-actions.json",
    "approval-log.json"
  ]
}

with open(os.path.join(outdir,"audit-report.json"),"w") as f:
    json.dump(report,f,indent=2)
PY

log "Done. Artifacts written to $OUTDIR"
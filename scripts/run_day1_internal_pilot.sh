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

log "Writing placeholder pilot artifacts"
cat > "$OUTDIR/reconciliation-summary.md" <<'EOF'
# Reconciliation Summary (Day-1 Internal Pilot)

- Internal pilot run completed.
- Route planning executed (failover + weighted).
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

cat > "$OUTDIR/audit-report.json" <<EOF
{
  "tenantId": "$TENANT_ID",
  "generatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "artifacts": [
    "onboarding.log",
    "failover-dry-run.json",
    "weighted-dry-run.json",
    "reconciliation-summary.md",
    "proposed-actions.json",
    "approval-log.json"
  ]
}
EOF

log "Done. Artifacts written to $OUTDIR"

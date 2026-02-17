#!/usr/bin/env bash
set -euo pipefail

# AgentGate Pilot Onboarding Script (POC)
# Usage:
#   ./scripts/pilot_onboarding.sh <base_url> <admin_token> <tenant_id> <tenant_token>
# Example:
#   ./scripts/pilot_onboarding.sh http://localhost:8000 dev-gateway-token tenant-a tenant-a-token

BASE_URL="${1:-http://localhost:8000}"
ADMIN_TOKEN="${2:-dev-gateway-token}"
TENANT_ID="${3:-tenant-a}"
TENANT_TOKEN="${4:-tenant-a-token}"

printf "==> Creating tenant operator token\n"
curl -sS -X POST "$BASE_URL/gateway/access/tokens" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $ADMIN_TOKEN" \
  -d "{\"token\":\"$TENANT_TOKEN\",\"subject_id\":\"${TENANT_ID}-op\",\"tenant_id\":\"$TENANT_ID\",\"role\":\"tenant-operator\",\"scopes\":[\"gateway:read\",\"gateway:write\",\"gateway:plan\"]}" \
  | jq .

printf "==> Registering sample finance servers\n"
curl -sS -X POST "$BASE_URL/gateway/servers" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $TENANT_TOKEN" \
  -d "{\"server_id\":\"${TENANT_ID}-acct-primary\",\"name\":\"Accounting Primary\",\"tenant_id\":\"$TENANT_ID\",\"transport\":\"sse\",\"endpoint\":\"https://api.example.com/sse\",\"weight\":5,\"priority\":20}" \
  | jq .

curl -sS -X POST "$BASE_URL/gateway/servers" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $TENANT_TOKEN" \
  -d "{\"server_id\":\"${TENANT_ID}-acct-backup\",\"name\":\"Accounting Backup\",\"tenant_id\":\"$TENANT_ID\",\"transport\":\"sse\",\"endpoint\":\"https://api-backup.example.com/sse\",\"weight\":2,\"priority\":10}" \
  | jq .

printf "==> Creating policy rule for plan actions\n"
curl -sS -X POST "$BASE_URL/gateway/policy/rules" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $ADMIN_TOKEN" \
  -d "{\"name\":\"allow-${TENANT_ID}-plan\",\"effect\":\"allow\",\"actions\":[\"plan\"],\"resources\":[\"gateway.server.${TENANT_ID}-acct-primary\",\"gateway.server.${TENANT_ID}-acct-backup\"],\"tenants\":[\"$TENANT_ID\"]}" \
  | jq .

printf "==> Running dry-run sanity check\n"
curl -sS -X POST "$BASE_URL/gateway/routes/dry-run" \
  -H "Content-Type: application/json" \
  -H "x-gateway-token: $TENANT_TOKEN" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"action\":\"plan\",\"strategy\":\"failover\"}" \
  | jq .

printf "\nPilot onboarding complete for tenant: %s\n" "$TENANT_ID"

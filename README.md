# AgentGate

**Policy-first control plane for AI agents over business APIs.**

**AgentGate is an API-first, AI-first, agent-first control plane** for teams running ChatGPT-, Claude-, and custom-agent workflows over business APIs.

The project keeps legacy APIs intact while adding persistent gateway control-plane capabilities under `/gateway/*`.

## Security by Default (Agent Operations)

- Deny-by-default policy decisions
- Tenant-scoped RBAC tokens and explicit scopes
- Transport validation by protocol type
- Health-aware route selection
- Audit-ready route decision output (reason + matched rule)

See:
- `docs/security-by-default.md`
- `docs/control-guarantees.md`

## Implemented so far

### Phase 1
- Persistent SQLite storage for registered servers and policy rules
- Policy management + registry management APIs
- Dry-run route evaluation with explicit deny reasons and health filtering
- Prometheus metrics export endpoint

### Phase 2
- Transport-specific endpoint validation (`stdio`, `sse`, `streamable-http`, `ws`)
- Weighted/failover route selection for dry-run planning
- Tenant-scoped RBAC token model and scope checks
- CI workflow for gateway tests

### Phase 3 (current)
- Real transport execution adapters (streamable-http, SSE, stdio)
- `POST /gateway/routes/execute` — calls real MCP servers through the gateway
- Policy-gated execution with dry-run support
- Echo MCP server test fixture for integration testing
- Migration script for gateway schema verification

## Gateway endpoints

- `GET /gateway/health`
- `GET /gateway/metrics`
- `GET /gateway/servers`
- `POST /gateway/servers`
- `POST /gateway/servers/{server_id}/health?healthy=true|false`
- `GET /gateway/policy/rules`
- `POST /gateway/policy/rules`
- `DELETE /gateway/policy/rules/{name}`
- `POST /gateway/access/tokens`
- `POST /gateway/access/tokens/{token}/revoke`
- `POST /gateway/routes/dry-run`
- `POST /gateway/routes/execute` **(Phase 3)**
- `GET /gateway/audit`

> Protected endpoints require `x-gateway-token` with appropriate role/scope.

## Quick Start

```bash
# 1. Clone and install
git clone <repository-url>
cd mcp-paas-implementation
pip install -r requirements.txt

# 2. Run migrations (creates/verifies SQLite schema)
python scripts/migrate.py

# 3. Start the server
uvicorn server:app --reload

# 4. The admin token is auto-bootstrapped (default: dev-gateway-token)
# Override with: export MCP_GATEWAY_ADMIN_TOKEN="your-secret"

# 5. Create a tenant operator token
curl -X POST http://localhost:8000/gateway/access/tokens \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: dev-gateway-token' \
  -d '{
    "token":"my-tenant-token",
    "subject_id":"tenant-ops",
    "tenant_id":"acme",
    "role":"tenant-operator",
    "scopes":["gateway:read","gateway:write","gateway:plan","gateway:execute"]
  }'

# 6. Register an MCP server
curl -X POST http://localhost:8000/gateway/servers \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: my-tenant-token' \
  -d '{
    "server_id":"my-mcp",
    "name":"My MCP Server",
    "tenant_id":"acme",
    "transport":"streamable-http",
    "endpoint":"http://localhost:9000/mcp"
  }'

# 7. Add a policy rule (admin only)
curl -X POST http://localhost:8000/gateway/policy/rules \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: dev-gateway-token' \
  -d '{
    "name":"allow-acme-tools",
    "effect":"allow",
    "actions":["tools/list","tools/call"],
    "resources":["gateway.server.my-mcp"],
    "tenants":["acme"]
  }'

# 8. Execute a call through the gateway
curl -X POST http://localhost:8000/gateway/routes/execute \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: my-tenant-token' \
  -d '{
    "server_id":"my-mcp",
    "method":"tools/list",
    "params":{}
  }'
```

## Environment variables

```bash
export MCP_GATEWAY_DB_PATH="./data/gateway_control_plane.db"  # SQLite path
export MCP_GATEWAY_ADMIN_TOKEN="dev-gateway-token"             # Bootstrap admin token
```

## API contract examples

Canonical schema contract is defined in `docs/api_spec.yaml`.

Error semantics to rely on:
- `401` missing/invalid `x-gateway-token`
- `403` role/scope/tenant violation (including expired/revoked tokens)
- `404` unknown server_id in execute calls
- `422` malformed payload or invalid enum/range

## Tests

```bash
# All gateway tests (including integration)
pytest -q gateway_tests/

# Run the finance stub demo
python pilot-artifacts/finance-stub-demo/run_demo.py
```

## Preflight

Before running pilot/demo flows:

```bash
./scripts/preflight_check.sh http://localhost:8000
```

## Directional docs

- `docs/migration-current-to-target.md`
- `docs/architecture-agentgate-control-plane.md`
- `docs/roadmap-agentgate-control-plane.md`
- `docs/next-sprint-tasks.md`
- `docs/partner-pilot-brief.md`
- `docs/partner-outreach-templates.md`
- `docs/pilot-intake-questionnaire.md`
- `docs/finance-poc-workflow-v1.md`
- `docs/policy-templates-finance-v1.md`
- `docs/finance-pilot-readiness-checklist.md`
- `docs/llm-discovery-positioning.md`
- `docs/partner-demo-script-v1.md`
- `docs/partner-first-call-checklist.md`
- `docs/pilot-kickoff-agenda-v1.md`
- `docs/target-account-scoring-model.md`
- `docs/target-account-list-template.csv`
- `docs/target-account-outreach-plan-next-10.md`
- `docs/partner-ready-api-hardening-checklist.md`
- `docs/execution-standards.md`
- `docs/spec-build-verify-gates.md`
- `docs/systematic-debugging-playbook.md`
- `docs/memory-tiers-and-retrieval-modes.md`
- `docs/context-checkpoints-and-rollbacks.md`
- `docs/coordinator-worker-handoff-contract.md`
- `docs/task-bundle-template.md`
- `docs/formula-runbook-partner-pilot.md`
- `docs/confidence-grading.md`
- `docs/config-lint-checklist.md`
- `docs/operator-status-template.md`
- `docs/security-by-default.md`
- `docs/control-guarantees.md`

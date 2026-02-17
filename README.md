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

### Phase 2 (current)
- Transport-specific endpoint validation (`stdio`, `sse`, `streamable-http`, `ws`)
- Weighted/failover route selection for dry-run planning
- Tenant-scoped RBAC token model and scope checks
- CI workflow for gateway tests

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
- `POST /gateway/routes/dry-run`

> Protected endpoints require `x-gateway-token` with appropriate role/scope.

## Quickstart

```bash
# Clone
git clone <repository-url>
cd mcp-paas-implementation

# Install deps
pip install -r requirements.txt
```

Set optional env vars:

```bash
export MCP_GATEWAY_DB_PATH="./data/gateway_control_plane.db"
export MCP_GATEWAY_ADMIN_TOKEN="dev-gateway-token"
```

Run the API:

```bash
uvicorn mcp_paas.server:app --reload
```

## Phase 2 example flow

```bash
# 1) create a tenant operator token via bootstrap admin token
curl -X POST http://localhost:8000/gateway/access/tokens \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: dev-gateway-token' \
  -d '{
    "token":"tenant-a-token",
    "subject_id":"tenant-a-op",
    "tenant_id":"tenant-a",
    "role":"tenant-operator",
    "scopes":["gateway:read","gateway:write","gateway:plan"]
  }'

# 2) register servers
curl -X POST http://localhost:8000/gateway/servers \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: tenant-a-token' \
  -d '{"server_id":"srv-1","name":"github-mcp","tenant_id":"tenant-a","transport":"sse","endpoint":"https://example.com/sse","weight":5,"priority":20}'

# 3) add policy rule with admin token
curl -X POST http://localhost:8000/gateway/policy/rules \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: dev-gateway-token' \
  -d '{"name":"allow-tenant-a-plan","effect":"allow","actions":["plan"],"resources":["gateway.server.srv-1"],"tenants":["tenant-a"]}'

# 4) dry-run plan
curl -X POST http://localhost:8000/gateway/routes/dry-run \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: tenant-a-token' \
  -d '{"tenant_id":"tenant-a","action":"plan","strategy":"weighted"}'
```

## Tests

```bash
pytest -q gateway_tests/test_gateway_policy.py gateway_tests/test_gateway_api.py
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
- `docs/execution-standards.md`
- `docs/security-by-default.md`
- `docs/control-guarantees.md`

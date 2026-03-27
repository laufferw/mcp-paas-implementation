# AgentGate

**Policy-first MCP and A2A gateway for AI agents.**

AgentGate sits between your AI agents and your business APIs. Every call is policy-checked, tenant-scoped, and audit-logged before it reaches a real system. Deny-by-default. No surprises.

## Why AgentGate

Most MCP gateway projects are proxies. AgentGate is a control plane.

The difference: a proxy passes traffic. A control plane decides whether traffic should pass at all — and gives you a full audit trail of why.

| Concern | Without AgentGate | With AgentGate |
|---|---|---|
| Policy enforcement | Per-tool, ad-hoc, inconsistent | Centralized, deny-by-default, auditable |
| Multi-tenant isolation | Manual, fragile | RBAC tokens + tenant scoping built in |
| Agent observability | Logs (if you're lucky) | Structured audit log, Prometheus metrics |
| Dry-run before execute | Not possible | First-class — test your policy before it matters |
| Transport coverage | One transport | stdio, SSE, streamable-http, WebSocket |

## How it relates to ContextForge (IBM)

IBM's [ContextForge](https://github.com/IBM/mcp-context-forge) is a federation layer — it aggregates MCP and A2A servers into a single unified endpoint with protocol translation, plugin extensibility, and Kubernetes-scale deployments. It is excellent at making many servers look like one.

AgentGate is a control plane — it decides what agents are allowed to do, enforces those decisions in real time, and gives operators the tools to audit, revoke, and govern. It is purpose-built for teams where trust, compliance, and explainability matter.

They are complementary. You could run AgentGate in front of a ContextForge federation to add policy enforcement to a multi-cluster MCP environment.

## What's built

### Phase 1
- Persistent SQLite storage for registered servers and policy rules
- Policy management and registry management APIs
- Dry-run route evaluation with explicit deny reasons and health filtering
- Prometheus metrics export endpoint

### Phase 2
- Transport-specific endpoint validation (`stdio`, `sse`, `streamable-http`, `ws`)
- Weighted and failover route selection for dry-run planning
- Tenant-scoped RBAC token model and scope checks
- CI workflow for gateway tests

### Phase 3 (current)
- Real transport execution adapters (streamable-http, SSE, stdio)
- `POST /gateway/routes/execute` — calls real MCP servers through the gateway
- Policy-gated execution with dry-run support
- Echo MCP server test fixture for integration testing
- Migration script for gateway schema verification

## Quick Start

```bash
cp .env.example .env
# Set AGENTGATE_ADMIN_TOKEN in .env
docker compose up -d
curl http://localhost:8000/gateway/health
```

Or without Docker:

```bash
git clone https://github.com/laufferw/mcp-paas-implementation
cd mcp-paas-implementation
pip install -r requirements.txt
python scripts/migrate.py
uvicorn server:app --reload
```

The admin token bootstraps automatically (default: `dev-gateway-token`). Override with `export MCP_GATEWAY_ADMIN_TOKEN="your-secret"`.

## Five-minute walkthrough

```bash
# 1. Create a tenant token
curl -X POST http://localhost:8000/gateway/access/tokens \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: dev-gateway-token' \
  -d '{
    "token": "my-tenant-token",
    "subject_id": "tenant-ops",
    "tenant_id": "acme",
    "role": "tenant-operator",
    "scopes": ["gateway:read", "gateway:write", "gateway:plan", "gateway:execute"]
  }'

# 2. Register an MCP server
curl -X POST http://localhost:8000/gateway/servers \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: my-tenant-token' \
  -d '{
    "server_id": "my-mcp",
    "name": "My MCP Server",
    "tenant_id": "acme",
    "transport": "streamable-http",
    "endpoint": "http://localhost:9000/mcp"
  }'

# 3. Add a policy rule
curl -X POST http://localhost:8000/gateway/policy/rules \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: dev-gateway-token' \
  -d '{
    "name": "allow-acme-tools",
    "effect": "allow",
    "actions": ["tools/list", "tools/call"],
    "resources": ["gateway.server.my-mcp"],
    "tenants": ["acme"]
  }'

# 4. Dry-run first (always)
curl -X POST http://localhost:8000/gateway/routes/dry-run \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: my-tenant-token' \
  -d '{"server_id": "my-mcp", "method": "tools/list", "params": {}}'

# 5. Execute for real
curl -X POST http://localhost:8000/gateway/routes/execute \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-token: my-tenant-token' \
  -d '{"server_id": "my-mcp", "method": "tools/list", "params": {}}'
```

## Using with Claude

```python
from src.mcp_gateway.claude_integration import GatewayClient
import anthropic

client = GatewayClient("http://localhost:8000", token="your-token")
tools = client.as_tools()

anthropic_client = anthropic.Anthropic()
response = anthropic_client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "List all registered MCP servers"}]
)
```

See `scripts/claude_demo.py` for a full working example.

## API reference

| Endpoint | Description |
|---|---|
| `GET /gateway/health` | Health check |
| `GET /gateway/metrics` | Prometheus metrics |
| `GET /gateway/servers` | List registered servers |
| `POST /gateway/servers` | Register a server |
| `POST /gateway/servers/{id}/health` | Update server health |
| `GET /gateway/policy/rules` | List policy rules |
| `POST /gateway/policy/rules` | Create a policy rule |
| `DELETE /gateway/policy/rules/{name}` | Delete a policy rule |
| `POST /gateway/access/tokens` | Issue a tenant token |
| `POST /gateway/access/tokens/{token}/revoke` | Revoke a token |
| `POST /gateway/routes/dry-run` | Evaluate route without executing |
| `POST /gateway/routes/execute` | Execute a route through the gateway |
| `GET /gateway/audit` | Retrieve audit log |

All protected endpoints require `x-gateway-token` with appropriate role and scope.

**Error semantics:**
- `401` missing or invalid token
- `403` role, scope, or tenant violation (including revoked tokens)
- `404` unknown server_id
- `422` malformed payload

## Environment variables

```bash
MCP_GATEWAY_DB_PATH="./data/gateway_control_plane.db"
MCP_GATEWAY_ADMIN_TOKEN="dev-gateway-token"
```

## Tests

```bash
pytest -q gateway_tests/

# Run the finance stub demo
python pilot-artifacts/finance-stub-demo/run_demo.py

# Preflight check
./scripts/preflight_check.sh http://localhost:8000
```

## Architecture

AgentGate is built in three layers:

1. **Registry** — servers register with transport type, endpoint, and tenant association
2. **Policy engine** — rules evaluated against (action, resource, tenant, token) — deny by default
3. **Execution adapters** — transport-specific clients (stdio, SSE, streamable-http) that execute only after policy clears

The dry-run endpoint runs layers 1 and 2 only, returning the policy decision and matched rule without touching any real server. This is the recommended way to validate policy before deploying changes.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- A2A protocol support (agent-to-agent task delegation through the gateway)
- WebSocket execution adapter
- Redis-backed distributed state (multi-instance deployments)
- Admin UI
- PyPI package (`agentgate`)

## License

MIT

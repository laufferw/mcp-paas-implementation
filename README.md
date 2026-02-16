# MCP Gateway + Control Plane (formerly MCP PaaS Implementation)

This repository is transitioning from a model-context PaaS API into an **MCP Gateway + Control Plane**.

The project now keeps legacy APIs intact while adding persistent control-plane capabilities under `/gateway/*`.

## Phase 1 implemented

- Added migration and architecture docs in `docs/`.
- Added gateway package: `src/mcp_gateway`.
- Added persistent SQLite storage for:
  - registered MCP servers
  - policy rules
- Added policy management + registry management APIs.
- Added dry-run route evaluation with explicit deny reasons and server health filtering.
- Added Prometheus export endpoint for gateway metrics.

## Gateway endpoints

- `GET /gateway/health`
- `GET /gateway/metrics`
- `GET /gateway/servers`
- `POST /gateway/servers` *(admin token required)*
- `POST /gateway/servers/{server_id}/health?healthy=true|false` *(admin token required)*
- `GET /gateway/policy/rules`
- `POST /gateway/policy/rules` *(admin token required)*
- `DELETE /gateway/policy/rules/{name}` *(admin token required)*
- `POST /gateway/routes/dry-run`

## Quickstart

```bash
# Clone
git clone <repository-url>
cd mcp-paas-implementation

# Install deps (choose your env toolchain)
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

Try the Phase 1 flow:

```bash
curl http://localhost:8000/gateway/health

curl -X POST http://localhost:8000/gateway/servers \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-admin-token: dev-gateway-token' \
  -d '{"server_id":"srv-1","name":"github-mcp","tenant_id":"tenant-a","transport":"sse","endpoint":"https://example.com/sse"}'

curl -X POST http://localhost:8000/gateway/policy/rules \
  -H 'Content-Type: application/json' \
  -H 'x-gateway-admin-token: dev-gateway-token' \
  -d '{"name":"allow-tenant-a-plan-srv1","effect":"allow","actions":["plan"],"resources":["gateway.server.srv-1"],"tenants":["tenant-a"]}'

curl -X POST http://localhost:8000/gateway/routes/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"tenant_id":"tenant-a","action":"plan","server_id":"srv-1"}'
```

## Tests

Targeted tests added for policy and gateway API:

```bash
pytest tests/test_gateway_policy.py tests/test_gateway_api.py -q
```

## Directional docs

- `docs/migration-current-to-target.md`
- `docs/architecture-gateway-control-plane.md`
- `docs/roadmap-gateway-control-plane.md`
- `docs/next-sprint-tasks.md`

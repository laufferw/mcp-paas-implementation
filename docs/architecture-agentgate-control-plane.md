# AgentGate Architecture (Initial Slice)

## New gateway domain (`src/mcp_gateway`)
- `transport_adapters.py`: transport protocol + HTTP adapter scaffold.
- `registry.py`: in-memory registered server catalog.
- `policy.py`: typed allow/deny policy engine.
- `observability.py`: lightweight counters snapshot helper.
- `router.py`: FastAPI router under `/gateway`.

## Exposed endpoints
- `GET /gateway/health`
- `GET /gateway/servers`
- `POST /gateway/routes/dry-run`

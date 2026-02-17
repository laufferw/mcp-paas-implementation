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

## Memory model (operational)
- **Working memory (core):** active run state and deterministic operational context.
- **Archival memory (semantic):** historical artifacts queried for concept-level recall.

Reference: `docs/memory-tiers-and-retrieval-modes.md`

## Retrieval modes
- **Exact lookup:** deterministic checks for strict correctness (IDs, rules, schemas).
- **Semantic synthesis:** concept-level discovery across historical artifacts.

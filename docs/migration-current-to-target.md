# Migration: Current MCP PaaS -> AgentGate

- Current: monolithic MCP PaaS API with context lifecycle/inference endpoints.
- Target: gateway-centric architecture with control-plane APIs for servers, routes, and policies.
- Strategy: additive migration. Keep legacy APIs stable while introducing `/gateway/*`.
- Risk control: default-deny policy behavior and incremental module boundaries.

## Retrieval strategy during migration
- Prefer **exact lookup** for migration-critical checks (rule names, endpoint paths, schema fields).
- Use **semantic synthesis** to discover related historical decisions and prior rollout lessons.
- For release decisions, pair deterministic evidence with semantic context before sign-off.

Reference: `docs/memory-tiers-and-retrieval-modes.md`

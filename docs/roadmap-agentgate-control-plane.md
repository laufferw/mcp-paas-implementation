# AgentGate Phased Roadmap

## Phase 0 (done)
- Gateway package scaffolding and non-breaking `/gateway/*` endpoints.
- Typed policy engine + initial unit tests.

## Phase 1 (done)
- Persisted registry and policy storage.
- Control plane CRUD APIs and dry-run planning.
- Metrics export endpoint.

## Phase 2 (in progress)
- Transport-specific endpoint validation (done).
- Weighted/failover route strategy (done).
- Tenant-scoped RBAC tokens and scopes (done).
- CI workflow for gateway tests (done).

## Phase 3 (next)
- Real transport execution adapters (HTTP/SSE/WS/stdio/streamable-http).
- Rich decision telemetry and audit event store.
- Strong tenant governance with role templates and delegated policy ops.

## Phase 4
- Full legacy endpoint deprecation plan, migration tooling, and conformance hardening.

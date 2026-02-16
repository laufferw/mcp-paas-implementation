# Migration: Current MCP PaaS -> MCP Gateway + Control Plane

- Current: monolithic MCP PaaS API with context lifecycle/inference endpoints.
- Target: gateway-centric architecture with control-plane APIs for servers, routes, and policies.
- Strategy: additive migration. Keep legacy APIs stable while introducing `/gateway/*`.
- Risk control: default-deny policy behavior and incremental module boundaries.

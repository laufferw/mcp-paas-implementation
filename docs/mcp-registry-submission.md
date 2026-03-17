# MCP Registry Submission — AgentGate

Fields needed to submit AgentGate to the [GitHub MCP Registry](https://github.com/modelcontextprotocol/servers).

## Registry Entry Fields

| Field | Value |
|---|---|
| **Name** | AgentGate |
| **Description** | MCP gateway and control plane for AI agents — policy-governed routing, multi-tenant access control, audit logging, and health-aware server selection across MCP servers. |
| **Category** | Infrastructure / Gateway |
| **Repository URL** | `https://github.com/openclaw/mcp-paas-implementation` |
| **Homepage** | (same as repo or project URL) |
| **Author / Organization** | OpenClaw |
| **License** | (fill in — e.g. MIT, Apache-2.0) |
| **Transport** | `streamable-http`, `sse`, `stdio` |
| **Tags** | `gateway`, `control-plane`, `policy`, `multi-tenant`, `audit`, `routing`, `agent-native` |

## README Requirements

The MCP registry expects a README.md with:

1. **What the server does** — one-paragraph summary
2. **Installation instructions** — pip install, Docker, or clone + run
3. **Configuration** — environment variables, required setup
4. **Available tools / resources / prompts** — what MCP capabilities are exposed
5. **Usage examples** — curl or SDK snippets showing real calls
6. **Authentication** — how tokens work

## Submission Process

1. Fork [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)
2. Add entry to the appropriate section of the README (Community Servers)
3. Include: name, one-line description, and link to repository
4. Open a pull request with the new entry
5. Ensure the repository README meets the quality bar above

## Package Distribution (Optional)

If publishing as an installable package:

- **npm**: Add to `package.json` with `bin` entry pointing to the server entrypoint
- **PyPI**: Add `pyproject.toml` with console_scripts entry point
- **Docker**: Publish image to Docker Hub or GitHub Container Registry

## AgentGate-Specific Notes

AgentGate is a *gateway* (sits in front of MCP servers), not a standard MCP server itself. The submission should clarify that it:

- Proxies requests to downstream MCP servers
- Adds policy evaluation, audit, and multi-tenant isolation
- Supports agent self-registration via `/gateway/agents/register`
- Provides a machine-readable discovery endpoint at `/gateway/agent-info`

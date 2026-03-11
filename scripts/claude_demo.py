#!/usr/bin/env python3
"""
AgentGate Claude Integration Demo

Demonstrates how to use GatewayClient to connect Claude (or any LLM)
to MCP servers through the AgentGate gateway.

Usage:
    python scripts/claude_demo.py [--base-url http://localhost:8000] [--token dev-gateway-token]

Works even if no servers are registered (graceful empty state).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os

# Add project root to path so imports work when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcp_gateway.claude_integration import GatewayClient


async def demo(base_url: str, token: str) -> None:
    client = GatewayClient(base_url=base_url, token=token)

    # --- Step 1: List available servers ---
    print("=" * 60)
    print("AgentGate Claude Integration Demo")
    print("=" * 60)
    print(f"\nGateway: {base_url}")
    print()

    try:
        servers = await client.list_servers()
    except Exception as e:
        print(f"Could not connect to gateway: {e}")
        print("\nMake sure the gateway is running:")
        print("  python server.py")
        print("\nContinuing with tool definitions (no server needed)...\n")
        servers = []

    if servers:
        print(f"Registered servers ({len(servers)}):")
        for s in servers:
            health = "healthy" if s.get("healthy") else "unhealthy"
            print(f"  - {s['server_id']}  ({s['transport']}, {health})")
    else:
        print("No servers registered yet (empty state is OK).")
    print()

    # --- Step 2: Show tool definitions ---
    tools = client.as_tools()
    print(f"Tool definitions for Claude/GPT ({len(tools)} tools):")
    print(json.dumps(tools, indent=2))
    print()

    # --- Step 3: Show how to wire into Anthropic API ---
    print("=" * 60)
    print("Example: Wiring into the Anthropic API")
    print("=" * 60)
    print("""
from src.mcp_gateway.claude_integration import GatewayClient
import anthropic

# 1. Create a gateway client
client = GatewayClient("http://localhost:8000", token="your-token")

# 2. Get tool definitions
tools = client.as_tools()

# 3. Pass tools to Claude
anthropic_client = anthropic.Anthropic()
response = anthropic_client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1024,
    tools=tools,
    messages=[{"role": "user", "content": "List all registered MCP servers"}]
)

# 4. Handle tool_use responses
for block in response.content:
    if block.type == "tool_use":
        if block.name == "agentgate_list_servers":
            result = await client.list_servers()
        elif block.name == "agentgate_execute":
            result = await client.execute(
                block.input["server_id"],
                block.input["method"],
                block.input.get("params", {}),
            )
        elif block.name == "agentgate_audit_log":
            result = await client.get_audit_log(block.input.get("limit", 20))
""")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentGate Claude Integration Demo")
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENTGATE_BASE_URL", "http://localhost:8000"),
        help="Gateway base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("AGENTGATE_ADMIN_TOKEN", "dev-gateway-token"),
        help="Gateway access token",
    )
    args = parser.parse_args()
    asyncio.run(demo(args.base_url, args.token))


if __name__ == "__main__":
    main()

"""Minimal MCP echo server for integration testing.

Listens on HTTP (streamable-http transport) and implements:
  - tools/list  → returns one tool: echo
  - tools/call  → with name="echo", returns params back

Usage:
    python tests/fixtures/echo_mcp_server.py [port]

The server prints "READY:<port>" to stdout once it's listening.
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class EchoMCPHandler(BaseHTTPRequestHandler):
    """Handles JSON-RPC 2.0 requests mimicking an MCP server."""

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self._json_response(400, {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None})
            return

        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id", 1)

        if method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echoes back the input parameters",
                        "inputSchema": {"type": "object"},
                    }
                ]
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            if tool_name == "echo":
                result = {"content": [{"type": "text", "text": json.dumps(arguments)}]}
            else:
                self._json_response(200, {
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                    "id": req_id,
                })
                return
        else:
            self._json_response(200, {
                "jsonrpc": "2.0",
                "error": {"code": -32601, "message": f"Method not found: {method}"},
                "id": req_id,
            })
            return

        self._json_response(200, {"jsonrpc": "2.0", "result": result, "id": req_id})

    def _json_response(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # Silence request logs during tests
        pass


def start_echo_server(port: int = 0) -> tuple[HTTPServer, int]:
    """Start the echo MCP server and return (server, port).

    If port=0, an ephemeral port is chosen.
    """
    server = HTTPServer(("127.0.0.1", port), EchoMCPHandler)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, actual_port


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    server, actual_port = start_echo_server(port)
    print(f"READY:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

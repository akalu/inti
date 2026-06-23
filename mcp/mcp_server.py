"""
INTI — MCP Tool Server
==============================
Exposes the ToolRegistry as an MCP-compatible tool provider.

Protocol (JSON-RPC-like):
  tools/list   → returns all tool schemas
  tools/call   → invokes a tool, returns ToolResult

Any system can discover and invoke tools through standardized messages.
The server also provides tool schema injection for LLM prompts.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("taas")


class MCPToolServer:
    """
    MCP-compliant tool server.
    Wraps a ToolRegistry and exposes it via a simple JSON-RPC protocol.
    Designed to be embedded inside the constellation (not a separate process).
    """

    PROTOCOL_VERSION = "2025-01-01"

    def __init__(self, tool_registry=None):
        self._registry = tool_registry
        self._call_count = 0

    @property
    def registry(self):
        if self._registry is None:
            from tools.registry import ToolRegistry
            self._registry = ToolRegistry()
            self._registry.register_defaults()
        return self._registry

    # ─────────── JSON-RPC Handler ───────────

    async def handle_request(self, request: dict) -> dict:
        """
        Process an MCP JSON-RPC request.
        Format: {"method": "tools/list"|"tools/call", "params": {...}}
        Returns: {"result": ..., "error": ...}
        """
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id", None)

        try:
            if method == "tools/list":
                result = self._handle_list(params)
            elif method == "tools/call":
                result = await self._handle_call(params)
            elif method == "initialize":
                result = self._handle_initialize()
            elif method == "ping":
                result = {"status": "ok"}
            else:
                return self._error_response(req_id, f"Unknown method: {method}")

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except Exception as e:
            logger.error(f"[MCP_SERVER] Error handling {method}: {e}")
            return self._error_response(req_id, str(e))

    # ─────────── Methods ───────────

    def _handle_initialize(self) -> dict:
        """MCP initialize handshake."""
        return {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "INTI-tool-server",
                "version": "1.0.0",
            },
        }

    def _handle_list(self, params: dict) -> dict:
        """List all available tools with their schemas."""
        schemas = self.registry.list_tools()
        return {
            "tools": [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            p["name"]: {
                                "type": p["type"],
                                "description": p["description"],
                            }
                            for p in s["parameters"]
                        },
                        "required": [
                            p["name"] for p in s["parameters"] if p["required"]
                        ],
                    },
                }
                for s in schemas
            ],
        }

    async def _handle_call(self, params: dict) -> dict:
        """Call a tool by name with parameters."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not tool_name:
            return {"content": [{"type": "text", "text": "Missing tool name"}], "isError": True}

        self._call_count += 1
        result = await self.registry.execute(tool_name, **arguments)

        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result.to_dict(), default=str),
                }
            ],
            "isError": not result.success,
        }

    # ─────────── LLM Integration ───────────

    def get_tool_prompt_block(self) -> str:
        """
        Generate a text block describing all available tools
        for injection into LLM system prompts.
        """
        schemas = self.registry.list_tools()
        if not schemas:
            return ""

        lines = ["## Available Tools", ""]
        for s in schemas:
            params_str = ", ".join(
                f"{p['name']}: {p['type']}" + (" (required)" if p["required"] else "")
                for p in s["parameters"]
            )
            lines.append(f"### {s['name']} [{s['risk_level'].upper()}]")
            lines.append(f"{s['description']}")
            lines.append(f"Parameters: {params_str}")
            lines.append("")

        lines.append(
            "To invoke a tool, respond with JSON: "
            '{"tool_call": {"name": "<tool>", "arguments": {...}}}'
        )

        # Tool selection guide for WILL
        lines.append("")
        lines.append("## Tool Selection Guide")
        lines.append("- **Finding information**: use `web_search` first to find URLs")
        lines.append("- **Reading a URL / extracting article content**: use `web_crawler` (action: crawl) — it renders JavaScript and outputs clean Markdown")
        lines.append("- **Quick URL metadata/headers**: use `web_browser` (action: headers)")
        lines.append("- **Chaining**: for research tasks, first `web_search` to find URLs, then `web_crawler` to read the best results")
        lines.append("- **NEVER** use `web_browser` for reading articles — always prefer `web_crawler` for full content extraction")

        return "\n".join(lines)

    # ─────────── Utils ───────────

    def _error_response(self, req_id: Any, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": message},
        }

    def get_status(self) -> dict:
        return {
            "protocol_version": self.PROTOCOL_VERSION,
            "tools_count": self.registry.tool_count,
            "total_calls": self._call_count,
        }

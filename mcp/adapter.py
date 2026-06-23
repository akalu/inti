"""
INTI — MCP LLM Adapter Interface & Client
===============================================
Universal bridge to LLM providers through an adapter pattern.
Each cognitive system gets its own MCPLLMClient with per-system configuration.

Supported providers: gemini, openai, ollama, simulation
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from config.settings import LLMConfig

logger = logging.getLogger("taas")


# ============================================================
# Abstract Adapter
# ============================================================

class LLMAdapter(ABC):
    """Abstract interface for all LLM providers."""

    def __init__(self, model: str = "", api_key: str = "", url: str = ""):
        self.model = model
        self.api_key = api_key
        self.url = url
        self._call_count = 0
        self._estimated_tokens = 0  # Approximate token usage tracking

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate a response from the LLM."""
        ...

    def _estimate_tokens(self, *texts: str) -> int:
        """Rough token estimation: ~4 chars per token for English text."""
        return sum(len(t) // 4 for t in texts if t)

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def estimated_tokens(self) -> int:
        return self._estimated_tokens


# ============================================================
# MCPLLMClient — Per-System LLM Client
# ============================================================

class MCPLLMClient:
    """
    LLM client for a single constellation system.
    Wraps an adapter with logging, error handling, call counting,
    and optional tool-augmented generation via MCPToolServer.
    """

    def __init__(self, system_name: str, adapter: LLMAdapter, tool_server=None):
        self.system_name = system_name
        self.adapter = adapter
        self.tool_server = tool_server  # Optional MCPToolServer
        self.total_calls = 0
        self.total_errors = 0
        self.total_estimated_tokens = 0

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate a response, with logging and error handling."""
        self.total_calls += 1
        try:
            result = await self.adapter.generate(prompt, system_prompt)
            # Track estimated tokens (prompt + system_prompt + response)
            est = self.adapter._estimate_tokens(prompt, system_prompt, result)
            self.adapter._estimated_tokens += est
            self.total_estimated_tokens += est
            logger.debug(
                f"[MCP:{self.system_name}] LLM call #{self.total_calls} "
                f"→ {len(result)} chars (~{est} tokens)"
            )
            return result
        except Exception as e:
            self.total_errors += 1
            logger.error(f"[MCP:{self.system_name}] LLM error: {e}")
            return f"[LLM_ERROR] {self.system_name}: {e}"

    async def generate_with_tools(self, prompt: str, system_prompt: str = "") -> dict:
        """
        Tool-augmented generation:
        1. Inject tool schemas into the system prompt
        2. Generate LLM response
        3. If response contains a tool_call, execute it and return result
        4. Otherwise return the text response
        """
        import json

        # Inject tool info into system prompt
        tool_block = ""
        if self.tool_server:
            tool_block = self.tool_server.get_tool_prompt_block()

        augmented_prompt = system_prompt
        if tool_block:
            augmented_prompt = f"{system_prompt}\n\n{tool_block}"

        response = await self.generate(prompt, augmented_prompt)

        # Try to parse tool_call from the response
        tool_call = self._extract_tool_call(response)
        if tool_call and self.tool_server:
            tool_result = await self.tool_server.handle_request({
                "method": "tools/call",
                "params": {
                    "name": tool_call["name"],
                    "arguments": tool_call.get("arguments", {}),
                },
            })
            return {
                "type": "tool_result",
                "tool_name": tool_call["name"],
                "result": tool_result.get("result", {}),
                "original_response": response,
            }

        return {
            "type": "text",
            "content": response,
        }

    def _extract_tool_call(self, response: str) -> Optional[dict]:
        """Try to extract a tool_call JSON from the LLM response."""
        import json
        try:
            # Look for {"tool_call": ...} pattern
            if "tool_call" in response:
                # Try parsing the whole response as JSON
                data = json.loads(response)
                if isinstance(data, dict) and "tool_call" in data:
                    return data["tool_call"]
        except (json.JSONDecodeError, KeyError):
            pass

        # Try to find JSON block within text
        try:
            start = response.index('{"tool_call"')
            depth = 0
            for i in range(start, len(response)):
                if response[i] == '{':
                    depth += 1
                elif response[i] == '}':
                    depth -= 1
                    if depth == 0:
                        data = json.loads(response[start:i+1])
                        return data.get("tool_call")
        except (ValueError, json.JSONDecodeError):
            pass

        return None

    def get_status(self) -> dict:
        return {
            "system": self.system_name,
            "provider": type(self.adapter).__name__,
            "model": self.adapter.model,
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
            "estimated_tokens": self.total_estimated_tokens,
            "tool_server": self.tool_server is not None,
        }


# ============================================================
# Factory
# ============================================================

def create_adapter(config: LLMConfig) -> LLMAdapter:
    """Create an LLM adapter from configuration."""
    provider = config.provider.lower().strip()

    if provider == "gemini":
        from mcp.adapters.gemini import GeminiAdapter
        return GeminiAdapter(model=config.model, api_key=config.api_key)
    elif provider == "openai":
        from mcp.adapters.openai import OpenAIAdapter
        return OpenAIAdapter(model=config.model, api_key=config.api_key)
    elif provider == "ollama":
        from mcp.adapters.ollama import OllamaAdapter
        return OllamaAdapter(
            model=config.model,
            url=config.url or "http://localhost:11434",
        )
    elif provider == "simulation":
        from mcp.adapters.simulation import SimulationAdapter
        return SimulationAdapter(model=config.model)
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'")


def create_llm_client(system_name: str, config: LLMConfig, tool_server=None) -> MCPLLMClient:
    """Create a full LLM client for a constellation system."""
    adapter = create_adapter(config)
    return MCPLLMClient(system_name=system_name, adapter=adapter, tool_server=tool_server)

"""
INTI — Ollama LLM Adapter
================================
Connects to a local Ollama instance via HTTP.
"""

from __future__ import annotations

import aiohttp

from mcp.adapter import LLMAdapter


class OllamaAdapter(LLMAdapter):
    """Adapter for local Ollama API."""

    def __init__(
        self,
        model: str = "llama3.2",
        url: str = "http://localhost:11434",
        api_key: str = "",
    ):
        super().__init__(model=model, api_key=api_key, url=url)

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self._call_count += 1

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                data = await resp.json()
                return data.get("response", "")

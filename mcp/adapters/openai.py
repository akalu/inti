"""
INTI — OpenAI LLM Adapter
================================
Uses the openai SDK (compatible with OpenAI and Azure OpenAI).
"""

from __future__ import annotations

from mcp.adapter import LLMAdapter


class OpenAIAdapter(LLMAdapter):
    """Adapter for OpenAI API."""

    def __init__(self, model: str = "gpt-4o", api_key: str = ""):
        super().__init__(model=model, api_key=api_key)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self._call_count += 1
        client = self._get_client()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return response.choices[0].message.content or ""

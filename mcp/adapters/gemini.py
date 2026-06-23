"""
INTI — Google Gemini LLM Adapter
======================================
Uses the google-genai SDK.
"""

from __future__ import annotations

from mcp.adapter import LLMAdapter


class GeminiAdapter(LLMAdapter):
    """Adapter for Google Gemini API."""

    def __init__(self, model: str = "gemini-2.0-flash", api_key: str = ""):
        super().__init__(model=model, api_key=api_key)
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        self._call_count += 1
        client = self._get_client()

        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        response = client.models.generate_content(
            model=self.model,
            contents=full_prompt,
        )
        return response.text or ""

"""
INTI - TAS (AI Agent Version) — Web Browser Tool
================================
Lightweight web page fetcher and content extractor.
Uses aiohttp + BeautifulSoup for text extraction (no headless browser needed).

Risk: LOW — read-only web scraping.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import aiohttp

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

MAX_PAGE_SIZE = 2_000_000  # 2MB max page size


class WebBrowserTool(Tool):
    """Fetch web pages and extract readable text content."""

    name = "web_browser"
    description = (
        "Fetch a web page and extract its text content. "
        "Supports actions: fetch (get text), raw (get HTML), headers (get response headers). "
        "Read-only — does not execute JavaScript."
    )
    category = ToolCategory.BROWSER
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("url", "URL to fetch", "string", True),
        ToolParam("action", "One of: fetch (text), raw (HTML), headers", "string", False, "fetch"),
        ToolParam("timeout", "Timeout in seconds (default 30)", "int", False, 30),
        ToolParam("max_chars", "Max characters to return (default 10000)", "int", False, 10000),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        url = kwargs.get("url", "").strip()
        action = kwargs.get("action", "fetch").lower()
        timeout = min(kwargs.get("timeout", 30), 60)
        max_chars = kwargs.get("max_chars", 10000)

        if not url:
            return ToolResult(success=False, error="Missing 'url' parameter")

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; INTI - TAS (AI Agent Version)/1.0; "
                        "Cognitive Constellation Web Fetcher)"
                    ),
                }
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    max_field_size=MAX_PAGE_SIZE,
                ) as resp:
                    if action == "headers":
                        return ToolResult(
                            success=True,
                            output={
                                "status": resp.status,
                                "headers": dict(resp.headers),
                                "url": str(resp.url),
                            },
                        )

                    raw_bytes = await resp.read()
                    if len(raw_bytes) > MAX_PAGE_SIZE:
                        raw_bytes = raw_bytes[:MAX_PAGE_SIZE]

                    html = raw_bytes.decode("utf-8", errors="replace")

                    if action == "raw":
                        return ToolResult(
                            success=True,
                            output=html[:max_chars],
                            metadata={
                                "url": str(resp.url),
                                "status": resp.status,
                                "size": len(html),
                                "truncated": len(html) > max_chars,
                            },
                        )

                    # Default: extract text
                    text = self._extract_text(html)
                    return ToolResult(
                        success=True,
                        output=text[:max_chars],
                        metadata={
                            "url": str(resp.url),
                            "status": resp.status,
                            "text_length": len(text),
                            "truncated": len(text) > max_chars,
                        },
                    )

        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"HTTP error: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _extract_text(self, html: str) -> str:
        """
        Extract readable text from HTML.
        Uses BeautifulSoup if available, falls back to regex stripping.
        """
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()

            text = soup.get_text(separator="\n", strip=True)
        except ImportError:
            # Fallback: regex-based HTML stripping
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

        # Clean up excessive whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

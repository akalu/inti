"""
INTI - TAS (AI Agent Version) — Web Search Tool
================================
Autonomous knowledge acquisition from secondary sources.

Enables the constellation to search the web for documentation,
error solutions, API references, and general knowledge.
This implements the Intellect System's mandate to "acquire and apply
knowledge from secondary sources" (Figueroa PPT slide 46).

Risk: LOW — read-only web search, no state mutation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from urllib.parse import quote_plus

import aiohttp

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Max results to return
MAX_RESULTS = 8
# Max content length per snippet
MAX_SNIPPET_LENGTH = 500
# Request timeout
SEARCH_TIMEOUT = 15


class WebSearchTool(Tool):
    """
    Search the web for information, documentation, and error solutions.

    Uses DuckDuckGo Lite (HTML scraping) as a free, no-API-key search engine.
    Falls back to DuckDuckGo Instant Answer API for quick facts.

    Ref: Figueroa PPT slide 46 — "Records, files, and processes for use
    all information acquired from secondary sources."
    """

    name = "web_search"
    description = (
        "Search the web for information: documentation, error solutions, "
        "API references, tutorials, or general knowledge. Returns titles, "
        "URLs, and text snippets from search results. Use this when you "
        "encounter an unknown error, need documentation, or want to learn "
        "something new."
    )
    category = ToolCategory.NETWORK
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("query", "The search query string", "string", True),
        ToolParam(
            "max_results",
            "Maximum number of results to return (default 5, max 8)",
            "int", False, 5,
        ),
        ToolParam(
            "search_type",
            "Type of search: 'general', 'documentation', 'error', 'api_reference'",
            "string", False, "general",
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        query = kwargs.get("query", "")
        max_results = min(kwargs.get("max_results", 5), MAX_RESULTS)
        search_type = kwargs.get("search_type", "general")

        if not query:
            return ToolResult(success=False, error="Missing 'query' parameter")

        # Enhance query based on search type
        enhanced_query = self._enhance_query(query, search_type)

        # Try DuckDuckGo HTML search first
        results = await self._search_ddg_html(enhanced_query, max_results)

        # Fallback to DuckDuckGo Instant Answer API
        if not results:
            results = await self._search_ddg_api(enhanced_query)

        if results:
            formatted = self._format_results(results)
            return ToolResult(
                success=True,
                output=formatted,
                metadata={
                    "query": query,
                    "enhanced_query": enhanced_query,
                    "result_count": len(results),
                    "search_type": search_type,
                },
            )
        else:
            return ToolResult(
                success=True,
                output=f"No results found for: {query}",
                metadata={"query": query, "result_count": 0},
            )

    def _enhance_query(self, query: str, search_type: str) -> str:
        """Enhance query based on search type for better results."""
        if search_type == "documentation":
            return f"{query} documentation reference"
        elif search_type == "error":
            return f"{query} fix solution"
        elif search_type == "api_reference":
            return f"{query} API reference docs"
        return query

    async def _search_ddg_html(
        self, query: str, max_results: int
    ) -> list[dict]:
        """Search DuckDuckGo via HTML scraping (Lite version)."""
        url = "https://lite.duckduckgo.com/lite/"
        params = {"q": query, "kl": "us-en"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    data=params,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"[WEB_SEARCH] DDG HTML returned {resp.status}")
                        return []
                    html = await resp.text()
                    return self._parse_ddg_html(html, max_results)
        except Exception as e:
            logger.warning(f"[WEB_SEARCH] DDG HTML search failed: {e}")
            return []

    def _parse_ddg_html(self, html: str, max_results: int) -> list[dict]:
        """Parse DuckDuckGo Lite HTML results."""
        results = []

        # Simple HTML parsing without BeautifulSoup
        # DDG Lite has a simple structure with links in <a> tags
        # and snippets in <td> elements
        import re

        # Find result links — DDG Lite uses class="result-link"
        link_pattern = re.compile(
            r'<a[^>]+class="result-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )
        # Also try the generic result pattern
        if not link_pattern.findall(html):
            link_pattern = re.compile(
                r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )

        links = link_pattern.findall(html)

        # Find snippets — DDG Lite puts them in <td class="result-snippet">
        snippet_pattern = re.compile(
            r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
            re.DOTALL | re.IGNORECASE,
        )
        snippets = snippet_pattern.findall(html)

        # Also try a broader snippet extraction
        if not snippets:
            snippet_pattern = re.compile(
                r'<span[^>]*class="[^"]*snippet[^"]*"[^>]*>(.*?)</span>',
                re.DOTALL | re.IGNORECASE,
            )
            snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(links[:max_results]):
            if not url or url.startswith("/") or "duckduckgo.com" in url:
                continue

            # Clean HTML from title
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            if not clean_title:
                continue

            # Get corresponding snippet
            snippet = ""
            if i < len(snippets):
                snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
                snippet = snippet[:MAX_SNIPPET_LENGTH]

            results.append({
                "title": clean_title,
                "url": url,
                "snippet": snippet,
            })

        return results

    async def _search_ddg_api(self, query: str) -> list[dict]:
        """Fallback: DuckDuckGo Instant Answer API."""
        url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "INTI - TAS (AI Agent Version)/1.0"},
                    timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT),
                ) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)
                    return self._parse_ddg_api(data)
        except Exception as e:
            logger.warning(f"[WEB_SEARCH] DDG API search failed: {e}")
            return []

    def _parse_ddg_api(self, data: dict) -> list[dict]:
        """Parse DuckDuckGo Instant Answer API response."""
        results = []

        # Abstract (if available)
        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", "Summary"),
                "url": data.get("AbstractURL", ""),
                "snippet": data["Abstract"][:MAX_SNIPPET_LENGTH],
            })

        # Related topics
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:100],
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", "")[:MAX_SNIPPET_LENGTH],
                })

        # Infobox
        if data.get("Infobox") and data["Infobox"].get("content"):
            info_text = "; ".join(
                f"{item.get('label', '')}: {item.get('value', '')}"
                for item in data["Infobox"]["content"][:5]
            )
            results.append({
                "title": f"Quick Info: {data.get('Heading', '')}",
                "url": data.get("AbstractURL", ""),
                "snippet": info_text[:MAX_SNIPPET_LENGTH],
            })

        return results

    def _format_results(self, results: list[dict]) -> str:
        """Format results as a readable string for the constellation."""
        lines = [f"Found {len(results)} result(s):\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r['title']}")
            if r.get("url"):
                lines.append(f"    URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"    {r['snippet']}")
            lines.append("")
        return "\n".join(lines)

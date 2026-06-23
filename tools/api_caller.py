"""
INTI - TAS (AI Agent Version) — API Caller Tool
==============================
Generic HTTP client for making API requests.

Risk: MEDIUM — outbound network requests with domain restrictions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiohttp

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Allowed domains by default (empty = allow all)
# Populate this to restrict outbound requests
DEFAULT_ALLOWED_DOMAINS: list[str] = []

# Always blocked domains
BLOCKED_DOMAINS: list[str] = [
    "localhost", "127.0.0.1", "0.0.0.0",
    "169.254.169.254",  # AWS metadata endpoint
    "metadata.google.internal",  # GCP metadata endpoint
]

MAX_RESPONSE_SIZE = 1_000_000  # 1MB


class APICallerTool(Tool):
    """Make HTTP requests to external APIs."""

    name = "api_caller"
    description = (
        "Make HTTP requests (GET, POST, PUT, DELETE) to external APIs. "
        "Supports custom headers and JSON body. "
        "Response is truncated at 1MB."
    )
    category = ToolCategory.NETWORK
    risk_level = RiskLevel.MEDIUM
    parameters = [
        ToolParam("method", "HTTP method: GET, POST, PUT, DELETE", "string", True),
        ToolParam("url", "Full URL to request", "string", True),
        ToolParam("headers", "Optional dict of HTTP headers", "dict", False),
        ToolParam("body", "Optional request body (dict for JSON, str for raw)", "dict", False),
        ToolParam("timeout", "Timeout in seconds (default 30)", "int", False, 30),
    ]

    def __init__(self, allowed_domains: Optional[list[str]] = None):
        self._allowed_domains = allowed_domains or DEFAULT_ALLOWED_DOMAINS

    def _check_domain(self, url: str) -> Optional[str]:
        """Validate the URL domain against allowlists and blocklists."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.hostname or ""

        # Check blocklist
        for blocked in BLOCKED_DOMAINS:
            if domain == blocked or domain.endswith(f".{blocked}"):
                return f"Domain blocked: {domain}"

        # Check allowlist (if configured)
        if self._allowed_domains:
            allowed = any(
                domain == d or domain.endswith(f".{d}")
                for d in self._allowed_domains
            )
            if not allowed:
                return f"Domain not in allowlist: {domain}"

        return None

    async def execute(self, **kwargs) -> ToolResult:
        method = kwargs.get("method", "GET").upper()
        url = kwargs.get("url", "")
        headers = kwargs.get("headers", {})
        body = kwargs.get("body")
        timeout = min(kwargs.get("timeout", 30), 120)

        if not url:
            return ToolResult(success=False, error="Missing 'url' parameter")

        if method not in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"}:
            return ToolResult(success=False, error=f"Invalid method: {method}")

        # Domain check
        domain_error = self._check_domain(url)
        if domain_error:
            return ToolResult(success=False, error=domain_error)

        try:
            async with aiohttp.ClientSession() as session:
                request_kwargs = {
                    "headers": headers or {},
                    "timeout": aiohttp.ClientTimeout(total=timeout),
                }

                if body and method in {"POST", "PUT", "PATCH"}:
                    if isinstance(body, dict):
                        request_kwargs["json"] = body
                    else:
                        request_kwargs["data"] = str(body)

                async with session.request(method, url, **request_kwargs) as resp:
                    # Read response with size limit
                    raw = await resp.read()
                    if len(raw) > MAX_RESPONSE_SIZE:
                        raw = raw[:MAX_RESPONSE_SIZE]

                    # Try to parse as JSON
                    try:
                        content = json.loads(raw)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        content = raw.decode("utf-8", errors="replace")

                    return ToolResult(
                        success=200 <= resp.status < 400,
                        output=content,
                        error="" if resp.status < 400 else f"HTTP {resp.status}",
                        metadata={
                            "status_code": resp.status,
                            "url": url,
                            "method": method,
                            "content_type": resp.content_type,
                            "response_size": len(raw),
                        },
                    )

        except aiohttp.ClientError as e:
            return ToolResult(success=False, error=f"HTTP error: {e}")
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"Request timed out after {timeout}s",
                metadata={"url": url, "timeout": timeout},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

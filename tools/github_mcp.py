"""
INTI - TAS (AI Agent Version) — GitHub MCP Tool
==============================
Browse, evaluate, and download tools from GitHub repositories.

Uses GitHub REST API (no MCP server needed — direct HTTP).
Requires GITHUB_TOKEN in .env.services for higher rate limits.

Actions:
  search        — search GitHub repos by keyword/topic
  read_repo     — get README, file list, languages, stars
  read_file     — read a specific file from a repo
  download_tool — clone a repo into tools_community/
  list_community — list installed community tools

Risk: MEDIUM — downloads code from the internet.
       All downloads are scanned by tool_scanner before registration.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

GITHUB_API = "https://api.github.com"


class GitHubMCPTool(Tool):
    """
    Interact with GitHub to search, evaluate, and download tools.
    All downloaded tools are malware-scanned before registration.
    """

    name = "github_mcp"
    description = (
        "Search GitHub repos, read code/READMEs, and download tools "
        "for KRONOS. Downloads are scanned for malware before use. "
        "Actions: search, read_repo, read_file, download_tool, list_community."
    )
    category = ToolCategory.NETWORK
    risk_level = RiskLevel.MEDIUM
    parameters = [
        ToolParam("action", "One of: search, read_repo, read_file, download_tool, list_community", "string", True),
        ToolParam("query", "Search query (for search action)", "string", False),
        ToolParam("repo", "Repository in 'owner/name' format", "string", False),
        ToolParam("path", "File path within the repo (for read_file)", "string", False),
        ToolParam("branch", "Branch name (default: main)", "string", False, "main"),
        ToolParam("topic", "GitHub topic filter (for search)", "string", False),
        ToolParam("max_results", "Max search results (default 5)", "int", False, 5),
    ]

    def __init__(self):
        self._session_headers = None

    def _get_headers(self) -> dict:
        """Get auth headers, caching the token lookup."""
        if self._session_headers is None:
            from config.settings import load_service_env
            token = load_service_env("GITHUB_TOKEN")
            self._session_headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "KRONOS-ISHM/1.0",
            }
            if token:
                self._session_headers["Authorization"] = f"token {token}"
        return self._session_headers

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if action == "search":
            return await self._search(kwargs)
        elif action == "read_repo":
            return await self._read_repo(kwargs)
        elif action == "read_file":
            return await self._read_file(kwargs)
        elif action == "download_tool":
            return await self._download_tool(kwargs)
        elif action == "list_community":
            return self._list_community()
        else:
            return ToolResult(
                success=False,
                error=f"Unknown action: {action}. "
                      f"Use: search, read_repo, read_file, download_tool, list_community",
            )

    # ================================================================
    # Action: search
    # ================================================================

    async def _search(self, kwargs: dict) -> ToolResult:
        """Search GitHub repositories."""
        import asyncio

        query = kwargs.get("query", "")
        topic = kwargs.get("topic", "")
        max_results = min(kwargs.get("max_results", 5), 20)

        if not query:
            return ToolResult(success=False, error="Missing 'query' parameter")

        search_q = query
        if topic:
            search_q += f" topic:{topic}"

        try:
            import requests
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.get(
                    f"{GITHUB_API}/search/repositories",
                    params={"q": search_q, "sort": "stars", "per_page": max_results},
                    headers=self._get_headers(),
                    timeout=10,
                ),
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("items", [])[:max_results]:
                results.append({
                    "name": item.get("full_name"),
                    "description": (item.get("description") or "")[:200],
                    "stars": item.get("stargazers_count", 0),
                    "language": item.get("language"),
                    "topics": item.get("topics", [])[:5],
                    "updated": item.get("updated_at", "")[:10],
                    "url": item.get("html_url"),
                    "license": (item.get("license") or {}).get("spdx_id", "none"),
                })

            return ToolResult(
                success=True,
                output=results,
                metadata={
                    "total_count": data.get("total_count", 0),
                    "results_returned": len(results),
                },
            )

        except ImportError:
            return ToolResult(success=False, error="requests library not installed")
        except Exception as e:
            return ToolResult(success=False, error=f"GitHub search failed: {e}")

    # ================================================================
    # Action: read_repo
    # ================================================================

    async def _read_repo(self, kwargs: dict) -> ToolResult:
        """Get repo info: README, file tree, languages."""
        import asyncio

        repo = kwargs.get("repo", "")
        if not repo or "/" not in repo:
            return ToolResult(success=False, error="'repo' must be 'owner/name' format")

        try:
            import requests
            loop = asyncio.get_event_loop()
            headers = self._get_headers()

            # Fetch repo info
            info_resp = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    f"{GITHUB_API}/repos/{repo}",
                    headers=headers, timeout=10,
                ),
            )
            info_resp.raise_for_status()
            info = info_resp.json()

            # Fetch README
            readme_text = ""
            try:
                readme_resp = await loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        f"{GITHUB_API}/repos/{repo}/readme",
                        headers={**headers, "Accept": "application/vnd.github.raw+json"},
                        timeout=10,
                    ),
                )
                if readme_resp.status_code == 200:
                    readme_text = readme_resp.text[:3000]
            except Exception:
                pass

            # Fetch top-level files
            files = []
            try:
                tree_resp = await loop.run_in_executor(
                    None,
                    lambda: requests.get(
                        f"{GITHUB_API}/repos/{repo}/contents/",
                        headers=headers, timeout=10,
                    ),
                )
                if tree_resp.status_code == 200:
                    for f in tree_resp.json()[:30]:
                        files.append({
                            "name": f.get("name"),
                            "type": f.get("type"),
                            "size": f.get("size", 0),
                        })
            except Exception:
                pass

            return ToolResult(
                success=True,
                output={
                    "name": info.get("full_name"),
                    "description": info.get("description", ""),
                    "stars": info.get("stargazers_count", 0),
                    "forks": info.get("forks_count", 0),
                    "language": info.get("language"),
                    "license": (info.get("license") or {}).get("spdx_id", "none"),
                    "topics": info.get("topics", []),
                    "default_branch": info.get("default_branch", "main"),
                    "open_issues": info.get("open_issues_count", 0),
                    "created": info.get("created_at", "")[:10],
                    "updated": info.get("updated_at", "")[:10],
                    "readme_preview": readme_text,
                    "files": files,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read repo: {e}")

    # ================================================================
    # Action: read_file
    # ================================================================

    async def _read_file(self, kwargs: dict) -> ToolResult:
        """Read a specific file from a repository."""
        import asyncio

        repo = kwargs.get("repo", "")
        path = kwargs.get("path", "")
        branch = kwargs.get("branch", "main")

        if not repo or not path:
            return ToolResult(success=False, error="Need 'repo' and 'path' parameters")

        try:
            import requests
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.get(
                    f"{GITHUB_API}/repos/{repo}/contents/{path}",
                    params={"ref": branch},
                    headers={
                        **self._get_headers(),
                        "Accept": "application/vnd.github.raw+json",
                    },
                    timeout=10,
                ),
            )

            if resp.status_code == 404:
                return ToolResult(success=False, error=f"File not found: {path}")

            resp.raise_for_status()
            content = resp.text[:15000]  # Limit content size

            return ToolResult(
                success=True,
                output=content,
                metadata={
                    "repo": repo,
                    "path": path,
                    "branch": branch,
                    "chars": len(content),
                    "truncated": len(resp.text) > 15000,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read file: {e}")

    # ================================================================
    # Action: download_tool
    # ================================================================

    async def _download_tool(self, kwargs: dict) -> ToolResult:
        """
        Download a GitHub repo into tools_community/ and scan for malware.
        Returns scan results — does NOT auto-register (requires approval).
        """
        import asyncio
        import zipfile
        import io

        repo = kwargs.get("repo", "")
        branch = kwargs.get("branch", "main")

        if not repo or "/" not in repo:
            return ToolResult(success=False, error="'repo' must be 'owner/name' format")

        from config.settings import COMMUNITY_TOOLS_DIR

        # Tool directory name from repo
        tool_name = repo.split("/")[-1].lower().replace("-", "_")
        tool_dir = COMMUNITY_TOOLS_DIR / tool_name

        if tool_dir.exists():
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' already exists in tools_community/. "
                      f"Remove it first to re-download.",
            )

        try:
            import requests

            # Download repo as zip
            zip_url = f"https://github.com/{repo}/archive/refs/heads/{branch}.zip"
            logger.info(f"[GITHUB] Downloading {repo} ({branch})...")

            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.get(zip_url, timeout=30, stream=True),
            )
            resp.raise_for_status()

            # Extract to tools_community/
            COMMUNITY_TOOLS_DIR.mkdir(parents=True, exist_ok=True)

            zip_data = io.BytesIO(resp.content)
            with zipfile.ZipFile(zip_data) as zf:
                # GitHub zips have a top-level folder like "repo-branch/"
                members = zf.namelist()
                prefix = members[0] if members else ""

                tool_dir.mkdir(parents=True, exist_ok=True)
                for member in members:
                    if member.endswith("/"):
                        continue
                    # Strip the top-level folder
                    relative = member[len(prefix):] if prefix else member
                    if not relative:
                        continue
                    target = tool_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(member))

            logger.info(f"[GITHUB] Extracted to {tool_dir}")

            # Run malware scan
            from tools.tool_scanner import ToolScannerTool
            scanner = ToolScannerTool()
            scan_result = scanner._scan_directory(tool_dir)
            scan_data = scan_result.output if scan_result.success else {}

            # Update manifest
            self._update_manifest(tool_name, repo, branch, scan_data)

            risk_score = scan_data.get("max_risk_score", 0)
            verdict = scan_data.get("verdict", "unknown")

            if risk_score >= 0.7:
                # Quarantine: rename with _QUARANTINE suffix
                quarantine_dir = tool_dir.with_name(f"_QUARANTINE_{tool_name}")
                tool_dir.rename(quarantine_dir)
                logger.warning(
                    f"[GITHUB] Tool '{tool_name}' QUARANTINED — risk score {risk_score}"
                )
                return ToolResult(
                    success=False,
                    error=(
                        f"Tool '{tool_name}' failed malware scan (score: {risk_score}, "
                        f"verdict: {verdict}). Moved to quarantine. "
                        f"Review: {quarantine_dir}"
                    ),
                    metadata={"scan": scan_data},
                )

            return ToolResult(
                success=True,
                output={
                    "tool_name": tool_name,
                    "repo": repo,
                    "branch": branch,
                    "installed_to": str(tool_dir),
                    "scan_verdict": verdict,
                    "scan_risk_score": risk_score,
                    "files_scanned": scan_data.get("files_scanned", 0),
                    "status": (
                        "Downloaded and scanned. "
                        "Use register_community_tools() to activate, "
                        "or review the code first."
                    ),
                },
                metadata={"scan": scan_data},
            )

        except Exception as e:
            # Cleanup on failure
            if tool_dir.exists():
                shutil.rmtree(tool_dir, ignore_errors=True)
            return ToolResult(success=False, error=f"Download failed: {e}")

    # ================================================================
    # Action: list_community
    # ================================================================

    def _list_community(self) -> ToolResult:
        """List all installed community tools and their scan status."""
        from config.settings import COMMUNITY_TOOLS_DIR

        manifest = self._read_manifest()
        installed = []

        if COMMUNITY_TOOLS_DIR.exists():
            for d in COMMUNITY_TOOLS_DIR.iterdir():
                if d.is_dir() and not d.name.startswith("_"):
                    entry = next(
                        (m for m in manifest if m["name"] == d.name), {}
                    )
                    has_tool_py = (d / "tool.py").exists()
                    installed.append({
                        "name": d.name,
                        "repo": entry.get("repo", "unknown"),
                        "scan_verdict": entry.get("scan_verdict", "unknown"),
                        "scan_score": entry.get("scan_score", 0),
                        "downloaded_at": entry.get("downloaded_at", ""),
                        "has_tool_py": has_tool_py,
                        "registrable": has_tool_py,
                    })

        return ToolResult(
            success=True,
            output={
                "community_tools": installed,
                "total": len(installed),
                "manifest_entries": len(manifest),
            },
        )

    # ================================================================
    # Manifest Management
    # ================================================================

    def _read_manifest(self) -> list[dict]:
        """Read the community tools manifest."""
        from config.settings import COMMUNITY_TOOLS_DIR
        manifest_path = COMMUNITY_TOOLS_DIR / "_manifest.json"
        if manifest_path.exists():
            try:
                return json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def _update_manifest(
        self, tool_name: str, repo: str, branch: str, scan_data: dict
    ):
        """Add or update a tool entry in the manifest."""
        from config.settings import COMMUNITY_TOOLS_DIR

        COMMUNITY_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = COMMUNITY_TOOLS_DIR / "_manifest.json"

        manifest = self._read_manifest()

        # Remove existing entry for this tool
        manifest = [m for m in manifest if m["name"] != tool_name]

        manifest.append({
            "name": tool_name,
            "repo": repo,
            "branch": branch,
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "scan_verdict": scan_data.get("verdict", "unknown"),
            "scan_score": scan_data.get("max_risk_score", 0),
            "files_scanned": scan_data.get("files_scanned", 0),
        })

        manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

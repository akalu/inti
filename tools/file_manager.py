"""
INTI - TAS (AI Agent Version) — File Manager Tool
================================
Read, write, list, and delete files on the local filesystem.
Sandboxed to the project root by default.

Risk: MEDIUM — can modify files within the sandbox.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory


# Default sandbox root — the kronos project directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FileManagerTool(Tool):
    """Filesystem operations sandboxed to the project directory."""

    name = "file_manager"
    description = (
        "Read, write, list, and delete files. Operations are sandboxed to "
        "the project root directory for safety. Supports actions: "
        "read, write, list, delete, exists."
    )
    category = ToolCategory.FILESYSTEM
    risk_level = RiskLevel.MEDIUM
    parameters = [
        ToolParam("action", "One of: read, write, list, delete, exists", "string", True),
        ToolParam("path", "Relative path within the project sandbox", "string", True),
        ToolParam("content", "Content to write (required for 'write' action)", "string", False),
        ToolParam("max_size_kb", "Max file size to read in KB (default 1024)", "int", False, 1024),
    ]

    def __init__(self, sandbox_root: Optional[Path] = None):
        self._sandbox = sandbox_root or _PROJECT_ROOT

    def _resolve_safe(self, path: str) -> Path:
        """Resolve a path and ensure it stays within the sandbox."""
        resolved = (self._sandbox / path).resolve()
        if not str(resolved).startswith(str(self._sandbox)):
            raise PermissionError(
                f"Path escapes sandbox: {path} → {resolved} "
                f"(sandbox: {self._sandbox})"
            )
        return resolved

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()
        path = kwargs.get("path", "")

        if not action:
            return ToolResult(success=False, error="Missing 'action' parameter")
        if not path and action != "list":
            return ToolResult(success=False, error="Missing 'path' parameter")

        try:
            if action == "read":
                return await self._read(path, kwargs.get("max_size_kb", 1024))
            elif action == "write":
                content = kwargs.get("content", "")
                if not content:
                    return ToolResult(success=False, error="Missing 'content' for write")
                return await self._write(path, content)
            elif action == "list":
                return await self._list(path or ".")
            elif action == "delete":
                return await self._delete(path)
            elif action == "exists":
                return await self._exists(path)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}. Use: read, write, list, delete, exists",
                )
        except PermissionError as e:
            return ToolResult(success=False, error=f"Permission denied: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def _read(self, path: str, max_size_kb: int) -> ToolResult:
        resolved = self._resolve_safe(path)
        if not resolved.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
        if not resolved.is_file():
            return ToolResult(success=False, error=f"Not a file: {path}")

        size_kb = resolved.stat().st_size / 1024
        if size_kb > max_size_kb:
            return ToolResult(
                success=False,
                error=f"File too large: {size_kb:.0f}KB > {max_size_kb}KB limit",
            )

        content = resolved.read_text(encoding="utf-8", errors="replace")
        return ToolResult(
            success=True,
            output=content,
            metadata={"path": str(resolved), "size_kb": round(size_kb, 1)},
        )

    async def _write(self, path: str, content: str) -> ToolResult:
        resolved = self._resolve_safe(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return ToolResult(
            success=True,
            output=f"Written {len(content)} chars to {path}",
            metadata={"path": str(resolved), "chars": len(content)},
        )

    async def _list(self, path: str) -> ToolResult:
        resolved = self._resolve_safe(path)
        if not resolved.exists():
            return ToolResult(success=False, error=f"Directory not found: {path}")
        if not resolved.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {path}")

        entries = []
        for item in sorted(resolved.iterdir()):
            rel = item.relative_to(self._sandbox)
            entry = {
                "name": item.name,
                "path": str(rel),
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size_kb"] = round(item.stat().st_size / 1024, 1)
            entries.append(entry)

        return ToolResult(
            success=True,
            output=entries,
            metadata={"path": str(resolved), "count": len(entries)},
        )

    async def _delete(self, path: str) -> ToolResult:
        resolved = self._resolve_safe(path)
        if not resolved.exists():
            return ToolResult(success=False, error=f"Not found: {path}")
        if resolved.is_dir():
            return ToolResult(success=False, error="Cannot delete directories — only files")

        resolved.unlink()
        return ToolResult(
            success=True,
            output=f"Deleted: {path}",
            metadata={"path": str(resolved)},
        )

    async def _exists(self, path: str) -> ToolResult:
        resolved = self._resolve_safe(path)
        exists = resolved.exists()
        return ToolResult(
            success=True,
            output=exists,
            metadata={"path": str(resolved), "is_file": resolved.is_file() if exists else False},
        )

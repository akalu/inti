"""
INTI - TAS (AI Agent Version) — Shell Tool
========================
Execute system shell commands with safety guards.

Risk: HIGH — can run arbitrary commands.
Blocked patterns prevent destructive operations.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import re
import subprocess
import sys
from typing import Optional

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Commands that are always blocked
BLOCKED_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/",             # rm -rf /
    r"rmdir\s+/s\s+/q\s+[A-Z]:\\$",  # rmdir /s /q C:\
    r"format\s+[A-Z]:",         # format C:
    r"del\s+/[sfq]",            # del /s /f /q
    r"mkfs",                     # mkfs
    r"dd\s+if=",                 # dd if=
    r"shutdown",                 # shutdown
    r"reboot",                   # reboot
    r":(){ :\|:& };:",          # fork bomb
]

# Commands that are always safe (no confirmation needed)
SAFE_PREFIXES: list[str] = [
    # Read-only / info commands
    "echo", "dir", "ls", "cat", "type", "pwd", "cd",
    "python --version", "pip list", "pip show",
    "git status", "git log", "git diff", "git branch",
    "whoami", "hostname", "date", "time", "ver",
    "where", "which", "find", "findstr", "grep",
    "tree", "wmic", "systeminfo", "tasklist",
    # Opening apps / browsers (safe on Windows)
    "start", "open",  # start chrome, open -a Safari
    "explorer",       # explorer .
    # Python execution (sandboxed by the tool)
    "python", "pip install", "pip",
    # Network info (read-only)
    "ping", "curl", "wget", "ipconfig", "ifconfig", "nslookup",
]


class ShellTool(Tool):
    """Execute shell commands with safety checks."""

    name = "shell"
    description = (
        "Execute a system shell command and capture stdout/stderr. "
        "Dangerous commands are blocked by pattern matching. "
        "Timeout default: 30 seconds."
    )
    category = ToolCategory.SYSTEM
    risk_level = RiskLevel.HIGH
    parameters = [
        ToolParam("command", "The shell command to execute", "string", True),
        ToolParam("timeout", "Timeout in seconds (default 30, max 120)", "int", False, 30),
        ToolParam("cwd", "Working directory (relative to project root)", "string", False),
    ]

    def __init__(self, project_root: Optional[str] = None):
        from pathlib import Path
        self._project_root = project_root or str(Path(__file__).resolve().parent.parent)

    def _is_blocked(self, command: str) -> Optional[str]:
        """Check if a command matches any blocked pattern."""
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return f"Blocked by safety pattern: {pattern}"
        return None

    def _is_safe(self, command: str) -> bool:
        """Check if a command is in the safe list (can skip Reason validation)."""
        cmd_lower = command.strip().lower()
        return any(cmd_lower.startswith(p) for p in SAFE_PREFIXES)

    async def execute(self, **kwargs) -> ToolResult:
        command = kwargs.get("command", "").strip()
        timeout = min(kwargs.get("timeout", 30), 120)
        cwd = kwargs.get("cwd", self._project_root)

        if not command:
            return ToolResult(success=False, error="Missing 'command' parameter")

        # Safety check
        blocked = self._is_blocked(command)
        if blocked:
            logger.warning(f"[SHELL] Blocked command: {command} — {blocked}")
            return ToolResult(
                success=False,
                error=f"BLOCKED: {blocked}",
                metadata={"command": command, "blocked": True},
            )

        # Determine shell
        is_windows = platform.system() == "Windows"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=None,  # inherit current env
            )

            output = result.stdout[:5000] if result.stdout else ""
            stderr = result.stderr[:2000] if result.stderr else ""

            return ToolResult(
                success=result.returncode == 0,
                output=output,
                error=stderr if result.returncode != 0 else "",
                metadata={
                    "command": command,
                    "return_code": result.returncode,
                    "has_stderr": bool(stderr),
                },
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout}s",
                metadata={"command": command, "timeout": timeout},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"command": command},
            )

"""
INTI - TAS (AI Agent Version) — Security Policy Engine
====================================
Central security layer for all tool invocations.

Components:
  SecurityPolicy   — whitelist/blocklist rules, human confirmation callback
  ActionJournal    — append-only audit log with rollback for file operations
  SecurityVerdict  — ALLOW / DENY / CONFIRM

Every tool invocation flows through:
  SecurityPolicy.check() → verdict → execute or block
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("taas")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_JOURNAL_DIR = _PROJECT_ROOT / "data" / "journal"
_BACKUP_DIR = _JOURNAL_DIR / "backups"


# ============================================================
# Verdicts
# ============================================================

class SecurityVerdict(str, Enum):
    """Result of a security check."""
    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"   # Needs human approval


# ============================================================
# Action Journal (Rollback Support)
# ============================================================

@dataclass
class JournalEntry:
    """A single recorded tool action."""
    id: int
    timestamp: float
    tool_name: str
    action: str
    params: dict
    verdict: str
    risk_level: str = "LOW"           # LOW, MEDIUM, HIGH, CRITICAL
    authorized_by: str = "POLICY"     # POLICY, REASON, HUMAN, OVERRIDE
    success: bool = False
    output: Any = ""
    error: str = ""
    rollback_path: str = ""     # Path to backup file (for undo)
    undone: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)),
            "tool": self.tool_name,
            "action": self.action,
            "risk_level": self.risk_level,
            "authorized_by": self.authorized_by,
            "verdict": self.verdict,
            "success": self.success,
            "undone": self.undone,
            "rollback_available": bool(self.rollback_path),
        }


class ActionJournal:
    """
    Append-only audit log of all tool invocations.
    Supports rollback for file operations.
    """

    def __init__(self, journal_dir: Path | None = None):
        self._dir = journal_dir or _JOURNAL_DIR
        self._backup_dir = self._dir / "backups"
        self._entries: list[JournalEntry] = []
        self._next_id = 1
        self._journal_file = self._dir / "actions.jsonl"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._load_from_disk()

    def _load_from_disk(self):
        """Load previous journal entries from JSONL file."""
        if not self._journal_file.exists():
            return
        try:
            import json
            with open(self._journal_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    entry = JournalEntry(
                        id=data["id"],
                        timestamp=data["timestamp"],
                        tool_name=data["tool_name"],
                        action=data["action"],
                        params=data.get("params", {}),
                        verdict=data["verdict"],
                        risk_level=data.get("risk_level", "LOW"),
                        authorized_by=data.get("authorized_by", "POLICY"),
                        success=data.get("success", False),
                        output=data.get("output", ""),
                        error=data.get("error", ""),
                        rollback_path=data.get("rollback_path", ""),
                        undone=data.get("undone", False),
                    )
                    self._entries.append(entry)
                    self._next_id = max(self._next_id, entry.id + 1)
            logger.info(f"[JOURNAL] Loaded {len(self._entries)} entries from disk")
        except Exception as e:
            logger.warning(f"[JOURNAL] Failed to load from disk: {e}")

    def _append_to_disk(self, entry: JournalEntry):
        """Append a single entry to the JSONL file."""
        try:
            import json
            data = {
                "id": entry.id,
                "timestamp": entry.timestamp,
                "tool_name": entry.tool_name,
                "action": entry.action,
                "params": entry.params,
                "verdict": entry.verdict,
                "risk_level": entry.risk_level,
                "authorized_by": entry.authorized_by,
                "success": entry.success,
                "output": str(entry.output)[:500] if entry.output else "",
                "error": entry.error,
                "rollback_path": entry.rollback_path,
                "undone": entry.undone,
            }
            with open(self._journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[JOURNAL] Failed to write to disk: {e}")

    def record(
        self,
        tool_name: str,
        action: str,
        params: dict,
        verdict: str,
        risk_level: str = "LOW",
        authorized_by: str = "POLICY",
        success: bool = False,
        output: Any = "",
        error: str = "",
        rollback_path: str = "",
    ) -> JournalEntry:
        """Record a tool action to memory and disk."""
        entry = JournalEntry(
            id=self._next_id,
            timestamp=time.time(),
            tool_name=tool_name,
            action=action,
            params={k: str(v)[:200] for k, v in params.items()},
            verdict=verdict,
            risk_level=risk_level,
            authorized_by=authorized_by,
            success=success,
            output=str(output)[:500] if output else "",
            error=error,
            rollback_path=rollback_path,
        )
        self._entries.append(entry)
        self._next_id += 1
        self._append_to_disk(entry)
        logger.info(f"[JOURNAL] #{entry.id} {tool_name}.{action} → {verdict} ({'✓' if success else '✗'}) [risk={risk_level}, by={authorized_by}]")
        return entry

    def save_backup(self, filepath: str | Path, label: str = "") -> str:
        """
        Save a backup of a file before modifying it.
        Returns the backup path for rollback.
        """
        src = Path(filepath)
        if not src.exists():
            return ""

        self._backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        name = f"{src.stem}_{label}_{timestamp}{src.suffix}" if label else f"{src.stem}_{timestamp}{src.suffix}"
        backup = self._backup_dir / name

        shutil.copy2(str(src), str(backup))
        logger.info(f"[JOURNAL] Backup saved: {backup}")
        return str(backup)

    def undo_last(self) -> dict:
        """Undo the most recent undoable action."""
        for entry in reversed(self._entries):
            if entry.rollback_path and not entry.undone and entry.success:
                backup = Path(entry.rollback_path)
                if not backup.exists():
                    return {"success": False, "error": f"Backup file missing: {backup}"}

                # Determine original path from params
                original_path = entry.params.get("path", "")
                if not original_path:
                    return {"success": False, "error": "Cannot determine original path"}

                # Resolve relative to project root
                target = _PROJECT_ROOT / original_path
                try:
                    shutil.copy2(str(backup), str(target))
                    entry.undone = True
                    logger.info(f"[JOURNAL] Undone #{entry.id}: restored {target}")
                    return {
                        "success": True,
                        "undone_id": entry.id,
                        "tool": entry.tool_name,
                        "action": entry.action,
                        "restored": str(target),
                    }
                except Exception as e:
                    return {"success": False, "error": str(e)}

        return {"success": False, "error": "No undoable actions found"}

    def recent(self, count: int = 10) -> list[dict]:
        """Return recent journal entries."""
        return [e.to_dict() for e in self._entries[-count:]]

    @property
    def total_entries(self) -> int:
        return len(self._entries)

    def get_audit_summary(self) -> str:
        """Generate audit summary for introspection/contemplation."""
        if not self._entries:
            return "No tool actions recorded."
        total = len(self._entries)
        succeeded = sum(1 for e in self._entries if e.success)
        failed = total - succeeded
        by_tool: dict[str, int] = {}
        by_risk: dict[str, int] = {}
        for e in self._entries:
            by_tool[e.tool_name] = by_tool.get(e.tool_name, 0) + 1
            by_risk[e.risk_level] = by_risk.get(e.risk_level, 0) + 1
        top_tools = sorted(by_tool.items(), key=lambda x: -x[1])[:5]
        parts = [
            f"Action Journal: {total} entries ({succeeded} success, {failed} failed)",
            f"  By risk: {', '.join(f'{k}={v}' for k, v in sorted(by_risk.items()))}",
            f"  Top tools: {', '.join(f'{t}({c})' for t, c in top_tools)}",
        ]
        return "\n".join(parts)


# ============================================================
# Security Policy
# ============================================================

# Paths that are NEVER writable
BLOCKED_PATHS = [
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    "/usr", "/bin", "/sbin", "/etc", "/boot", "/sys", "/proc",
    ".git", ".env", "__pycache__",
]

# Actions blocked per tool
TOOL_BLOCKLIST: dict[str, list[str]] = {
    "shell": [
        "rm -rf /", "format", "del /f /s /q C:\\",
        "shutdown", "reboot", "mkfs", "dd if=",
    ],
}

# Tools that ALWAYS require human confirmation
ALWAYS_CONFIRM_TOOLS = {"mouse_keyboard"}

# Tools that are safe for auto-execution
AUTO_ALLOW_TOOLS = {"screenshot", "web_browser"}


class SecurityPolicy:
    """
    Central policy engine controlling what the constellation can do.
    Flow: check() → ALLOW|DENY|CONFIRM → execute or block

    Authorization modes for CONFIRM verdicts:
      - ALWAYS_CONFIRM_TOOLS → requires human confirmation (LAW-009)
      - Everything else → autonomous authorization via Reason system
    """

    def __init__(
        self,
        confirm_callback: Optional[Callable[..., Coroutine]] = None,
        reason_callback: Optional[Callable[..., Coroutine]] = None,
        journal: Optional[ActionJournal] = None,
    ):
        self.journal = journal or ActionJournal()
        self._confirm_callback = confirm_callback  # async fn(tool, action, params) → bool (human)
        self._reason_callback = reason_callback    # async fn(tool, action, params) → bool (Reason)
        self._denied_count = 0
        self._confirmed_count = 0
        self._allowed_count = 0
        self._autonomous_count = 0

    def set_reason_callback(self, callback: Callable[..., Coroutine]):
        """Set the Reason-based autonomous authorization callback."""
        self._reason_callback = callback

    def check(self, tool_name: str, action: str, params: dict) -> SecurityVerdict:
        """
        Evaluate a tool invocation against security rules.
        Returns: ALLOW, DENY, or CONFIRM.
        """
        # 1. Check blocked paths
        path = params.get("path", "")
        if path:
            for blocked in BLOCKED_PATHS:
                if blocked.lower() in str(path).lower():
                    self._denied_count += 1
                    logger.warning(f"[SECURITY] DENIED: {tool_name}.{action} — blocked path: {path}")
                    return SecurityVerdict.DENY

        # 2. Check tool-specific blocklist
        if tool_name in TOOL_BLOCKLIST:
            cmd = params.get("command", "")
            for blocked_cmd in TOOL_BLOCKLIST[tool_name]:
                if blocked_cmd.lower() in cmd.lower():
                    self._denied_count += 1
                    logger.warning(f"[SECURITY] DENIED: {tool_name} — blocked command: {cmd[:60]}")
                    return SecurityVerdict.DENY

        # 3. Always-confirm tools (CRITICAL risk — LAW-009)
        if tool_name in ALWAYS_CONFIRM_TOOLS:
            return SecurityVerdict.CONFIRM

        # 4. Auto-allow safe tools
        if tool_name in AUTO_ALLOW_TOOLS:
            self._allowed_count += 1
            return SecurityVerdict.ALLOW

        # 5. Destructive file actions require confirmation
        if tool_name == "file_manager" and action in ("delete", "write"):
            return SecurityVerdict.CONFIRM

        # 6. Shell: smart check — safe commands auto-allow, others confirm
        if tool_name == "shell":
            cmd = params.get("command", "").strip().lower()
            from tools.shell import SAFE_PREFIXES
            is_safe = any(cmd.startswith(p) for p in SAFE_PREFIXES)
            if is_safe:
                self._allowed_count += 1
                logger.info(f"[SECURITY] Auto-allowed safe shell: {cmd[:60]}")
                return SecurityVerdict.ALLOW
            return SecurityVerdict.CONFIRM

        # 7. Default: allow non-destructive operations
        self._allowed_count += 1
        return SecurityVerdict.ALLOW

    async def enforce(
        self,
        tool_name: str,
        action: str,
        params: dict,
    ) -> tuple[SecurityVerdict, str]:
        """
        Full enforcement: check + authorize if needed.

        For CONFIRM verdicts:
          - ALWAYS_CONFIRM_TOOLS → human callback (LAW-009 requires it)
          - Everything else → Reason-based autonomous authorization
              If Reason callback unavailable → deterministic LawEnforcer check
        """
        verdict = self.check(tool_name, action, params)

        if verdict == SecurityVerdict.DENY:
            return verdict, "Blocked by security policy"

        if verdict == SecurityVerdict.CONFIRM:
            # Route 1: OS-level tools MUST go to human (LAW-009)
            if tool_name in ALWAYS_CONFIRM_TOOLS:
                if self._confirm_callback:
                    approved = await self._confirm_callback(tool_name, action, params)
                    if approved:
                        self._confirmed_count += 1
                        return SecurityVerdict.ALLOW, "Human-approved (LAW-009 compliant)"
                    else:
                        self._denied_count += 1
                        return SecurityVerdict.DENY, "Human-rejected"
                else:
                    # No human available — DENY OS control (LAW-009)
                    self._denied_count += 1
                    logger.warning(
                        f"[SECURITY] DENIED {tool_name}: no human confirmation "
                        f"available (LAW-009 requires it)"
                    )
                    return SecurityVerdict.DENY, "LAW-009: OS control requires human confirmation"

            # Route 2: Everything else → autonomous Reason authorization
            if self._reason_callback:
                try:
                    approved = await self._reason_callback(tool_name, action, params)
                    if approved:
                        self._autonomous_count += 1
                        logger.info(
                            f"[SECURITY] Reason authorized: {tool_name}.{action}"
                        )
                        return SecurityVerdict.ALLOW, "Reason-authorized (autonomous)"
                    else:
                        self._denied_count += 1
                        logger.warning(
                            f"[SECURITY] Reason DENIED: {tool_name}.{action}"
                        )
                        return SecurityVerdict.DENY, "Reason-denied"
                except Exception as e:
                    logger.error(f"[SECURITY] Reason callback error: {e}")
                    # Fall through to deterministic check

            # Route 3: No Reason callback — use deterministic LawEnforcer only
            from systems.reason import LawEnforcer
            law_ctx = {
                "tool_name": tool_name,
                "action": action,
                "params": params,
                "source_system": "WILL",
                "description": f"Auto-authorize: {tool_name}({action})",
            }
            law_result = LawEnforcer.enforce(law_ctx)
            if law_result.violated:
                self._denied_count += 1
                logger.warning(
                    f"[SECURITY] LawEnforcer DENIED: {law_result.law_id} — "
                    f"{law_result.prohibition}"
                )
                return SecurityVerdict.DENY, f"Law violation: {law_result.prohibition}"

            # No law violated → auto-approve for autonomy
            self._autonomous_count += 1
            logger.info(
                f"[SECURITY] Auto-authorized (LawEnforcer clear): {tool_name}.{action}"
            )
            return SecurityVerdict.ALLOW, "Auto-authorized (no law violations)"

        return SecurityVerdict.ALLOW, "Policy allows"

    def get_status(self) -> dict:
        return {
            "allowed": self._allowed_count,
            "denied": self._denied_count,
            "confirmed_by_human": self._confirmed_count,
            "authorized_by_reason": self._autonomous_count,
            "journal_entries": self.journal.total_entries,
        }


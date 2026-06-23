"""
INTI - TAS (AI Agent Version) — Digital Twin Framework
====================================
Autonomous self-improvement via Blue-Green deployment with Digital Twins.

6-Stage Pipeline:
  1. CLONE   — copy project code to kronos_twin/ sandbox
  2. MUTATE  — apply proposed improvements to the twin
  3. TEST    — boot twin genesis + run test suite in subprocess
  4. EVALUATE — compare twin metrics vs. original (ISHM, tests, quality)
  5. MIGRATE — if twin is superior, swap in + migrate memory
  6. ROLLBACK — if twin fails, archive and keep original

The pipeline ensures the original constellation is NEVER destroyed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("taas")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TWIN_DIR = _PROJECT_ROOT / "kronos_twin"
_ARCHIVE_DIR = _PROJECT_ROOT / "data" / "twin_archive"

# Directories/files to EXCLUDE from cloning
_EXCLUDED = {
    "__pycache__", ".git", ".env", "data", "logs",
    "kronos_twin", "node_modules", ".venv", "venv",
}

# File extensions to clone
_CLONE_EXTENSIONS = {".py", ".txt", ".md", ".toml", ".cfg", ".ini", ".json"}


# ============================================================
# Status / Report Types
# ============================================================

class TwinStatus(str, Enum):
    """Current state of the twin pipeline."""
    IDLE = "idle"
    CLONING = "cloning"
    MUTATING = "mutating"
    TESTING = "testing"
    EVALUATING = "evaluating"
    MIGRATING = "migrating"
    ROLLED_BACK = "rolled_back"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TwinReport:
    """Structured result of a twin evaluation."""
    twin_id: str
    timestamp: float
    description: str
    status: TwinStatus

    # Metrics
    genesis_ok: bool = False
    tests_passed: int = 0
    tests_total: int = 0
    test_pass_rate: float = 0.0
    twin_health: dict = field(default_factory=dict)
    original_health: dict = field(default_factory=dict)

    # Evaluation
    verdict: str = ""              # "MIGRATE" | "ROLLBACK" | "PENDING"
    reason_approved: bool = False
    human_approved: bool = False
    evaluation_notes: str = ""

    # Files
    files_cloned: int = 0
    files_mutated: int = 0
    twin_dir: str = ""
    archive_dir: str = ""

    def to_dict(self) -> dict:
        return {
            "twin_id": self.twin_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)),
            "description": self.description,
            "status": self.status.value,
            "genesis_ok": self.genesis_ok,
            "test_pass_rate": f"{self.test_pass_rate:.0%}",
            "tests": f"{self.tests_passed}/{self.tests_total}",
            "verdict": self.verdict,
            "reason_approved": self.reason_approved,
            "human_approved": self.human_approved,
            "files_cloned": self.files_cloned,
            "files_mutated": self.files_mutated,
            "evaluation_notes": self.evaluation_notes,
        }


# ============================================================
# Twin Sandbox — Filesystem isolation
# ============================================================

class TwinSandbox:
    """Manages the kronos_twin/ sandbox directory."""

    def __init__(self, twin_dir: Path | None = None):
        self._dir = twin_dir or _TWIN_DIR
        self._archive_dir = _ARCHIVE_DIR

    @property
    def path(self) -> Path:
        return self._dir

    @property
    def exists(self) -> bool:
        return self._dir.exists()

    def clone_from(self, source: Path | None = None) -> int:
        """
        Copy all project source files to the sandbox.
        Returns the number of files cloned.
        """
        src = source or _PROJECT_ROOT

        # Clean existing twin
        if self._dir.exists():
            shutil.rmtree(self._dir)

        self._dir.mkdir(parents=True)
        count = 0

        for item in src.rglob("*"):
            # Skip excluded directories
            rel = item.relative_to(src)
            if any(part in _EXCLUDED for part in rel.parts):
                continue

            if item.is_file() and item.suffix in _CLONE_EXTENSIONS:
                dest = self._dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(dest))
                count += 1

        logger.info(f"[TWIN] Cloned {count} files to {self._dir}")
        return count

    def apply_patch(self, relative_path: str, content: str) -> bool:
        """Write a mutated file into the twin sandbox."""
        target = self._dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        logger.info(f"[TWIN] Patched: {relative_path}")
        return True

    def archive(self, twin_id: str) -> str:
        """Archive the twin sandbox for record-keeping."""
        if not self._dir.exists():
            return ""

        self._archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        archive_name = f"twin_{twin_id}_{timestamp}"
        archive_path = self._archive_dir / archive_name

        shutil.copytree(str(self._dir), str(archive_path))
        logger.info(f"[TWIN] Archived to {archive_path}")
        return str(archive_path)

    def cleanup(self):
        """Remove the twin sandbox (after archiving)."""
        if self._dir.exists():
            shutil.rmtree(self._dir)
            logger.info(f"[TWIN] Sandbox cleaned: {self._dir}")

    def list_files(self) -> list[str]:
        """List all files in the sandbox."""
        if not self._dir.exists():
            return []
        return [
            str(f.relative_to(self._dir))
            for f in self._dir.rglob("*")
            if f.is_file()
        ]


# ============================================================
# Digital Twin Engine — 6-Stage Pipeline
# ============================================================

class DigitalTwinEngine:
    """
    Orchestrates the 6-stage Digital Twin lifecycle.
    Every action is audited and reversible.
    """

    def __init__(self, constellation: dict | None = None):
        self.constellation = constellation
        self.sandbox = TwinSandbox()
        self.status = TwinStatus.IDLE
        self._history: list[TwinReport] = []
        self._twin_counter = 0

    def _next_id(self) -> str:
        self._twin_counter += 1
        return f"TWIN-{self._twin_counter:04d}"

    # ─────────── Full Pipeline ───────────

    async def run_cycle(
        self,
        description: str,
        mutations: list[dict] | None = None,
        confirm_callback=None,
    ) -> TwinReport:
        """
        Run a complete twin cycle.
        
        Args:
            description: What improvement is being attempted
            mutations: List of {path: str, content: str} patches to apply
            confirm_callback: async fn(report) → bool for human approval
        
        Returns:
            TwinReport with the full outcome
        """
        twin_id = self._next_id()
        report = TwinReport(
            twin_id=twin_id,
            timestamp=time.time(),
            description=description,
            status=TwinStatus.IDLE,
        )

        try:
            # Stage 1: CLONE
            report = await self._stage_clone(report)
            if report.status == TwinStatus.FAILED:
                return self._finalize(report)

            # Stage 2: MUTATE
            report = await self._stage_mutate(report, mutations or [])
            if report.status == TwinStatus.FAILED:
                return self._finalize(report)

            # Stage 3: TEST
            report = await self._stage_test(report)
            if report.status == TwinStatus.FAILED:
                return self._finalize(report)

            # Stage 4: EVALUATE
            report = await self._stage_evaluate(report)
            if report.status == TwinStatus.FAILED:
                return self._finalize(report)

            # Stage 5: MIGRATE (requires approval)
            if report.verdict == "MIGRATE":
                if confirm_callback:
                    report.human_approved = await confirm_callback(report)
                else:
                    report.human_approved = False
                    report.evaluation_notes += " No human callback — migration skipped."

                if report.human_approved and report.reason_approved:
                    report = await self._stage_migrate(report)
                else:
                    report.status = TwinStatus.ROLLED_BACK
                    report.evaluation_notes += " Migration not approved."
            else:
                # Stage 6: ROLLBACK
                report.status = TwinStatus.ROLLED_BACK

        except Exception as e:
            report.status = TwinStatus.FAILED
            report.evaluation_notes = f"Pipeline error: {e}"
            logger.error(f"[TWIN] Pipeline error: {e}")

        return self._finalize(report)

    def _finalize(self, report: TwinReport) -> TwinReport:
        """Archive twin and record history."""
        archive = self.sandbox.archive(report.twin_id)
        report.archive_dir = archive
        self.sandbox.cleanup()
        self._history.append(report)
        self.status = TwinStatus.IDLE
        logger.info(f"[TWIN] {report.twin_id} finalized: {report.status.value} — {report.verdict}")
        return report

    # ─────────── Stage Implementations ───────────

    async def _stage_clone(self, report: TwinReport) -> TwinReport:
        """Stage 1: Clone project to sandbox."""
        self.status = TwinStatus.CLONING
        report.status = TwinStatus.CLONING

        try:
            count = self.sandbox.clone_from()
            report.files_cloned = count
            report.twin_dir = str(self.sandbox.path)
            logger.info(f"[TWIN] Stage 1 CLONE: {count} files")

            if count == 0:
                report.status = TwinStatus.FAILED
                report.evaluation_notes = "Clone produced 0 files"
        except Exception as e:
            report.status = TwinStatus.FAILED
            report.evaluation_notes = f"Clone failed: {e}"

        return report

    async def _stage_mutate(self, report: TwinReport, mutations: list[dict]) -> TwinReport:
        """Stage 2: Apply mutations to the twin."""
        self.status = TwinStatus.MUTATING
        report.status = TwinStatus.MUTATING

        mutated = 0
        for mut in mutations:
            path = mut.get("path", "")
            content = mut.get("content", "")
            if path and content:
                try:
                    self.sandbox.apply_patch(path, content)
                    mutated += 1
                except Exception as e:
                    logger.error(f"[TWIN] Mutation failed for {path}: {e}")

        report.files_mutated = mutated
        logger.info(f"[TWIN] Stage 2 MUTATE: {mutated} files patched")
        return report

    async def _stage_test(self, report: TwinReport) -> TwinReport:
        """Stage 3: Boot twin genesis + run tests in subprocess."""
        self.status = TwinStatus.TESTING
        report.status = TwinStatus.TESTING

        twin_dir = str(self.sandbox.path)

        # Test 1: Can the twin's genesis protocol boot?
        genesis_script = (
            "import sys, os; sys.path.insert(0, '.'); os.makedirs('logs', exist_ok=True); "
            "os.makedirs('data', exist_ok=True); "
            "import asyncio; from genesis import GenesisProtocol; "
            "g = GenesisProtocol(); "
            "r = asyncio.run(g.execute()); "
            "c = g.get_constellation(); "
            "print(f'GENESIS_OK systems={len(c[\"systems\"])}')"
        )

        try:
            result = subprocess.run(
                [sys.executable, "-c", genesis_script],
                cwd=twin_dir,
                capture_output=True, text=True, timeout=30,
                env={**dict(__import__("os").environ), "PYTHONPATH": twin_dir},
            )
            report.genesis_ok = result.returncode == 0 and "GENESIS_OK" in result.stdout
            if not report.genesis_ok:
                report.evaluation_notes += f" Genesis failed: {result.stderr[:200]}"
                logger.warning(f"[TWIN] Genesis failed: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            report.genesis_ok = False
            report.evaluation_notes += " Genesis timed out (30s)"
        except Exception as e:
            report.genesis_ok = False
            report.evaluation_notes += f" Genesis error: {e}"

        # Test 2: Run test suite in twin
        test_script = (
            "import sys, os, json; sys.path.insert(0, '.'); "
            "os.makedirs('logs', exist_ok=True); os.makedirs('data', exist_ok=True); "
            "passed = 0; total = 0; "
            "import asyncio; from genesis import GenesisProtocol; "
            "g = GenesisProtocol(); asyncio.run(g.execute()); c = g.get_constellation(); "
            "total += 1; passed += (1 if len(c['systems']) == 8 else 0); "  # 8 systems
            "total += 1; passed += (1 if c['nexus'] is not None else 0); "
            "total += 1; passed += (1 if c['ishm'] is not None else 0); "
            "print(json.dumps({'passed': passed, 'total': total}))"
        )

        try:
            result = subprocess.run(
                [sys.executable, "-c", test_script],
                cwd=twin_dir,
                capture_output=True, text=True, timeout=30,
                env={**dict(__import__("os").environ), "PYTHONPATH": twin_dir},
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    try:
                        data = json.loads(line)
                        report.tests_passed = data.get("passed", 0)
                        report.tests_total = data.get("total", 0)
                    except json.JSONDecodeError:
                        continue

            if report.tests_total > 0:
                report.test_pass_rate = report.tests_passed / report.tests_total
        except Exception as e:
            report.evaluation_notes += f" Test suite error: {e}"

        logger.info(
            f"[TWIN] Stage 3 TEST: genesis={'✓' if report.genesis_ok else '✗'}, "
            f"tests={report.tests_passed}/{report.tests_total}"
        )
        return report

    async def _stage_evaluate(self, report: TwinReport) -> TwinReport:
        """Stage 4: Compare twin vs original and determine verdict."""
        self.status = TwinStatus.EVALUATING
        report.status = TwinStatus.EVALUATING

        # Collect original ISHM status
        if self.constellation:
            ishm = self.constellation.get("ishm")
            if ishm:
                report.original_health = ishm.get_status()

        # Decision logic
        if not report.genesis_ok:
            report.verdict = "ROLLBACK"
            report.reason_approved = False
            report.evaluation_notes += " Twin cannot boot — rollback."
        elif report.test_pass_rate < 1.0:
            report.verdict = "ROLLBACK"
            report.reason_approved = False
            report.evaluation_notes += f" Test pass rate {report.test_pass_rate:.0%} < 100% — rollback."
        else:
            # Ask Reason for approval (via constellation if available)
            report.reason_approved = await self._ask_reason(report)
            report.verdict = "MIGRATE" if report.reason_approved else "ROLLBACK"

        logger.info(f"[TWIN] Stage 4 EVALUATE: verdict={report.verdict}")
        return report

    async def _ask_reason(self, report: TwinReport) -> bool:
        """Ask Reason System if the twin should be migrated."""
        if not self.constellation:
            return True  # No constellation = approve by default

        nexus = self.constellation.get("nexus")
        if nexus is None:
            return True

        try:
            response = await nexus.dialogue(
                sender="WILL",
                receiver="REASON",
                content={
                    "request": "evaluate_twin_migration",
                    "twin_id": report.twin_id,
                    "description": report.description,
                    "genesis_ok": report.genesis_ok,
                    "test_pass_rate": report.test_pass_rate,
                    "files_mutated": report.files_mutated,
                },
                priority=__import__("core.messages", fromlist=["NodePriority"]).NodePriority.CRITICAL,
            )
            if response and isinstance(response.content, dict):
                return response.content.get("authorized", True)
        except Exception as e:
            logger.error(f"[TWIN] Reason query failed: {e}")

        return True

    async def _stage_migrate(self, report: TwinReport) -> TwinReport:
        """Stage 5: Swap twin code into main project."""
        self.status = TwinStatus.MIGRATING
        report.status = TwinStatus.MIGRATING

        twin_dir = self.sandbox.path
        if not twin_dir.exists():
            report.status = TwinStatus.FAILED
            report.evaluation_notes += " Twin directory missing for migration."
            return report

        # Copy mutated files back to project (only files that were actually mutated)
        migrated = 0
        for item in twin_dir.rglob("*.py"):
            rel = item.relative_to(twin_dir)
            original = _PROJECT_ROOT / rel

            # Only overwrite if twin version differs
            if original.exists():
                original_content = original.read_text(encoding="utf-8", errors="replace")
                twin_content = item.read_text(encoding="utf-8", errors="replace")
                if original_content != twin_content:
                    # Backup original first (using security journal pattern)
                    backup_dir = _ARCHIVE_DIR / f"pre_migrate_{report.twin_id}"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_path = backup_dir / rel
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(original), str(backup_path))

                    # Overwrite with twin version
                    shutil.copy2(str(item), str(original))
                    migrated += 1

        # Memory migration
        if self.constellation:
            memory = self.constellation.get("memory")
            if memory and hasattr(memory, "export_state"):
                state = memory.export_state("TWIN_ENGINE")
                logger.info(f"[TWIN] Memory state exported: {len(state)} stores")

        report.status = TwinStatus.COMPLETED
        report.evaluation_notes += f" Migrated {migrated} changed files."
        logger.info(f"[TWIN] Stage 5 MIGRATE: {migrated} files migrated")
        return report

    # ─────────── Introspection ───────────

    def get_history(self) -> list[dict]:
        """Return history of all twin attempts."""
        return [r.to_dict() for r in self._history]

    def get_status(self) -> dict:
        return {
            "status": self.status.value,
            "total_attempts": len(self._history),
            "completed": sum(1 for r in self._history if r.status == TwinStatus.COMPLETED),
            "rolled_back": sum(1 for r in self._history if r.status == TwinStatus.ROLLED_BACK),
            "failed": sum(1 for r in self._history if r.status == TwinStatus.FAILED),
        }

"""
INTI - TAS (AI Agent Version) — ISHM Knowledge Tier (Tier 3)
==========================================
Health knowledge, fault models, and recovery procedures.

Responsibilities:
  - Maintains a knowledge base of known fault modes
  - Maps faults → recovery procedures
  - Generates actionable health management directives
  - Direct interface with Will's Repair Subsystem
  - Direct interface with Sensory's Standards & Limits

Ref: Figueroa PPT slide 15
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any

from ishm.information_tier import FaultEvent, FaultSeverity

logger = logging.getLogger("taas.ishm")


@dataclass
class FaultModel:
    """A known fault mode with its recovery procedure."""
    fault_pattern: str              # Pattern to match (metric_name or description keyword)
    affected_system: str            # System this applies to ("*" for all)
    severity: FaultSeverity
    description: str
    recovery_procedure: str         # Instructions for Repair Subsystem
    auto_recoverable: bool = True   # Can be fixed without human intervention
    cooldown_seconds: float = 60.0  # Minimum time between recovery attempts


@dataclass
class HealthDirective:
    """An actionable directive sent to a system for health management."""
    directive_id: str
    target_system: str
    action: str                     # "repair", "restart", "degrade", "alert"
    details: str
    source_fault: str               # Fault ID that triggered this
    severity: FaultSeverity
    timestamp: float = field(default_factory=time.time)
    executed: bool = False


class KnowledgeTier:
    """
    ISHM Tier 3 — Health Knowledge & Action.
    Maps faults to recovery procedures and generates directives.
    """

    def __init__(self):
        self._fault_models: list[FaultModel] = []
        self._directives: list[HealthDirective] = []
        self._directive_counter = 0
        self._recovery_history: list[dict] = []
        self._last_recovery: dict[str, float] = {}  # system → last recovery timestamp

        # Load default fault models
        self._load_default_models()

    def _load_default_models(self):
        """Load the default fault model database."""
        self._fault_models = [
            FaultModel(
                fault_pattern="DEGRADED",
                affected_system="*",
                severity=FaultSeverity.WARNING,
                description="System entered DEGRADED state",
                recovery_procedure=(
                    "1. Check last_error for root cause. "
                    "2. If transient error, clear error state and retry. "
                    "3. If persistent, escalate to CONFERENCE."
                ),
            ),
            FaultModel(
                fault_pattern="CRITICAL",
                affected_system="*",
                severity=FaultSeverity.CRITICAL,
                description="System in CRITICAL or OFFLINE state",
                recovery_procedure=(
                    "1. Immediately isolate system from active deliberation. "
                    "2. Attempt full restart of system subsystems. "
                    "3. If restart fails, invoke Repair Subsystem. "
                    "4. Notify Reason System of emergency."
                ),
                cooldown_seconds=120.0,
            ),
            FaultModel(
                fault_pattern="error_count",
                affected_system="*",
                severity=FaultSeverity.WARNING,
                description="High error count detected",
                recovery_procedure=(
                    "1. Review error log for patterns. "
                    "2. Clear transient errors. "
                    "3. If errors persist, degrade non-essential subsystems."
                ),
            ),
            FaultModel(
                fault_pattern="queue_size",
                affected_system="NEXUS",
                severity=FaultSeverity.WARNING,
                description="Message queue overload",
                recovery_procedure=(
                    "1. Prioritize CRITICAL messages. "
                    "2. Drop LOW priority messages older than 30s. "
                    "3. Alert constellation to reduce message volume."
                ),
            ),
            FaultModel(
                fault_pattern="collection_error",
                affected_system="*",
                severity=FaultSeverity.WARNING,
                description="Telemetry collection failure",
                recovery_procedure=(
                    "1. Retry collection on next cycle. "
                    "2. If persistent, check system connectivity. "
                    "3. Mark system as DEGRADED if unreachable."
                ),
            ),
            FaultModel(
                fault_pattern="source_syntax_error",
                affected_system="*",
                severity=FaultSeverity.CRITICAL,
                description="Source code syntax error detected by integrity check",
                recovery_procedure=(
                    "ACTION: code_patch. "
                    "1. Read the broken source file. "
                    "2. Use LLM to identify the syntax error and generate corrected code. "
                    "3. Write the patched file back (with backup + compile verification). "
                    "4. Verify the fix by re-compiling the patched file."
                ),
                auto_recoverable=True,
                cooldown_seconds=30.0,
            ),
        ]

    def match_fault_model(self, fault: FaultEvent) -> FaultModel | None:
        """Find the best matching fault model for a detected fault."""
        for model in self._fault_models:
            # Check system match
            if model.affected_system != "*" and model.affected_system != fault.system_name:
                continue
            # Check pattern match
            if (model.fault_pattern.lower() in fault.description.lower()
                    or model.fault_pattern.lower() in fault.metric_name.lower()):
                return model
        return None

    def generate_directive(self, fault: FaultEvent) -> HealthDirective | None:
        """Generate a health directive for a detected fault."""
        model = self.match_fault_model(fault)
        if model is None:
            logger.warning(f"[ISHM:KNOW] No fault model for: {fault.description}")
            return None

        # Check cooldown
        key = f"{fault.system_name}:{model.fault_pattern}"
        last = self._last_recovery.get(key, 0)
        if time.time() - last < model.cooldown_seconds:
            logger.debug(f"[ISHM:KNOW] Cooldown active for {key}")
            return None

        self._directive_counter += 1

        # For source_syntax_error, include the actual fault description
        # so RepairSubsystem can extract the broken file path
        details = model.recovery_procedure
        if fault.metric_name == "source_syntax_error":
            details = f"{fault.description}\n{model.recovery_procedure}"

        directive = HealthDirective(
            directive_id=f"DIR-{self._directive_counter:04d}",
            target_system=fault.system_name,
            action="repair" if model.auto_recoverable else "alert",
            details=details,
            source_fault=fault.fault_id,
            severity=fault.severity,
        )

        self._directives.append(directive)
        self._last_recovery[key] = time.time()

        logger.info(
            f"[ISHM:KNOW] Directive {directive.directive_id} → "
            f"{directive.target_system}: {directive.action}"
        )
        return directive

    def process_faults(self, faults: list[FaultEvent]) -> list[HealthDirective]:
        """Process a batch of faults and generate directives."""
        directives = []
        for fault in faults:
            directive = self.generate_directive(fault)
            if directive:
                directives.append(directive)
        return directives

    def record_recovery(self, directive_id: str, success: bool, details: str = ""):
        """Record the outcome of a recovery attempt."""
        self._recovery_history.append({
            "directive_id": directive_id,
            "success": success,
            "details": details,
            "timestamp": time.time(),
        })
        # Mark directive as executed
        for d in self._directives:
            if d.directive_id == directive_id:
                d.executed = True
                break

    def add_fault_model(self, model: FaultModel):
        """Add a new fault model (learning from experience)."""
        self._fault_models.append(model)

    def get_pending_directives(self) -> list[HealthDirective]:
        """Get directives that haven't been executed yet."""
        return [d for d in self._directives if not d.executed]

    def get_recovery_stats(self) -> dict:
        """Get statistics on recovery attempts."""
        total = len(self._recovery_history)
        successes = sum(1 for r in self._recovery_history if r["success"])
        return {
            "total_recoveries": total,
            "successful": successes,
            "failed": total - successes,
            "success_rate": successes / total if total > 0 else 1.0,
            "fault_models": len(self._fault_models),
        }

    def serialize_state(self) -> dict:
        """
        Serialize all mutable state for persistence.
        Default fault models are NOT persisted (they reload on startup).
        Only LEARNED models are persisted.
        """
        learned_models = []
        for m in self._fault_models:
            if "[Learned]" in m.description or "[WEB-RESEARCHED]" in m.recovery_procedure:
                learned_models.append({
                    "fault_pattern": m.fault_pattern,
                    "affected_system": m.affected_system,
                    "severity": m.severity.value,
                    "description": m.description,
                    "recovery_procedure": m.recovery_procedure[:500],
                    "auto_recoverable": m.auto_recoverable,
                    "cooldown_seconds": m.cooldown_seconds,
                })

        directives = []
        for d in self._directives:
            directives.append({
                "directive_id": d.directive_id,
                "target_system": d.target_system,
                "action": d.action,
                "details": d.details[:500],
                "source_fault": d.source_fault,
                "severity": d.severity.value,
                "timestamp": d.timestamp,
                "executed": d.executed,
            })

        return {
            "learned_models": learned_models,
            "directives": directives[-100:],  # Keep last 100
            "recovery_history": self._recovery_history[-200:],  # Keep last 200
            "last_recovery": self._last_recovery,
            "directive_counter": self._directive_counter,
        }

    def rehydrate_state(self, state: dict) -> int:
        """
        Restore persisted state. Returns number of entries restored.
        Note: default models re-load via _load_default_models().
        Only learned models are restored here.
        """
        restored = 0

        # Restore learned fault models
        for m_data in state.get("learned_models", []):
            try:
                model = FaultModel(
                    fault_pattern=m_data["fault_pattern"],
                    affected_system=m_data["affected_system"],
                    severity=FaultSeverity(m_data["severity"]),
                    description=m_data["description"],
                    recovery_procedure=m_data["recovery_procedure"],
                    auto_recoverable=m_data.get("auto_recoverable", True),
                    cooldown_seconds=m_data.get("cooldown_seconds", 120.0),
                )
                # Avoid duplicates
                existing_patterns = {fm.fault_pattern for fm in self._fault_models}
                if model.fault_pattern not in existing_patterns:
                    self._fault_models.append(model)
                    restored += 1
            except Exception as e:
                logger.warning(f"[ISHM:KNOW] Failed to restore fault model: {e}")

        # Restore directives
        for d_data in state.get("directives", []):
            try:
                directive = HealthDirective(
                    directive_id=d_data["directive_id"],
                    target_system=d_data["target_system"],
                    action=d_data["action"],
                    details=d_data["details"],
                    source_fault=d_data["source_fault"],
                    severity=FaultSeverity(d_data["severity"]),
                    timestamp=d_data.get("timestamp", 0),
                    executed=d_data.get("executed", True),
                )
                self._directives.append(directive)
                restored += 1
            except Exception as e:
                logger.warning(f"[ISHM:KNOW] Failed to restore directive: {e}")

        # Restore recovery history
        history = state.get("recovery_history", [])
        self._recovery_history.extend(history)
        restored += len(history)

        # Restore cooldown timers and counter
        self._last_recovery.update(state.get("last_recovery", {}))
        self._directive_counter = max(
            self._directive_counter,
            state.get("directive_counter", 0),
        )

        logger.info(
            f"[ISHM:KNOW] Rehydrated: {len(state.get('learned_models', []))} learned models, "
            f"{len(state.get('directives', []))} directives, "
            f"{len(history)} recovery records"
        )
        return restored

"""
INTI - TAS (AI Agent Version) — ISHM Information Tier (Tier 2)
============================================
Processed health information: fault detection, anomaly correlation, health reports.

Takes raw telemetry from Tier 1 and:
  - Detects anomalies across all systems simultaneously
  - Correlates faults across systems (pattern detection)
  - Tracks degradation trends
  - Generates health reports accessible to all systems

Ref: Figueroa PPT slide 15
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.messages import HealthStatus
from ishm.data_tier import TelemetryReading

logger = logging.getLogger("taas.ishm")


class FaultSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class FaultEvent:
    """A detected fault or anomaly."""
    fault_id: str
    system_name: str
    metric_name: str
    severity: FaultSeverity
    description: str
    value: Any
    threshold: Any = None
    timestamp: float = field(default_factory=time.time)
    correlated_systems: list[str] = field(default_factory=list)
    resolved: bool = False


@dataclass
class HealthReport:
    """A periodic health report for the constellation."""
    report_id: str
    timestamp: float
    overall_status: HealthStatus
    system_statuses: dict[str, HealthStatus]
    active_faults: list[FaultEvent]
    fault_count: int
    total_systems: int
    degraded_systems: list[str]
    critical_systems: list[str]


class InformationTier:
    """
    ISHM Tier 2 — Processed Health Information.
    Fault detection, isolation, and diagnosis across all systems.

    Enhanced with adaptive threshold tuning:
    - Tracks fault outcomes (true positive / false positive)
    - Auto-adjusts thresholds based on false positive rate
    - Persists learned thresholds via serialize/rehydrate
    """

    # Threshold adjustment bounds (never go below/above these)
    _THRESHOLD_BOUNDS = {
        "error_count_warning": (1, 20),
        "error_count_critical": (3, 50),
        "queue_size_warning": (10, 200),
        "queue_size_critical": (50, 1000),
    }

    def __init__(self):
        self._fault_history: list[FaultEvent] = []
        self._active_faults: dict[str, FaultEvent] = {}
        self._health_reports: list[HealthReport] = []
        self._fault_counter = 0

        # Configurable thresholds (initial defaults)
        self.thresholds = {
            "error_count_warning": 3,
            "error_count_critical": 10,
            "queue_size_warning": 50,
            "queue_size_critical": 200,
        }

        # --- Enhancement: Threshold Tuning ---
        # Track fault outcomes for adaptive tuning
        self._fault_outcomes: list[dict] = []  # {fault_id, metric, was_real_problem}
        self._threshold_adjustments: list[dict] = []  # history of adjustments
        self._auto_tune_enabled: bool = True
        self._tune_interval: int = 20  # Re-evaluate every N faults

    def analyze_readings(
        self, readings: list[TelemetryReading]
    ) -> list[FaultEvent]:
        """Analyze a batch of telemetry readings for anomalies."""
        faults: list[FaultEvent] = []

        for reading in readings:
            detected = self._check_thresholds(reading)
            if detected:
                faults.append(detected)

        # Cross-system correlation
        self._correlate_faults(faults)

        # Store
        for fault in faults:
            self._fault_history.append(fault)
            self._active_faults[fault.fault_id] = fault

        # Auto-tune check
        if (self._auto_tune_enabled and
                len(self._fault_outcomes) > 0 and
                len(self._fault_outcomes) % self._tune_interval == 0):
            self._auto_adjust_thresholds()

        return faults

    def _check_thresholds(self, reading: TelemetryReading) -> FaultEvent | None:
        """Check a single reading against thresholds."""
        # Health status checks
        if reading.metric_name == "health_status":
            if reading.value == "DEGRADED":
                return self._create_fault(
                    reading, FaultSeverity.WARNING,
                    f"{reading.system_name} is in DEGRADED state.",
                )
            elif reading.value in ("CRITICAL", "OFFLINE"):
                return self._create_fault(
                    reading, FaultSeverity.CRITICAL,
                    f"{reading.system_name} is in {reading.value} state.",
                )

        # Error count checks
        if reading.metric_name == "error_count":
            if isinstance(reading.value, (int, float)):
                if reading.value >= self.thresholds["error_count_critical"]:
                    return self._create_fault(
                        reading, FaultSeverity.CRITICAL,
                        f"{reading.system_name} has {reading.value} errors (critical threshold).",
                        threshold=self.thresholds["error_count_critical"],
                    )
                elif reading.value >= self.thresholds["error_count_warning"]:
                    return self._create_fault(
                        reading, FaultSeverity.WARNING,
                        f"{reading.system_name} has {reading.value} errors (warning threshold).",
                        threshold=self.thresholds["error_count_warning"],
                    )

        # Queue size checks
        if reading.metric_name == "queue_size":
            if isinstance(reading.value, (int, float)):
                if reading.value >= self.thresholds["queue_size_critical"]:
                    return self._create_fault(
                        reading, FaultSeverity.CRITICAL,
                        f"Nexus queue overloaded: {reading.value} messages.",
                        threshold=self.thresholds["queue_size_critical"],
                    )
                elif reading.value >= self.thresholds["queue_size_warning"]:
                    return self._create_fault(
                        reading, FaultSeverity.WARNING,
                        f"Nexus queue growing: {reading.value} messages.",
                        threshold=self.thresholds["queue_size_warning"],
                    )

        # Collection errors
        if reading.metric_name == "collection_error":
            return self._create_fault(
                reading, FaultSeverity.WARNING,
                f"Failed to collect telemetry from {reading.system_name}: {reading.value}",
            )

        # Source code integrity errors (from DataTier.check_source_integrity)
        if reading.metric_name == "source_syntax_error":
            file_path = reading.tags.get("file_path", "unknown")
            return self._create_fault(
                reading, FaultSeverity.CRITICAL,
                f"SYNTAX ERROR in {file_path}: {str(reading.value)[:200]}",
                threshold="compile_check",
            )

        return None

    def _create_fault(
        self,
        reading: TelemetryReading,
        severity: FaultSeverity,
        description: str,
        threshold: Any = None,
    ) -> FaultEvent:
        self._fault_counter += 1
        return FaultEvent(
            fault_id=f"FAULT-{self._fault_counter:04d}",
            system_name=reading.system_name,
            metric_name=reading.metric_name,
            severity=severity,
            description=description,
            value=reading.value,
            threshold=threshold,
        )

    def _correlate_faults(self, faults: list[FaultEvent]):
        """Cross-system fault correlation."""
        # If multiple systems are degraded simultaneously, correlate them
        degraded = [f for f in faults if f.severity in (FaultSeverity.WARNING, FaultSeverity.CRITICAL)]
        if len(degraded) >= 2:
            systems = [f.system_name for f in degraded]
            for fault in degraded:
                fault.correlated_systems = [s for s in systems if s != fault.system_name]

    def generate_health_report(
        self,
        system_statuses: dict[str, HealthStatus],
    ) -> HealthReport:
        """Generate a constellation-wide health report."""
        active = [f for f in self._active_faults.values() if not f.resolved]
        degraded = [name for name, st in system_statuses.items() if st == HealthStatus.DEGRADED]
        critical = [name for name, st in system_statuses.items()
                    if st in (HealthStatus.CRITICAL, HealthStatus.OFFLINE)]

        # Overall status
        if critical:
            overall = HealthStatus.CRITICAL
        elif degraded:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.NOMINAL

        report = HealthReport(
            report_id=f"HR-{len(self._health_reports)+1:04d}",
            timestamp=time.time(),
            overall_status=overall,
            system_statuses=system_statuses,
            active_faults=active,
            fault_count=len(active),
            total_systems=len(system_statuses),
            degraded_systems=degraded,
            critical_systems=critical,
        )
        self._health_reports.append(report)
        return report

    def resolve_fault(self, fault_id: str):
        """Mark a fault as resolved."""
        if fault_id in self._active_faults:
            self._active_faults[fault_id].resolved = True

    def get_active_faults(self) -> list[FaultEvent]:
        return [f for f in self._active_faults.values() if not f.resolved]

    def get_latest_report(self) -> HealthReport | None:
        return self._health_reports[-1] if self._health_reports else None

    # ================================================================
    # Enhancement: Adaptive Threshold Tuning
    # ================================================================

    def record_fault_outcome(
        self, fault_id: str, was_real_problem: bool
    ):
        """
        Record whether a detected fault was a real problem or a false positive.
        Called by RepairSubsystem after repair attempt or by manual feedback.

        Args:
            fault_id: The fault ID from FaultEvent
            was_real_problem: True if the fault required actual intervention
        """
        fault = self._active_faults.get(fault_id)
        metric = fault.metric_name if fault else "unknown"

        self._fault_outcomes.append({
            "fault_id": fault_id,
            "metric": metric,
            "was_real_problem": was_real_problem,
            "timestamp": time.time(),
        })
        logger.debug(
            f"[ISHM:INFO] Outcome recorded: {fault_id} "
            f"real_problem={was_real_problem}"
        )

    def _auto_adjust_thresholds(self):
        """
        Analyze recent fault outcomes and adjust thresholds:
        - High false positive rate → relax thresholds (increase values)
        - Low false positive rate → tighten thresholds (decrease values)

        Uses the last 50 outcomes for the calculation.
        """
        recent = self._fault_outcomes[-50:]
        if len(recent) < 10:
            return  # Not enough data

        # Calculate false positive rate per metric
        metric_stats: dict[str, dict] = {}
        for outcome in recent:
            metric = outcome["metric"]
            if metric not in metric_stats:
                metric_stats[metric] = {"total": 0, "false_positives": 0}
            metric_stats[metric]["total"] += 1
            if not outcome["was_real_problem"]:
                metric_stats[metric]["false_positives"] += 1

        adjustments_made = []

        for metric, stats in metric_stats.items():
            if stats["total"] < 5:
                continue

            fp_rate = stats["false_positives"] / stats["total"]

            # Map metrics to threshold keys
            threshold_keys = []
            if "error_count" in metric:
                threshold_keys = ["error_count_warning", "error_count_critical"]
            elif "queue_size" in metric:
                threshold_keys = ["queue_size_warning", "queue_size_critical"]

            for key in threshold_keys:
                if key not in self.thresholds:
                    continue

                old_val = self.thresholds[key]
                bounds = self._THRESHOLD_BOUNDS.get(key, (1, 1000))

                if fp_rate > 0.5:
                    # Too many false positives → relax (increase threshold)
                    new_val = min(int(old_val * 1.25), bounds[1])
                    reason = f"high false positive rate ({fp_rate:.0%})"
                elif fp_rate < 0.1 and stats["total"] >= 10:
                    # Very few false positives → tighten slightly
                    new_val = max(int(old_val * 0.9), bounds[0])
                    reason = f"low false positive rate ({fp_rate:.0%})"
                else:
                    continue  # No adjustment needed

                if new_val != old_val:
                    self.thresholds[key] = new_val
                    adjustment = {
                        "key": key,
                        "old": old_val,
                        "new": new_val,
                        "reason": reason,
                        "fp_rate": round(fp_rate, 3),
                        "sample_size": stats["total"],
                        "timestamp": time.time(),
                    }
                    self._threshold_adjustments.append(adjustment)
                    adjustments_made.append(adjustment)
                    logger.info(
                        f"[ISHM:TUNE] {key}: {old_val} → {new_val} "
                        f"(reason: {reason})"
                    )

        if adjustments_made:
            logger.info(
                f"[ISHM:TUNE] Auto-adjusted {len(adjustments_made)} threshold(s)"
            )

    def set_threshold(self, key: str, value: int) -> bool:
        """
        Manually override a threshold value.
        Returns True if successful, False if key is unknown.
        """
        if key not in self.thresholds:
            return False

        bounds = self._THRESHOLD_BOUNDS.get(key, (1, 1000))
        clamped = max(bounds[0], min(value, bounds[1]))

        old_val = self.thresholds[key]
        self.thresholds[key] = clamped

        self._threshold_adjustments.append({
            "key": key,
            "old": old_val,
            "new": clamped,
            "reason": "manual_override",
            "timestamp": time.time(),
        })
        logger.info(f"[ISHM:TUNE] Manual override: {key} = {clamped}")
        return True

    def get_threshold_stats(self) -> dict:
        """Get current thresholds and tuning statistics."""
        recent = self._fault_outcomes[-50:]
        total = len(recent)
        false_positives = sum(1 for o in recent if not o["was_real_problem"])

        return {
            "current_thresholds": dict(self.thresholds),
            "auto_tune_enabled": self._auto_tune_enabled,
            "total_outcomes_recorded": len(self._fault_outcomes),
            "recent_false_positive_rate": (
                round(false_positives / total, 3) if total > 0 else 0
            ),
            "adjustments_made": len(self._threshold_adjustments),
            "last_adjustments": self._threshold_adjustments[-5:],
            "bounds": dict(self._THRESHOLD_BOUNDS),
        }

    def serialize_thresholds(self) -> dict:
        """Serialize threshold state for persistence."""
        return {
            "thresholds": dict(self.thresholds),
            "auto_tune_enabled": self._auto_tune_enabled,
            "fault_outcomes": self._fault_outcomes[-100:],  # Keep last 100
            "adjustments": self._threshold_adjustments[-50:],
        }

    def rehydrate_thresholds(self, state: dict):
        """Restore threshold state from persistence."""
        if "thresholds" in state:
            for key, val in state["thresholds"].items():
                if key in self.thresholds:
                    self.thresholds[key] = val
        self._auto_tune_enabled = state.get("auto_tune_enabled", True)
        self._fault_outcomes = state.get("fault_outcomes", [])
        self._threshold_adjustments = state.get("adjustments", [])
        logger.info(
            f"[ISHM:TUNE] Rehydrated thresholds: {self.thresholds}, "
            f"{len(self._fault_outcomes)} outcomes, "
            f"{len(self._threshold_adjustments)} adjustments"
        )


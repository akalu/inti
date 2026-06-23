"""
INTI - TAS (AI Agent Version) — ISHM Data Tier (Tier 1)
====================================
Raw telemetry collection from ALL constellation systems.

Sources:
  - Sensory System (Standards & Limits, System State)
  - Will System (Repair Subsystem telemetry)
  - All Noumenon networks (fragment counts, latencies)
  - System health endpoints (error counts, uptimes)

Enhanced with performance metrics:
  - LLM call latency, token usage, cost tracking
  - Message processing response times
  - Memory pressure (vector store sizes, readings buffer)
  - Tool execution statistics
  - Cycle-level performance summaries

Ref: Figueroa PPT slide 15
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.base import TASNode
    from core.nexus import NexusCogitationis

logger = logging.getLogger("taas.ishm")


@dataclass
class TelemetryReading:
    """A single raw telemetry reading from a system."""
    system_name: str
    metric_name: str
    value: Any
    timestamp: float = field(default_factory=time.time)
    unit: str = ""
    tags: dict = field(default_factory=dict)


class DataTier:
    """
    ISHM Tier 1 — Raw Health Data Collection.
    Collects telemetry from all constellation systems at regular intervals.

    Enhanced with performance metrics:
    - LLM call latency per system
    - Token usage tracking
    - Message processing response times
    - Memory / buffer pressure indicators
    """

    def __init__(self):
        self._readings: list[TelemetryReading] = []
        self._max_readings = 5_000
        self._collection_count = 0

        # --- Performance metrics tracking ---
        self._perf_history: list[dict] = []   # Per-cycle summaries
        self._max_perf_history = 500

    async def collect_from_node(self, node: "TASNode") -> list[TelemetryReading]:
        """Collect raw telemetry from a single constellation system."""
        readings = []
        status = node.get_status()

        # Core health metrics
        readings.append(TelemetryReading(
            system_name=node.name,
            metric_name="health_status",
            value=status["health"],
        ))
        readings.append(TelemetryReading(
            system_name=node.name,
            metric_name="message_count",
            value=status["message_count"],
            unit="messages",
        ))
        readings.append(TelemetryReading(
            system_name=node.name,
            metric_name="error_count",
            value=status["error_count"],
            unit="errors",
        ))
        readings.append(TelemetryReading(
            system_name=node.name,
            metric_name="uptime",
            value=status.get("uptime", 0),
            unit="seconds",
        ))

        # Subsystem health
        for sub_name, sub_status in status.get("subsystems", {}).items():
            readings.append(TelemetryReading(
                system_name=node.name,
                metric_name=f"subsystem.{sub_name}.active",
                value=sub_status.get("active", False),
            ))

        return readings

    async def collect_all(self, nodes: dict[str, "TASNode"]) -> list[TelemetryReading]:
        """Collect telemetry from all registered systems."""
        self._collection_count += 1
        batch: list[TelemetryReading] = []

        for name, node in nodes.items():
            try:
                readings = await self.collect_from_node(node)
                batch.extend(readings)
            except Exception as e:
                logger.error(f"[ISHM:DATA] Failed to collect from {name}: {e}")
                batch.append(TelemetryReading(
                    system_name=name,
                    metric_name="collection_error",
                    value=str(e),
                ))

        self._readings.extend(batch)
        # Trim old readings
        if len(self._readings) > self._max_readings:
            self._readings = self._readings[-self._max_readings:]

        return batch

    async def collect_nexus_telemetry(self, nexus: "NexusCogitationis") -> list[TelemetryReading]:
        """Collect telemetry specifically from the Nexus bus."""
        status = nexus.get_status()
        readings = [
            TelemetryReading(
                system_name="NEXUS",
                metric_name="queue_size",
                value=status["queue_size"],
                unit="messages",
            ),
            TelemetryReading(
                system_name="NEXUS",
                metric_name="consciousness_size",
                value=status["consciousness_size"],
                unit="entries",
            ),
            TelemetryReading(
                system_name="NEXUS",
                metric_name="assembled_thoughts",
                value=status["assembled_thoughts"],
                unit="thoughts",
            ),
        ]
        self._readings.extend(readings)
        return readings

    # ================================================================
    # Enhancement: Performance Metrics Collection
    # ================================================================

    async def collect_performance_metrics(
        self, nodes: dict[str, "TASNode"], nexus: Optional["NexusCogitationis"] = None
    ) -> list[TelemetryReading]:
        """
        Collect deep performance metrics beyond basic health.

        Metrics gathered per system:
        - llm_call_count:    total LLM invocations
        - llm_latency_avg:   average LLM response time (ms)
        - llm_latency_last:  most recent LLM call duration (ms)
        - llm_tokens_total:  total tokens consumed
        - msg_processing_ms: average message processing time (ms)
        - tool_exec_count:   total tool executions
        - tool_error_count:  tool execution failures
        - buffer_pressure:   readings buffer fill percentage

        Returns the new performance readings.
        """
        perf_readings: list[TelemetryReading] = []

        for name, node in nodes.items():
            try:
                # LLM metrics (from subsystems that use .think())
                for sub_name, sub in node.subsystems.items():
                    llm_stats = getattr(sub, "_llm_stats", None)
                    if llm_stats and isinstance(llm_stats, dict):
                        perf_readings.append(TelemetryReading(
                            system_name=name,
                            metric_name=f"perf.{sub_name}.llm_call_count",
                            value=llm_stats.get("call_count", 0),
                            unit="calls",
                            tags={"subsystem": sub_name},
                        ))
                        perf_readings.append(TelemetryReading(
                            system_name=name,
                            metric_name=f"perf.{sub_name}.llm_latency_avg_ms",
                            value=round(llm_stats.get("avg_latency_ms", 0), 1),
                            unit="ms",
                            tags={"subsystem": sub_name},
                        ))
                        perf_readings.append(TelemetryReading(
                            system_name=name,
                            metric_name=f"perf.{sub_name}.llm_tokens_total",
                            value=llm_stats.get("total_tokens", 0),
                            unit="tokens",
                            tags={"subsystem": sub_name},
                        ))

                    # Fallback: check for individual timing attributes
                    last_think_ms = getattr(sub, "_last_think_ms", None)
                    if last_think_ms is not None:
                        perf_readings.append(TelemetryReading(
                            system_name=name,
                            metric_name=f"perf.{sub_name}.llm_latency_last_ms",
                            value=round(last_think_ms, 1),
                            unit="ms",
                            tags={"subsystem": sub_name},
                        ))

                    think_count = getattr(sub, "_think_count", None)
                    if think_count is not None:
                        perf_readings.append(TelemetryReading(
                            system_name=name,
                            metric_name=f"perf.{sub_name}.think_count",
                            value=think_count,
                            unit="calls",
                            tags={"subsystem": sub_name},
                        ))

                # Node-level message processing time
                avg_process_ms = getattr(node, "_avg_process_ms", None)
                if avg_process_ms is not None:
                    perf_readings.append(TelemetryReading(
                        system_name=name,
                        metric_name="perf.msg_processing_avg_ms",
                        value=round(avg_process_ms, 1),
                        unit="ms",
                    ))

                # Error rate (errors / messages)
                status = node.get_status()
                msg_count = status.get("message_count", 0)
                err_count = status.get("error_count", 0)
                if msg_count > 0:
                    perf_readings.append(TelemetryReading(
                        system_name=name,
                        metric_name="perf.error_rate",
                        value=round(err_count / msg_count, 4),
                        unit="ratio",
                    ))

            except Exception as e:
                logger.debug(f"[ISHM:PERF] Failed to collect perf from {name}: {e}")

        # --- Buffer pressure (ISHM internal health) ---
        buffer_fill = len(self._readings) / self._max_readings
        perf_readings.append(TelemetryReading(
            system_name="ISHM",
            metric_name="perf.readings_buffer_fill",
            value=round(buffer_fill, 3),
            unit="ratio",
        ))
        perf_readings.append(TelemetryReading(
            system_name="ISHM",
            metric_name="perf.total_readings_stored",
            value=len(self._readings),
            unit="readings",
        ))
        perf_readings.append(TelemetryReading(
            system_name="ISHM",
            metric_name="perf.collection_cycles",
            value=self._collection_count,
            unit="cycles",
        ))

        # --- Nexus performance ---
        if nexus:
            try:
                nst = nexus.get_status()
                perf_readings.append(TelemetryReading(
                    system_name="NEXUS",
                    metric_name="perf.total_dialogues",
                    value=nst.get("total_dialogues", 0),
                    unit="dialogues",
                ))
                perf_readings.append(TelemetryReading(
                    system_name="NEXUS",
                    metric_name="perf.consciousness_entries",
                    value=nst.get("consciousness_size", 0),
                    unit="entries",
                ))
            except Exception:
                pass

        # --- Tool registry performance ---
        # If nodes have tool stats, collect them
        for name, node in nodes.items():
            tool_stats = getattr(node, "_tool_stats", None)
            if tool_stats and isinstance(tool_stats, dict):
                perf_readings.append(TelemetryReading(
                    system_name=name,
                    metric_name="perf.tool_exec_count",
                    value=tool_stats.get("total_executions", 0),
                    unit="executions",
                ))
                perf_readings.append(TelemetryReading(
                    system_name=name,
                    metric_name="perf.tool_error_count",
                    value=tool_stats.get("errors", 0),
                    unit="errors",
                ))
                avg_tool_ms = tool_stats.get("avg_exec_ms", 0)
                if avg_tool_ms:
                    perf_readings.append(TelemetryReading(
                        system_name=name,
                        metric_name="perf.tool_avg_exec_ms",
                        value=round(avg_tool_ms, 1),
                        unit="ms",
                    ))

        # Store readings
        self._readings.extend(perf_readings)
        if len(self._readings) > self._max_readings:
            self._readings = self._readings[-self._max_readings:]

        return perf_readings

    def record_cycle_performance(self, cycle_data: dict):
        """
        Record a performance summary for a complete ISHM cycle.
        Called by ISHMEngine.run_cycle() at the end of each cycle.
        """
        cycle_data["timestamp"] = time.time()
        self._perf_history.append(cycle_data)
        if len(self._perf_history) > self._max_perf_history:
            self._perf_history = self._perf_history[-self._max_perf_history:]

    def get_performance_summary(self, last_n: int = 10) -> dict:
        """
        Aggregate performance stats from the last N cycles.
        Returns averages, peaks, and trends.
        """
        recent = self._perf_history[-last_n:]
        if not recent:
            return {"cycles": 0, "message": "No performance data yet"}

        cycle_times = [c.get("cycle_time_ms", 0) for c in recent]
        fault_counts = [c.get("faults_detected", 0) for c in recent]
        reading_counts = [c.get("readings", 0) for c in recent]

        # Collect perf.* readings for LLM latency
        perf_readings = [
            r for r in self._readings
            if r.metric_name.startswith("perf.") and "llm_latency" in r.metric_name
        ]
        llm_latencies = [r.value for r in perf_readings[-50:] if isinstance(r.value, (int, float))]

        return {
            "cycles_analyzed": len(recent),
            "cycle_time_avg_ms": round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else 0,
            "cycle_time_peak_ms": round(max(cycle_times), 1) if cycle_times else 0,
            "faults_avg_per_cycle": round(sum(fault_counts) / len(fault_counts), 2) if fault_counts else 0,
            "readings_avg_per_cycle": round(sum(reading_counts) / len(reading_counts), 1) if reading_counts else 0,
            "llm_latency_avg_ms": round(sum(llm_latencies) / len(llm_latencies), 1) if llm_latencies else 0,
            "llm_latency_peak_ms": round(max(llm_latencies), 1) if llm_latencies else 0,
            "buffer_fill_pct": round(len(self._readings) / self._max_readings * 100, 1),
            "total_readings_stored": len(self._readings),
            "perf_readings_count": len(perf_readings),
        }

    # ================================================================
    # Original query methods
    # ================================================================

    def get_latest(self, system_name: str = "", count: int = 50) -> list[TelemetryReading]:
        """Get the latest readings, optionally filtered by system."""
        if system_name:
            filtered = [r for r in self._readings if r.system_name == system_name]
            return filtered[-count:]
        return self._readings[-count:]

    def get_metric_history(
        self, system_name: str, metric_name: str, count: int = 20
    ) -> list[TelemetryReading]:
        """Get history of a specific metric for a system."""
        return [
            r for r in self._readings
            if r.system_name == system_name and r.metric_name == metric_name
        ][-count:]

    @property
    def total_readings(self) -> int:
        return len(self._readings)

    @property
    def collection_count(self) -> int:
        return self._collection_count

    # ================================================================
    # Source Code Integrity Check (Self-Patching Support)
    # ================================================================

    # Core files to monitor for syntax errors every ISHM cycle
    MONITORED_FILES = [
        "systems/will.py",
        "systems/reason.py",
        "systems/intellect.py",
        "systems/thought.py",
        "systems/sensory.py",
        "systems/decision.py",
        "systems/understanding.py",
        "systems/presentation.py",
        "core/nexus.py",
        "core/base.py",
    ]

    def check_source_integrity(self, project_root: str = "") -> list[TelemetryReading]:
        """
        Compile-check all monitored source files.
        Returns TelemetryReadings — one per broken file.

        Uses py_compile (0 LLM tokens, pure deterministic).
        Called every ISHM cycle to detect syntax errors
        introduced by corruption, accidental edits, or test scenarios.
        """
        import py_compile
        from pathlib import Path

        if not project_root:
            project_root = str(Path(__file__).resolve().parent.parent)

        # Track files already reported (only log WARNING once per file)
        if not hasattr(self, '_reported_syntax_errors'):
            self._reported_syntax_errors: set[str] = set()

        readings = []
        current_errors: set[str] = set()
        for rel_path in self.MONITORED_FILES:
            full_path = Path(project_root) / rel_path
            if not full_path.exists():
                continue
            try:
                py_compile.compile(str(full_path), doraise=True)
                # File is OK now — remove from reported set if it was there
                self._reported_syntax_errors.discard(rel_path)
            except py_compile.PyCompileError as e:
                current_errors.add(rel_path)
                # Extract the system name from path (e.g., "systems/thought.py" → "THOUGHT")
                system_name = Path(rel_path).stem.upper()
                if rel_path.startswith("core/"):
                    system_name = f"CORE:{Path(rel_path).stem.upper()}"

                error_msg = str(e).replace(str(project_root), ".")[:500]
                readings.append(TelemetryReading(
                    system_name=system_name,
                    metric_name="source_syntax_error",
                    value=error_msg,
                    unit="error",
                    tags={
                        "file_path": rel_path,
                        "full_path": str(full_path),
                    },
                ))

                # Only log WARNING the first time; debug afterwards
                if rel_path not in self._reported_syntax_errors:
                    logger.warning(f"[ISHM:INTEGRITY] Syntax error in {rel_path}: {error_msg[:120]}")
                    self._reported_syntax_errors.add(rel_path)

        self._readings.extend(readings)
        return readings


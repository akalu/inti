"""
INTI - TAS (AI Agent Version) — ISHM Engine (Orchestrator)
=======================================
Runs all 3 ISHM tiers in a coordinated cycle across all constellation systems.

Cross-system interfaces:
  - Will       → Repair Subsystem receives directives
  - Sensory    → Standards & Limits + System State feed real-time data
  - Decision   → Health status influences course-of-action priority
  - Thought    → Anomaly events trigger self-awareness monitoring in Nexus
  - Reason     → Threshold violations trigger emergency Laws-level constraints
  - Presentation → Status rendered in real-time

Ref: Figueroa PPT slide 15
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, TYPE_CHECKING

from core.messages import (
    TASMessage, MessageType, NodePriority, HealthStatus,
)
from ishm.data_tier import DataTier
from ishm.information_tier import InformationTier, FaultSeverity
from ishm.knowledge_tier import KnowledgeTier, HealthDirective, FaultModel

if TYPE_CHECKING:
    from core.base import TASNode
    from core.nexus import NexusCogitationis
    from core.memory import MemoryManager
    from tools.registry import ToolRegistry

logger = logging.getLogger("taas.ishm")


class ISHMEngine:
    """
    Integrated System Health Management Engine.
    Orchestrates the 3-tier ISHM cycle:
      Tier 1 (Data)        → collect raw telemetry
      Tier 2 (Information) → detect and correlate faults
      Tier 3 (Knowledge)   → match models and generate directives
    """

    def __init__(
        self,
        nexus: Optional["NexusCogitationis"] = None,
        memory: Optional["MemoryManager"] = None,
    ):
        self.nexus = nexus
        self.memory = memory
        self.tool_registry: Optional["ToolRegistry"] = None

        # Toggle: set ISHM_ENABLED=false in .env or ishm.enabled = False at runtime
        import os
        self.enabled = os.getenv("ISHM_ENABLED", "true").lower() in ("true", "1", "yes")

        # 3 tiers
        self.data_tier = DataTier()
        self.info_tier = InformationTier()
        self.knowledge_tier = KnowledgeTier()

        # State
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._cycle_interval = 5.0  # seconds between cycles
        self._web_research_count = 0

    def set_nexus(self, nexus: "NexusCogitationis"):
        self.nexus = nexus

    def set_memory(self, memory: "MemoryManager"):
        self.memory = memory

    def set_tool_registry(self, registry: "ToolRegistry"):
        """Connect ISHM to the tool registry for autonomous web research."""
        self.tool_registry = registry
        logger.info("[ISHM] Tool registry connected — web research enabled")

    # --- Main Cycle ---

    async def run_cycle(self) -> dict:
        """Run one complete ISHM cycle across all systems."""
        if not self.enabled:
            return {"status": "disabled", "message": "ISHM paused (set ISHM_ENABLED=true to resume)"}
        if self.nexus is None:
            return {"error": "No Nexus connected"}

        self._cycle_count += 1
        cycle_start = time.time()

        # Tier 1: Collect raw telemetry
        readings = await self.data_tier.collect_all(self.nexus.nodes)
        nexus_readings = await self.data_tier.collect_nexus_telemetry(self.nexus)
        all_readings = readings + nexus_readings

        # Tier 1.5: Collect performance metrics (LLM latency, tokens, etc.)
        perf_readings = await self.data_tier.collect_performance_metrics(
            self.nexus.nodes, self.nexus
        )

        # Tier 1.6: Source code integrity check (py_compile on core files)
        integrity_readings = self.data_tier.check_source_integrity()
        all_readings.extend(integrity_readings)

        # Tier 2: Detect and analyze faults
        faults = self.info_tier.analyze_readings(all_readings)

        # Generate health report
        system_statuses = {
            name: HealthStatus(node.health.value)
            for name, node in self.nexus.nodes.items()
        }
        report = self.info_tier.generate_health_report(system_statuses)

        # Tier 3: Generate directives for detected faults
        directives = self.knowledge_tier.process_faults(faults)

        # Fallback: research unknown faults via web_crawler (Crawl4AI)
        # Skip if there's already a pending repair patch (avoid noise)
        has_pending_repair = self._has_pending_patches()
        unmatched = [
            f for f in faults
            if not any(d.source_fault == f.fault_id for d in directives)
        ]
        if unmatched and self.tool_registry and not has_pending_repair:
            for fault in unmatched:
                researched = await self._research_unknown_fault(fault)
                if researched:
                    directives.append(researched)

        # Write health state to shared memory
        if self.memory:
            self.memory.write(
                "SHARED:ISHM:health", "latest_report",
                {
                    "overall": report.overall_status.value,
                    "degraded": report.degraded_systems,
                    "critical": report.critical_systems,
                    "fault_count": report.fault_count,
                    "cycle": self._cycle_count,
                },
                requester="ISHM",
            )

        # Dispatch directives to target systems
        # Skip dispatch if a pending patch already exists (reduce noise)
        if not has_pending_repair:
            for directive in directives:
                await self._dispatch_directive(directive)
        elif directives:
            logger.debug(
                f"[ISHM] Skipping directive dispatch — pending repair patch exists"
            )

        # Alert Reason on critical faults
        critical_faults = [f for f in faults if f.severity == FaultSeverity.CRITICAL]
        if critical_faults:
            await self._alert_reason(critical_faults)

        # Alert Thought (Nexus) on any anomalies
        if faults and not has_pending_repair:
            await self._alert_thought(faults)

        cycle_time = time.time() - cycle_start
        result = {
            "cycle": self._cycle_count,
            "readings": len(all_readings),
            "perf_readings": len(perf_readings),
            "faults_detected": len(faults),
            "directives_generated": len(directives),
            "overall_status": report.overall_status.value,
            "cycle_time_ms": round(cycle_time * 1000, 1),
        }

        # Record cycle performance for summaries
        self.data_tier.record_cycle_performance(result)

        if faults:
            logger.info(
                f"[ISHM] Cycle #{self._cycle_count}: "
                f"{len(faults)} faults, {len(directives)} directives, "
                f"status={report.overall_status.value}"
            )

        # Auto-persist every 5 cycles
        if self._cycle_count % 5 == 0:
            self.persist_state()

        return result

    # --- Directive Dispatch ---

    async def _dispatch_directive(self, directive: HealthDirective):
        """Send a health directive to the appropriate system."""
        if self.nexus is None:
            return

        directive_content = {
            "directive": directive.directive_id,
            "action": directive.action,
            "target": directive.target_system,
            "procedure": directive.details,
            "severity": directive.severity.value,
            "source_fault": directive.source_fault,
        }

        # Will System gets repair directives via HEALTH_ALERT
        if directive.action == "repair":
            target = self.nexus.nodes.get("WILL")
            if target:
                msg = TASMessage(
                    priority=NodePriority.HIGH.value,
                    sender="ISHM",
                    receiver="WILL",
                    msg_type=MessageType.HEALTH_ALERT,
                    content=directive_content,
                )
                self.nexus.consciousness.record(
                    source="ISHM", event_type="repair_dispatch",
                    content=f"Repair directive → WILL: {directive.details[:200]}",
                )
                try:
                    await target.process_message(msg)
                    logger.info(f"[ISHM] Repair directive dispatched to WILL: {directive.directive_id}")
                except Exception as e:
                    logger.error(f"[ISHM] Failed to dispatch repair to WILL: {e}")

        # Alert directives go to Sensory Standards & Limits
        elif directive.action == "alert":
            target = self.nexus.nodes.get("SENSORY")
            if target:
                msg = TASMessage(
                    priority=NodePriority.HIGH.value,
                    sender="ISHM",
                    receiver="SENSORY",
                    msg_type=MessageType.SENSORY_BURST,
                    content=directive_content,
                )
                try:
                    await target.process_message(msg)
                except Exception as e:
                    logger.error(f"[ISHM] Failed to dispatch alert to SENSORY: {e}")

    async def _alert_reason(self, critical_faults):
        """Alert Reason System about critical faults (emergency constraints)."""
        if self.nexus is None:
            return
        await self.nexus.monologue(
            sender="ISHM",
            receiver="REASON",
            content={
                "alert_type": "CRITICAL_HEALTH",
                "faults": [
                    {"id": f.fault_id, "system": f.system_name, "desc": f.description}
                    for f in critical_faults
                ],
                "recommendation": "Consider activating emergency Laws-level constraints.",
            },
            priority=NodePriority.CRITICAL,
        )

    async def _alert_thought(self, faults):
        """Alert Thought System about anomalies (self-awareness monitoring)."""
        if self.nexus is None:
            return
        await self.nexus.monologue(
            sender="ISHM",
            receiver="THOUGHT",
            content={
                "alert_type": "HEALTH_ANOMALY",
                "fault_count": len(faults),
                "systems_affected": list(set(f.system_name for f in faults)),
                "recommendation": "Activate self-awareness monitoring.",
            },
            priority=NodePriority.HIGH,
        )

    # --- Web Research Fallback ---

    async def _research_unknown_fault(self, fault: FaultEvent) -> HealthDirective | None:
        """
        When no fault model matches, research the web for solutions.

        Strategy (2-step with Crawl4AI):
        1. Use web_search to find relevant URLs for the error
        2. Use web_crawler (Crawl4AI) to extract clean LLM-ready Markdown
           from the top result — saves ~60-70% tokens vs raw HTML

        Falls back to web_search-only if web_crawler is unavailable.
        Creates an ad-hoc directive AND learns a new FaultModel.
        """
        if self.tool_registry is None:
            return None

        self._web_research_count += 1
        search_query = (
            f"{fault.system_name} system {fault.description} "
            f"{fault.metric_name} error solution"
        )

        logger.info(f"[ISHM] Researching unknown fault: {search_query[:80]}")

        try:
            web_info = ""
            research_method = "web_search"
            token_savings = 0

            # Step 1: Find relevant URLs via web_search
            search_result = await self.tool_registry.execute(
                "web_search",
                query=search_query,
                search_type="error",
                max_results=5,
            )

            if not search_result.success:
                logger.warning(f"[ISHM] Web search failed: {search_result.error}")
                return None

            # Step 2: Try to crawl the top result with Crawl4AI
            top_url = None
            search_output = search_result.output
            if isinstance(search_output, list) and search_output:
                # web_search returns list of result dicts with 'url'
                first = search_output[0]
                if isinstance(first, dict):
                    top_url = first.get("url") or first.get("link")
            elif isinstance(search_output, str):
                # Try to extract a URL from text
                import re
                urls = re.findall(r'https?://\S+', str(search_output))
                if urls:
                    top_url = urls[0]

            # Try Crawl4AI for clean Markdown extraction
            if top_url:
                try:
                    crawl_result = await self.tool_registry.execute(
                        "web_crawler",
                        action="crawl",
                        url=top_url,
                        max_chars=3000,
                    )
                    if crawl_result.success and crawl_result.output:
                        web_info = str(crawl_result.output)[:2000]
                        research_method = "web_crawler (Crawl4AI)"
                        token_savings = crawl_result.metadata.get(
                            "token_savings_pct", 0
                        )
                        logger.info(
                            f"[ISHM] Crawl4AI extracted {len(web_info)} chars "
                            f"from {top_url} (saved ~{token_savings}% tokens)"
                        )
                except Exception as crawl_err:
                    logger.debug(
                        f"[ISHM] Crawl4AI unavailable, using web_search: {crawl_err}"
                    )

            # Fallback: use raw web_search results if crawl didn't work
            if not web_info:
                web_info = str(search_output)[:1500]
                research_method = "web_search (fallback)"

            # Build recovery procedure from research
            recovery_procedure = (
                f"[WEB-RESEARCHED via {research_method}]\n"
                f"Query: {search_query}\n"
                f"Source: {top_url or 'search results'}\n"
                f"Token savings: ~{token_savings}%\n\n"
                f"Findings:\n{web_info}\n\n"
                f"Suggested steps:\n"
                f"1. Review the findings above for applicable fixes.\n"
                f"2. Apply the most relevant solution.\n"
                f"3. Monitor for recurrence."
            )

            # Create ad-hoc directive
            self.knowledge_tier._directive_counter += 1
            directive = HealthDirective(
                directive_id=f"DIR-WEB-{self.knowledge_tier._directive_counter:04d}",
                target_system=fault.system_name,
                action="repair",
                details=recovery_procedure,
                source_fault=fault.fault_id,
                severity=fault.severity,
            )
            self.knowledge_tier._directives.append(directive)

            # LEARN: create a new FaultModel from web results
            new_model = FaultModel(
                fault_pattern=fault.metric_name or fault.description[:30],
                affected_system=fault.system_name,
                severity=fault.severity,
                description=f"[Learned via {research_method}] {fault.description}",
                recovery_procedure=recovery_procedure[:500],
                auto_recoverable=True,
                cooldown_seconds=120.0,
            )
            self.knowledge_tier.add_fault_model(new_model)
            logger.info(
                f"[ISHM] Learned new fault model from web: "
                f"{new_model.fault_pattern} → {fault.system_name} "
                f"(method: {research_method})"
            )

            # Record in Consciousness Stream
            if self.nexus:
                self.nexus.consciousness.record(
                    source="ISHM",
                    event_type="web_research_recovery",
                    content=(
                        f"Researched unknown fault '{fault.description}' "
                        f"via {research_method}. "
                        f"Created directive {directive.directive_id} "
                        f"and learned new model."
                    ),
                    metadata={
                        "query": search_query,
                        "fault_id": fault.fault_id,
                        "source_url": top_url,
                        "method": research_method,
                        "token_savings_pct": token_savings,
                    },
                )

            return directive

        except Exception as e:
            logger.error(f"[ISHM] Web research error: {e}")
            return None

    # --- Background Monitor ---

    async def start_monitoring(self):
        """Start the background ISHM monitoring loop."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("[ISHM] Background monitoring started")

    async def stop_monitoring(self):
        """Stop the background monitoring loop and persist state."""
        self._running = False
        self.persist_state()  # Save before shutdown
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("[ISHM] Background monitoring stopped (state persisted)")

    async def _monitor_loop(self):
        """Background loop that runs ISHM cycles periodically."""
        while self._running:
            try:
                await self.run_cycle()
                await asyncio.sleep(self._cycle_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ISHM] Monitor error: {e}")
                await asyncio.sleep(self._cycle_interval)

    # --- Introspection ---

    def _has_pending_patches(self) -> bool:
        """Check if WILL's RepairSubsystem has pending patches awaiting approval."""
        if not self.nexus:
            return False
        will = self.nexus.nodes.get("WILL")
        if will and hasattr(will, "repair"):
            pending = will.repair.get_pending_patches()
            return len(pending) > 0
        return False

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "cycles": self._cycle_count,
            "total_readings": self.data_tier.total_readings,
            "active_faults": len(self.info_tier.get_active_faults()),
            "pending_directives": len(self.knowledge_tier.get_pending_directives()),
            "recovery_stats": self.knowledge_tier.get_recovery_stats(),
            "web_research": {
                "enabled": self.tool_registry is not None,
                "researches_done": self._web_research_count,
            },
        }

    # --- Persistence ---

    def persist_state(self):
        """
        Save all ISHM state to MemoryManager for cross-restart persistence.
        Writes to SHARED:ISHM:state (engine counters) and
        SHARED:ISHM:knowledge (KnowledgeTier state).
        """
        if not self.memory:
            return

        # Persist KnowledgeTier state (learned models, directives, recovery history)
        kt_state = self.knowledge_tier.serialize_state()
        self.memory.write(
            "SHARED:ISHM:knowledge", "knowledge_tier_state",
            kt_state, requester="ISHM",
        )

        # Persist engine-level counters
        self.memory.write(
            "SHARED:ISHM:state", "engine_state",
            {
                "cycle_count": self._cycle_count,
                "web_research_count": self._web_research_count,
                "persisted_at": time.time(),
            },
            requester="ISHM",
        )

        logger.debug(
            f"[ISHM] State persisted: cycle={self._cycle_count}, "
            f"learned_models={len(kt_state.get('learned_models', []))}, "
            f"directives={len(kt_state.get('directives', []))}"
        )

    def rehydrate(self) -> int:
        """
        Restore ISHM state from MemoryManager on startup.
        Returns total entries restored.
        """
        if not self.memory:
            return 0

        restored = 0

        # Restore KnowledgeTier state
        kt_store = self.memory.get_store("SHARED:ISHM:knowledge")
        if kt_store:
            kt_state = kt_store._data.get("knowledge_tier_state")
            if kt_state and isinstance(kt_state, dict):
                restored += self.knowledge_tier.rehydrate_state(kt_state)

        # Restore engine counters
        engine_store = self.memory.get_store("SHARED:ISHM:state")
        if engine_store:
            engine_state = engine_store._data.get("engine_state")
            if engine_state and isinstance(engine_state, dict):
                self._cycle_count = engine_state.get("cycle_count", 0)
                self._web_research_count = engine_state.get("web_research_count", 0)
                restored += 1
                logger.info(
                    f"[ISHM] Engine state restored: cycle={self._cycle_count}, "
                    f"web_researches={self._web_research_count}"
                )

        if restored > 0:
            logger.info(f"[ISHM] Total entries rehydrated: {restored}")

        return restored

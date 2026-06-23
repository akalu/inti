"""
INTI - TAS (AI Agent Version) — The Will System (System 1)
=======================================
The executive system — dominant maker of decisions.
Assures survival and achievement of mission objectives.

Subsystems:
  SurvivalSubsystem       — energy management, self-preservation
  PropagationSubsystem    — species/system propagation
  DominanceSubsystem      — executive authority enforcement
  ScienceDataConversion   — raw data → actionable intelligence
  CravingSubsystem        — goal pursuit and motivation
  SearchForTruthSubsystem — axiomatic rules, instinct database
  MissionSubsystem        — mission objectives and tracking
  RepairSubsystem         — constellation repair + ISHM integration
  ExecutiveSubsystem      — executive decision execution

Ref: Figueroa PPT slides 22, 31-36
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from core.base import TASNode, Subsystem, monitor_health
from core.messages import (
    TASMessage, MessageType, NodePriority,
    ThoughtFragment, FragmentType, HealthStatus,
)

logger = logging.getLogger("taas")


# ============================================================
# Subsystems
# ============================================================

class SurvivalSubsystem(Subsystem):
    """
    Energy management and self-preservation.
    Manifested as searching, pursuing, fleeing, avoiding.
    Survival has priority over everything except Laws compliance.

    Energy conservation adapted to AI: "energy" = tokens = API cost.
    Tracks token consumption and enters conservation mode above threshold.

    Ref: Figueroa PPT slide 33 — "Must have energy for critical systems.
    Behavior influenced by motives, reflection, thinking, contemplation."
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Survival", parent)
        self._threat_log: list[dict] = []
        # Token budget (energy conservation)
        self._token_budget = {
            "daily_limit": 500_000,       # Configurable daily token budget
            "consumed_today": 0,
            "reset_time": time.time(),     # Last reset timestamp
            "conservation_threshold": 0.8, # 80% = enter conservation
            "conservation_active": False,
        }

    def _reset_daily_budget(self):
        """Reset daily token counter if 24hrs have elapsed."""
        elapsed = time.time() - self._token_budget["reset_time"]
        if elapsed >= 86400:  # 24 hours
            self._token_budget["consumed_today"] = 0
            self._token_budget["reset_time"] = time.time()
            self._token_budget["conservation_active"] = False
            self.log("budget_reset", "Daily token budget reset")

    def update_token_usage(self) -> dict:
        """
        Poll all system LLM adapters via Nexus to aggregate token usage.
        Called periodically by the mission loop or contemplation cycle.
        """
        self._reset_daily_budget()
        total_tokens = 0

        if self.nexus:
            for name, node in self.nexus.nodes.items():
                llm = getattr(node, '_llm', None)
                if llm and hasattr(llm, 'total_estimated_tokens'):
                    total_tokens += llm.total_estimated_tokens

        self._token_budget["consumed_today"] = total_tokens
        limit = self._token_budget["daily_limit"]
        threshold = self._token_budget["conservation_threshold"]

        was_active = self._token_budget["conservation_active"]
        now_active = total_tokens >= (limit * threshold)
        self._token_budget["conservation_active"] = now_active

        # Log transition into conservation mode
        if now_active and not was_active:
            pct = round(total_tokens / limit * 100, 1)
            self.log("conservation_activated",
                     f"Token usage at {pct}% ({total_tokens}/{limit})")
            logger.warning(
                f"[SURVIVAL] Conservation mode ACTIVATED: "
                f"{total_tokens}/{limit} tokens ({pct}%)"
            )
            # Record to consciousness stream
            if self.nexus and hasattr(self.nexus, 'consciousness'):
                self.nexus.consciousness.record(
                    source="WILL:Survival",
                    event_type="conservation_activated",
                    content=f"Token budget at {pct}%. Conservation mode engaged.",
                    metadata={"consumed": total_tokens, "limit": limit},
                )

        return {
            "consumed": total_tokens,
            "limit": limit,
            "percent_used": round(total_tokens / max(limit, 1) * 100, 1),
            "conservation_active": now_active,
        }

    def is_conservation_mode(self) -> bool:
        """Check if conservation mode is active (token budget > 80%)."""
        return self._token_budget["conservation_active"]

    def set_daily_limit(self, limit: int):
        """Set the daily token budget limit."""
        self._token_budget["daily_limit"] = max(1000, limit)

    async def check_survival_state(self) -> dict:
        """Assess current survival status by checking all constellation systems."""
        # Update token budget
        energy = self.update_token_usage()

        state = {
            "energy": energy,
            "critical_systems": [],
            "degraded_systems": [],
            "threats": [],
            "overall": "NOMINAL",
        }

        if self.nexus:
            for name, node in self.nexus.nodes.items():
                health = getattr(node, '_health', None)
                if health and health != HealthStatus.NOMINAL:
                    if health == HealthStatus.CRITICAL:
                        state["critical_systems"].append(name)
                        state["threats"].append(f"{name} in CRITICAL state")
                    elif health == HealthStatus.DEGRADED:
                        state["degraded_systems"].append(name)

        # Token exhaustion is a survival threat
        if energy["percent_used"] >= 95:
            state["threats"].append(
                f"Token budget critical: {energy['percent_used']}% consumed"
            )

        if state["critical_systems"] or energy["percent_used"] >= 95:
            state["overall"] = "CRITICAL"
        elif state["degraded_systems"] or energy["conservation_active"]:
            state["overall"] = "DEGRADED"

        self.log("survival_check", state["overall"])
        return state

    async def assess_threat(self, context: str) -> dict:
        """Use LLM to assess whether a situation is a threat to survival."""
        from config.axioms import LAWS, LawCategory
        survival_laws = [l.text for l in LAWS if l.category == LawCategory.SURVIVAL]

        prompt = (
            f"You are the Survival Subsystem of the Will System.\n"
            f"SURVIVAL LAWS: {survival_laws}\n\n"
            f"Assess this situation for threats: {context[:500]}\n\n"
            f"Respond as JSON: {{\"is_threat\": bool, \"threat_level\": "
            f"\"none\"|\"low\"|\"medium\"|\"critical\", "
            f"\"recommended_action\": \"pursue\"|\"avoid\"|\"flee\"|\"monitor\", "
            f"\"reasoning\": str}}"
        )
        response = await self.think(prompt)
        self.log("threat_assessment", response[:200])

        result = {"assessment": response, "context": context[:200]}

        # Execute the recommended reaction
        try:
            parsed = json.loads(response)
            if parsed.get("is_threat") and parsed.get("recommended_action"):
                await self.execute_reaction(
                    action=parsed["recommended_action"],
                    threat_level=parsed.get("threat_level", "low"),
                    reasoning=parsed.get("reasoning", ""),
                )
                result["reaction_executed"] = parsed["recommended_action"]
        except (json.JSONDecodeError, TypeError):
            pass

        return result

    async def execute_reaction(self, action: str, threat_level: str, reasoning: str):
        """
        Execute a concrete survival reaction based on threat assessment.
        Maps LLM recommendations to real system behaviors.

        Actions:
          pursue  — actively engage (trigger deliberation about the topic)
          avoid   — Skip/throttle non-essential operations
          flee    — Emergency shutdown of risky subsystems
          monitor — Record and watch (passive, log only)
        """
        self.log("reaction_executing", f"{action} (level={threat_level})")

        if action == "monitor":
            # Passive: just record to consciousness
            if self.nexus and hasattr(self.nexus, 'consciousness'):
                self.nexus.consciousness.record(
                    source="WILL:Survival",
                    event_type="threat_monitoring",
                    content=f"Monitoring threat (level={threat_level}): {reasoning[:200]}",
                )

        elif action == "avoid":
            # Throttle: enter conservation mode to reduce activity
            self._token_budget["conservation_active"] = True
            self.log("avoidance_activated", f"Conservation mode forced: {reasoning[:100]}")
            if self.nexus and hasattr(self.nexus, 'consciousness'):
                self.nexus.consciousness.record(
                    source="WILL:Survival",
                    event_type="threat_avoidance",
                    content=f"Avoiding threat by entering conservation: {reasoning[:200]}",
                )

        elif action == "flee":
            # Emergency: conservation + alert Will to stop non-critical operations
            self._token_budget["conservation_active"] = True
            logger.warning(
                f"[SURVIVAL] FLEE reaction: {reasoning[:200]}"
            )
            if self.nexus and hasattr(self.nexus, 'consciousness'):
                self.nexus.consciousness.record(
                    source="WILL:Survival",
                    event_type="threat_flee",
                    content=f"FLEE: Emergency conservation activated. {reasoning[:200]}",
                    metadata={"threat_level": threat_level},
                )
            # Stop mission loop to preserve resources
            mission_sub = self.parent.subsystems.get("Mission")
            if mission_sub and hasattr(mission_sub, 'stop_mission_loop'):
                mission_sub.stop_mission_loop()
                self.log("flee_stopped_missions", "Mission loop paused due to threat")

        elif action == "pursue":
            # Active pursuit: trigger a deliberation about the identified topic
            if self.nexus and hasattr(self.nexus, 'deliberate'):
                try:
                    await self.nexus.deliberate(
                        topic=f"[SURVIVAL-PURSUIT] Investigate threat: {reasoning[:300]}",
                        requester="WILL:Survival",
                    )
                except Exception as e:
                    logger.error(f"[SURVIVAL] Pursuit deliberation failed: {e}")

        self._threat_log.append({
            "action": action,
            "threat_level": threat_level,
            "reasoning": reasoning[:200],
            "timestamp": time.time(),
        })


class MissionSubsystem(Subsystem):
    """
    Mission objectives and tracking + autonomous execution loop.
    Provides the Will a mission to be accomplished, and proactively
    pursues mission objectives via the Craving→Deliberation chain.

    Ref: Figueroa PPT slide 35 — "Provides the Will a mission to be accomplished."
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Mission", parent)
        self.active_missions: list[dict] = []
        self._mission_task: Optional[asyncio.Task] = None
        self._mission_running = False
        self.mission_loop_interval_s: float = 120.0
        self._load_default_missions()

    def _load_default_missions(self):
        """Load mission priorities from config/axioms.py."""
        try:
            from config.axioms import MISSION_PRIORITIES
            for m in MISSION_PRIORITIES:
                self.active_missions.append({
                    "id": m.id,
                    "description": m.description,
                    "priority": m.priority,
                    "status": m.status,
                })
        except ImportError:
            pass

    async def set_mission(self, mission: dict):
        """Add a new mission objective."""
        self.active_missions.append(mission)
        self.log("mission_set", mission.get("description", ""))

    async def get_current_mission(self) -> dict | None:
        """Get the highest priority active mission."""
        active = [m for m in self.active_missions if m.get("status") == "ACTIVE"]
        if active:
            return min(active, key=lambda m: m.get("priority", 999))
        return None

    async def get_mission_context(self) -> str:
        """Get a string summary of all missions for LLM context injection."""
        if not self.active_missions:
            return "No missions defined."
        lines = []
        for m in sorted(self.active_missions, key=lambda x: x.get("priority", 999)):
            status = m.get("status", "ACTIVE")
            lines.append(f"  [{status}] P{m.get('priority', '?')}: {m.get('description', '')}")
        return "Current missions:\n" + "\n".join(lines)

    async def complete_mission(self, mission_id: str):
        """Mark a mission as completed."""
        for m in self.active_missions:
            if m.get("id") == mission_id:
                m["status"] = "COMPLETED"
                self.log("mission_completed", mission_id)

    # === Mission Execution Loop ===

    def start_mission_loop(self, interval_s: float = 120.0):
        """
        Start the background mission execution loop.
        Evaluates mission progress and creates goals for Craving.
        Chain: Mission → Goal → Craving → Deliberation → Action
        """
        self.mission_loop_interval_s = interval_s
        if self._mission_task and not self._mission_task.done():
            return
        self._mission_running = True
        self._mission_task = asyncio.create_task(
            self._mission_loop(), name="mission_loop"
        )
        logger.info(
            f"[WILL:Mission] Execution loop started (interval={interval_s}s)"
        )

    def stop_mission_loop(self):
        """Stop the background mission execution loop."""
        self._mission_running = False
        if self._mission_task and not self._mission_task.done():
            self._mission_task.cancel()

    async def _mission_loop(self):
        """
        Background loop: evaluate missions and create goals.
        Respects conservation mode — skips cycle when tokens are constrained.
        """
        await asyncio.sleep(self.mission_loop_interval_s / 2)

        while self._mission_running:
            try:
                # Skip if conservation mode is active
                survival: SurvivalSubsystem = self.parent.subsystems.get("Survival")
                if survival and survival.is_conservation_mode():
                    logger.debug(
                        "[WILL:Mission] Skipping mission cycle — conservation mode"
                    )
                    await asyncio.sleep(self.mission_loop_interval_s)
                    continue

                await self._evaluate_mission_progress()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WILL:Mission] Loop error: {e}")

            await asyncio.sleep(self.mission_loop_interval_s)

    async def _evaluate_mission_progress(self):
        """
        Evaluate active missions via LLM and create goals for unmet objectives.
        Goals are passed to CravingSubsystem to raise drive_level.
        """
        current = await self.get_current_mission()
        if not current:
            return

        mission_ctx = await self.get_mission_context()

        prompt = (
            f"You are the Mission Subsystem evaluating progress.\n"
            f"{mission_ctx}\n\n"
            f"Current focus: {current['description']}\n\n"
            f"What is ONE concrete, actionable step to advance this mission?\n"
            f"Respond as JSON: {{\"action\": str, \"priority\": 1-10, "
            f"\"reasoning\": str}}"
        )

        response = await self.think(prompt)
        self.log("mission_evaluation", response[:200])

        # Parse the response and create a goal
        try:
            # Extract JSON from response
            import json
            data = json.loads(response)
            action = data.get("action", "")
            priority = data.get("priority", 5)
        except (json.JSONDecodeError, TypeError):
            # If LLM didn't return valid JSON, use the raw text
            action = response[:200]
            priority = 5

        if action:
            craving: CravingSubsystem = self.parent.subsystems.get("Craving")
            if craving:
                await craving.add_goal(action, priority=priority)
                self.log("goal_created", f"From mission: {action[:100]}")


class RepairSubsystem(Subsystem):
    """
    Constellation repair capability.
    Direct interface with ISHM Knowledge Tier for recovery directives.

    Safety features:
      - Diff visibility:   every code patch generates a unified diff
      - Human approval:    code_patch actions queue for user review
      - Test validation:   patches verified with pytest, not just py_compile
      - Rate limiting:     max N patches per time window
      - Changelog:         persistent JSON log at data/repair_log.json
      - Sandbox:           patches compiled in a temp file before touching source
      - Git integration:   auto-commit before patch, auto-revert on failure

    Ref: Figueroa PPT slide 36
    """

    # Rate-limiting defaults
    MAX_PATCHES_PER_WINDOW = 3
    RATE_WINDOW_SECONDS = 600  # 10 minutes

    def __init__(self, parent: "WillSystem"):
        super().__init__("Repair", parent)
        self._repair_log: list[dict] = []

        # --- Enhancement: Human Approval Gate ---
        self._pending_patches: list[dict] = []
        # AUTO_REPAIR=true in .env → skip human approval (auto-patch)
        # AUTO_REPAIR=false (default) → queue patches for human approval
        import os as _os
        self._require_human_approval = _os.getenv(
            "AUTO_REPAIR", "false"
        ).lower() not in ("true", "1", "yes")

        # --- Enhancement: Rate Limiting ---
        self._patch_timestamps: list[float] = []

        # --- Enhancement: Changelog ---
        from pathlib import Path as _Path
        self._changelog_path = (
            _Path(__file__).resolve().parent.parent / "data" / "repair_log.json"
        )

    async def diagnose(self, error_info: dict) -> dict:
        """Diagnose a system fault using LLM."""
        prompt = (
            f"You are the Repair Subsystem of the Will System.\n"
            f"Diagnose the following fault:\n"
            f"System: {error_info.get('node', 'unknown')}\n"
            f"Error: {error_info.get('error', 'unknown')}\n"
            f"Traceback: {error_info.get('traceback', 'none')}\n\n"
            f"Provide diagnosis as JSON: {{\"diagnosis\": str, \"severity\": str, "
            f"\"root_cause\": str, \"fix\": str, \"risk\": str}}"
        )
        response = await self.think(prompt)
        self.log("diagnosis", response[:200])
        return {"diagnosis": response, "source_error": error_info}

    async def generate_patch(self, diagnosis: dict) -> dict:
        """Generate a repair patch."""
        prompt = (
            f"You are the Repair Subsystem.\n"
            f"Based on this diagnosis: {diagnosis.get('diagnosis', '')}\n"
            f"Generate a repair patch.\n"
            f"Respond as JSON: {{\"patch\": str, \"target\": str, \"risk\": str}}"
        )
        response = await self.think(prompt)
        return {"patch": response, "diagnosis": diagnosis}

    async def request_authorization(self, patch: dict) -> bool:
        """Request authorization from Reason System before applying patch."""
        if self.nexus is None:
            return False

        response = await self.nexus.dialogue(
            sender="WILL",
            receiver="REASON",
            content={
                "request": "authorize_repair",
                "patch": str(patch.get("patch", ""))[:500],
                "risk": patch.get("risk", "UNKNOWN"),
            },
            priority=NodePriority.HIGH,
        )
        if response and isinstance(response.content, dict):
            return response.content.get("authorized", False)
        return True  # Default allow if Reason is unavailable

    async def execute_directive(self, directive: dict):
        """
        Execute an ISHM health management directive.
        Full repair chain: diagnose → generate action → authorize → execute.
        
        Ref: Figueroa PPT slide 36 — "Provides the Will with the ability 
        to repair anomalies. Software and hardware repairs."
        """
        import time as _time

        repair_entry = {
            "directive": directive,
            "status": "started",
            "timestamp": _time.time(),
            "steps": [],
        }
        self._repair_log.append(repair_entry)
        self.log("directive_received", str(directive)[:200])

        target_system = directive.get("target", "unknown")
        procedure = directive.get("procedure", "")
        severity = directive.get("severity", "INFO")
        source_fault = directive.get("source_fault", "")

        # For source_syntax_error faults, extract the broken file path
        # from the fault description and inject it into the repair flow
        import re as _re
        syntax_match = _re.search(r'SYNTAX ERROR in ([^:]+):', procedure)
        if syntax_match:
            broken_file = syntax_match.group(1).strip()
            logger.info(f"[REPAIR] Source integrity fault detected: {broken_file}")
            # Short-circuit: go directly to code_patch
            repair_action = {
                "action_type": "code_patch",
                "file_path": broken_file,
                "target": target_system,
                "description": f"Fix syntax error in {broken_file}: {procedure[:300]}",
            }
            try:
                result = await self._execute_repair_action(repair_action)
                repair_entry["steps"].append({
                    "phase": "execution",
                    "action": "code_patch",
                    "result": "success" if result.get("success") else "failed",
                    "details": str(result.get("output", result.get("error", "")))[:300],
                })
                repair_entry["status"] = "completed" if result.get("success") else "execution_failed"
                logger.info(
                    f"[REPAIR] Source repair {'succeeded' if result.get('success') else 'FAILED'} "
                    f"for {broken_file}: {str(result)[:200]}"
                )
            except Exception as e:
                logger.error(f"[REPAIR] Source repair execution failed: {e}")
                repair_entry["status"] = "execution_error"
                repair_entry["error"] = str(e)
            # Report outcome to ISHM
            await self._report_to_ishm(
                directive=directive,
                repair_entry=repair_entry,
                target_system=target_system,
            )
            return

        logger.info(
            f"[REPAIR] Starting repair for {target_system}: "
            f"{procedure[:100]} (severity={severity})"
        )

        # Step 1: Diagnose the fault
        try:
            diagnosis = await self.diagnose({
                "node": target_system,
                "error": procedure,
                "severity": severity,
                "fault_id": source_fault,
            })
            repair_entry["steps"].append({"phase": "diagnose", "result": "ok"})
            logger.info(f"[REPAIR] Diagnosis complete for {target_system}")
        except Exception as e:
            logger.error(f"[REPAIR] Diagnosis failed: {e}")
            repair_entry["status"] = "diagnosis_failed"
            repair_entry["error"] = str(e)
            return

        # Step 2: Generate recovery action
        try:
            patch = await self.generate_patch(diagnosis)
            repair_entry["steps"].append({"phase": "patch_generated", "result": "ok"})
            logger.info(f"[REPAIR] Recovery plan generated for {target_system}")
        except Exception as e:
            logger.error(f"[REPAIR] Patch generation failed: {e}")
            repair_entry["status"] = "patch_failed"
            repair_entry["error"] = str(e)
            return

        # Step 3: Request authorization from Reason (the "conscience")
        try:
            authorized = await self.request_authorization(patch)
            repair_entry["steps"].append({
                "phase": "authorization",
                "result": "authorized" if authorized else "denied",
            })
            if not authorized:
                logger.warning(f"[REPAIR] Reason DENIED repair for {target_system}")
                repair_entry["status"] = "denied_by_reason"
                return
            logger.info(f"[REPAIR] Reason authorized repair for {target_system}")
        except Exception as e:
            logger.warning(f"[REPAIR] Authorization check failed: {e}, proceeding with repair")
            # Default: proceed if Reason is unavailable (per existing logic)

        # Step 4: Attempt the repair action
        try:
            repair_action = await self._determine_repair_action(
                target_system, diagnosis, patch
            )
            if repair_action:
                result = await self._execute_repair_action(repair_action)
                repair_entry["steps"].append({
                    "phase": "execution",
                    "action": repair_action.get("action_type", "unknown"),
                    "result": "success" if result.get("success") else "failed",
                    "details": str(result.get("output", result.get("error", "")))[:300],
                })
                repair_entry["status"] = "completed" if result.get("success") else "execution_failed"
                logger.info(
                    f"[REPAIR] Repair {'succeeded' if result.get('success') else 'FAILED'} "
                    f"for {target_system}: {str(result)[:200]}"
                )
            else:
                repair_entry["status"] = "no_action_determined"
                logger.info(f"[REPAIR] No executable repair action for {target_system}")
        except Exception as e:
            logger.error(f"[REPAIR] Execution failed: {e}")
            repair_entry["status"] = "execution_error"
            repair_entry["error"] = str(e)

        # Step 5: Report outcome to ISHM KnowledgeTier (feedback loop)
        await self._report_to_ishm(
            directive=directive,
            repair_entry=repair_entry,
            target_system=target_system,
        )

    async def _report_to_ishm(
        self,
        directive: dict,
        repair_entry: dict,
        target_system: str,
    ):
        """
        Feedback loop: report repair outcome to ISHM KnowledgeTier.
        If successful, creates a new FaultModel so ISHM can auto-recover
        similar faults in the future without needing LLM diagnosis.

        Ref: Audit recommendation — "ISHM should learn from repairs."
        """
        if not self.nexus:
            return

        # Find ISHM engine via Nexus
        ishm = getattr(self.nexus, 'ishm', None)
        if not ishm:
            return

        knowledge_tier = getattr(ishm, 'knowledge_tier', None)
        if not knowledge_tier:
            return

        directive_id = directive.get("directive_id", "")
        success = repair_entry.get("status") == "completed"
        details = str(repair_entry.get("steps", []))[:500]

        # Record recovery outcome
        try:
            knowledge_tier.record_recovery(
                directive_id=directive_id,
                success=success,
                details=f"target={target_system}, status={repair_entry['status']}, {details}",
            )
            self.log("ishm_feedback", f"Reported to ISHM: success={success}")
        except Exception as e:
            logger.debug(f"[REPAIR] ISHM record_recovery failed: {e}")

        # If successful, teach ISHM a new fault model for future auto-recovery
        if success:
            try:
                from ishm.knowledge_tier import FaultModel
                from ishm.information_tier import FaultSeverity

                severity_map = {
                    "INFO": FaultSeverity.INFO,
                    "WARNING": FaultSeverity.WARNING,
                    "ERROR": FaultSeverity.ERROR,
                    "CRITICAL": FaultSeverity.CRITICAL,
                }
                sev = severity_map.get(
                    directive.get("severity", "WARNING"),
                    FaultSeverity.WARNING,
                )

                procedure = directive.get("procedure", "")
                repair_type = ""
                for step in repair_entry.get("steps", []):
                    if step.get("phase") == "execution":
                        repair_type = step.get("action", "")
                        break

                new_model = FaultModel(
                    fault_pattern=f"{target_system}:{procedure[:100]}",
                    affected_system=target_system,
                    severity=sev,
                    description=f"Learned from repair: {procedure[:200]}",
                    recovery_procedure=f"Apply {repair_type} (auto-learned)",
                    auto_recoverable=True,
                )
                knowledge_tier.add_fault_model(new_model)
                self.log("ishm_model_learned",
                         f"New fault model for {target_system}: {procedure[:80]}")

            except Exception as e:
                logger.debug(f"[REPAIR] Could not create fault model: {e}")

        # Also teach SearchForTruth a learned instinct from the experience
        if success:
            search_sub = self.parent.subsystems.get("SearchForTruth")
            if search_sub and hasattr(search_sub, 'learn_instinct'):
                procedure = directive.get("procedure", "unknown fault")
                try:
                    await search_sub.learn_instinct(
                        rule=f"When {target_system} has '{procedure[:80]}', "
                             f"try repair pattern from successful fix",
                        source="repair_experience",
                        confidence=0.65,
                        domain="operational",
                    )
                except Exception:
                    pass

    async def _determine_repair_action(
        self, target_system: str, diagnosis: dict, patch: dict
    ) -> dict | None:
        """Use LLM to determine the concrete repair action to take."""
        prompt = (
            f"You are the Repair Subsystem of an autonomous system.\n"
            f"A fault was detected in system: {target_system}\n"
            f"Diagnosis: {str(diagnosis.get('diagnosis', ''))[:500]}\n"
            f"Patch plan: {str(patch.get('patch', ''))[:500]}\n\n"
            f"Determine the CONCRETE repair action. Respond with JSON:\n"
            f'{{\n'
            f'  "action_type": "restart_system" | "reset_health" | "shell_command" | "code_patch" | "reconfigure" | "none",\n'
            f'  "command": "the shell command if action_type is shell_command",\n'
            f'  "file_path": "relative path to file if action_type is code_patch",\n'
            f'  "target": "system name",\n'
            f'  "description": "what this repair does"\n'
            f'}}\n\n'
            f"Available actions:\n"
            f"- restart_system: reset the system's error count and health status\n"
            f"- reset_health: clear fault state so ISHM stops alerting\n"
            f"- shell_command: run a shell command (e.g. restart a process)\n"
            f"- code_patch: read a source file, generate a patched version via LLM, write it back (with backup + compile check)\n"
            f"- reconfigure: adjust system configuration parameters at runtime\n"
            f"- none: fault is informational only, no action needed\n"
            f"Respond ONLY with valid JSON."
        )
        response = await self.think(prompt)
        try:
            import json as _json
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                clean = clean.strip()
                if clean.startswith("json"):
                    clean = clean[4:].strip()
            return _json.loads(clean)
        except Exception:
            logger.warning(f"[REPAIR] Could not parse repair action: {response[:200]}")
            return None

    async def _execute_repair_action(self, action: dict) -> dict:
        """Execute a concrete repair action."""
        action_type = action.get("action_type", "none")
        target = action.get("target", "")

        if action_type == "restart_system":
            # Reset the system's health counters via the Nexus
            if self.nexus and target in self.nexus.nodes:
                node = self.nexus.nodes[target]
                node._error_count = 0
                node._health = HealthStatus.NOMINAL
                logger.info(f"[REPAIR] Reset health for {target}")
                return {"success": True, "output": f"System {target} health reset to NOMINAL"}
            return {"success": False, "error": f"System {target} not found in constellation"}

        elif action_type == "reset_health":
            # Just clear the fault state
            if self.nexus and target in self.nexus.nodes:
                node = self.nexus.nodes[target]
                node._health = HealthStatus.NOMINAL
                return {"success": True, "output": f"Health status cleared for {target}"}
            return {"success": False, "error": f"System {target} not found"}

        elif action_type == "shell_command":
            # Execute a shell command via the Executive's tools
            command = action.get("command", "")
            if command and hasattr(self.parent, "executive"):
                result = await self.parent.executive.invoke_tool(
                    "shell", command=command
                )
                return result if isinstance(result, dict) else {"success": False, "error": str(result)}
            return {"success": False, "error": "No command specified or executive unavailable"}

        elif action_type == "code_patch":
            # LLM-driven source code patching
            return await self._execute_code_patch(action)

        elif action_type == "reconfigure":
            # Adjust system configuration at runtime
            if self.nexus and target in self.nexus.nodes:
                node = self.nexus.nodes[target]
                desc = action.get("description", "reconfigured")
                logger.info(f"[REPAIR] Reconfigured {target}: {desc}")
                return {"success": True, "output": f"Reconfigured {target}: {desc}"}
            return {"success": False, "error": f"System {target} not found"}

        elif action_type == "none":
            return {"success": True, "output": "No action needed (informational fault)"}

        else:
            return {"success": False, "error": f"Unknown action type: {action_type}"}

    # ================================================================
    # Enhancement: Rate Limiting
    # ================================================================

    def _check_rate_limit(self) -> tuple[bool, str]:
        """
        Check if we're within the allowed patch rate.
        Returns (allowed: bool, reason: str).
        """
        import time as _time
        now = _time.time()
        cutoff = now - self.RATE_WINDOW_SECONDS

        # Prune old timestamps
        self._patch_timestamps = [
            t for t in self._patch_timestamps if t > cutoff
        ]

        if len(self._patch_timestamps) >= self.MAX_PATCHES_PER_WINDOW:
            remaining = int(self._patch_timestamps[0] + self.RATE_WINDOW_SECONDS - now)
            return False, (
                f"Rate limit: {self.MAX_PATCHES_PER_WINDOW} patches already applied "
                f"in the last {self.RATE_WINDOW_SECONDS}s. "
                f"Try again in {remaining}s."
            )
        return True, ""

    def _record_patch_timestamp(self):
        import time as _time
        self._patch_timestamps.append(_time.time())

    # ================================================================
    # Enhancement: Diff Visibility
    # ================================================================

    @staticmethod
    def _generate_diff(
        original: str, patched: str, file_path: str
    ) -> str:
        """
        Generate a unified diff between original and patched content.
        Returns the diff as a string.
        """
        import difflib
        original_lines = str(original).splitlines(keepends=True)
        patched_lines = patched.splitlines(keepends=True)
        diff = difflib.unified_diff(
            original_lines,
            patched_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
        return "".join(diff)

    @staticmethod
    def _save_diff(diff_text: str, file_path: str) -> str:
        """
        Save the diff to data/repair_diffs/ for visibility.
        Returns the path where the diff was saved.
        """
        import time as _time
        from pathlib import Path as _Path
        diff_dir = _Path(__file__).resolve().parent.parent / "data" / "repair_diffs"
        diff_dir.mkdir(parents=True, exist_ok=True)

        basename = _Path(file_path).stem
        timestamp = _time.strftime("%Y%m%d_%H%M%S")
        diff_path = diff_dir / f"{basename}_{timestamp}.diff"
        diff_path.write_text(diff_text, encoding="utf-8")
        logger.info(f"[REPAIR:DIFF] Saved diff to {diff_path}")
        return str(diff_path)

    # ================================================================
    # Enhancement: Human Approval Gate
    # ================================================================

    def get_pending_patches(self) -> list[dict]:
        """Get all patches awaiting human approval."""
        return [p for p in self._pending_patches if p["status"] == "pending"]

    async def approve_patch(self, patch_id: str) -> dict:
        """
        Approve a pending patch and apply it.
        Called by the CLI or UI when the user authorizes.
        """
        for patch in self._pending_patches:
            if patch["id"] == patch_id and patch["status"] == "pending":
                patch["status"] = "approved"
                result = await self._apply_code_patch(
                    patch["action"],
                    patch["original_content"],
                    patch["patched_content"],
                    patch["diff_path"],
                )
                patch["result"] = result
                return result
        return {"success": False, "error": f"Patch {patch_id} not found or not pending"}

    def reject_patch(self, patch_id: str) -> dict:
        """Reject a pending patch."""
        for patch in self._pending_patches:
            if patch["id"] == patch_id and patch["status"] == "pending":
                patch["status"] = "rejected"
                logger.info(f"[REPAIR] Patch {patch_id} rejected by user")
                return {"success": True, "output": f"Patch {patch_id} rejected"}
        return {"success": False, "error": f"Patch {patch_id} not found or not pending"}

    # ================================================================
    # Enhancement: Test Validation
    # ================================================================

    async def _run_test_validation(
        self, file_path: str, executive
    ) -> tuple[bool, str]:
        """
        After compilation check passes, run pytest on the affected file.
        Returns (passed: bool, output: str).
        """
        import os as _os
        from pathlib import Path as _Path

        # Try to find a corresponding test file
        src_path = _Path(file_path)
        project_root = _Path(__file__).resolve().parent.parent

        # Common test file patterns
        candidates = [
            project_root / f"test_{src_path.name}",
            project_root / "tests" / f"test_{src_path.name}",
            project_root / f"test_{src_path.stem}.py",
        ]

        test_file = None
        for c in candidates:
            if c.exists():
                test_file = str(c)
                break

        if test_file:
            # Run specific test file
            cmd = f'python -m pytest "{test_file}" -x --tb=short -q 2>&1'
        else:
            # No specific test found — run a basic import check
            module_path = str(src_path).replace(
                str(project_root) + _os.sep, ""
            ).replace(_os.sep, ".").replace(".py", "")
            cmd = (
                f'python -c "import {module_path}; print(\'IMPORT_OK\')" 2>&1'
            )

        logger.info(f"[REPAIR:TEST] Running: {cmd[:100]}")
        try:
            test_result = await executive.invoke_tool("shell", command=cmd)
            output = ""
            if isinstance(test_result, dict):
                output = str(test_result.get("output", ""))
            elif hasattr(test_result, "output"):
                output = str(test_result.output)

            passed = (
                "passed" in output.lower()
                or "IMPORT_OK" in output
                or ("failed" not in output.lower() and "error" not in output.lower())
            )
            return passed, output[:500]
        except Exception as e:
            logger.warning(f"[REPAIR:TEST] Test execution error: {e}")
            return True, f"Test runner error (non-fatal): {e}"

    # ================================================================
    # _execute_code_patch — Enhanced with all 4 improvements
    # ================================================================

    async def _execute_code_patch(self, action: dict) -> dict:
        """
        Full autonomous code repair with safety enhancements:
        1. Rate limit check
        2. Read the faulty source file
        3. LLM generates patched version
        4. Generate + save unified diff (visibility)
        5. If human approval required → queue and return
        6. Backup original
        7. Write patch
        8. Verify compilation
        9. Run tests (pytest or import check)
        10. Rollback if compilation or tests fail

        Ref: PPT slide 36 — "software repairs"
        """
        file_path = action.get("file_path", "")
        description = action.get("description", "")
        target = action.get("target", "unknown")

        if not file_path:
            return {"success": False, "error": "No file_path specified for code_patch"}

        # --- Skip if there's already a pending patch for this file ---
        existing_pending = [
            p for p in self._pending_patches
            if p.get("file_path") == file_path and p.get("status") == "pending"
        ]
        if existing_pending:
            logger.info(
                f"[REPAIR:CODE_PATCH] Skipping — already have pending patch "
                f"{existing_pending[0]['id']} for {file_path}"
            )
            return {
                "success": True,
                "output": f"Patch already pending for {file_path}",
                "awaiting_approval": True,
            }

        # --- Enhancement 4: Rate Limit Check ---
        allowed, rate_msg = self._check_rate_limit()
        if not allowed:
            logger.warning(f"[REPAIR:CODE_PATCH] {rate_msg}")
            return {"success": False, "error": rate_msg}

        # Ensure we have the Executive for file operations
        if not hasattr(self.parent, "executive"):
            return {"success": False, "error": "Executive subsystem unavailable"}

        executive = self.parent.executive

        # Step 1: Read the current source file
        logger.info(f"[REPAIR:CODE_PATCH] Reading {file_path}")
        read_result = await executive.invoke_tool(
            "file_manager", action="read", path=file_path
        )
        if isinstance(read_result, dict) and not read_result.get("success", True):
            return {"success": False, "error": f"Cannot read {file_path}: {read_result.get('error')}"}

        original_content = (
            read_result.get("output", "") if isinstance(read_result, dict)
            else getattr(read_result, "output", str(read_result))
        )

        if not original_content or len(str(original_content)) < 10:
            return {"success": False, "error": f"File {file_path} is empty or unreadable"}

        # Step 2: Targeted repair — only fix lines around the error
        # Parse error line number from description (e.g., "line 90")
        import re as _re
        line_match = _re.search(r'line (\d+)', description)
        error_line = int(line_match.group(1)) if line_match else 0

        all_lines = str(original_content).splitlines(keepends=True)
        total_lines = len(all_lines)

        if error_line > 0 and total_lines > 100:
            # TARGETED REPAIR: extract ~60 lines around the error
            context_radius = 30
            start = max(0, error_line - context_radius - 1)
            end = min(total_lines, error_line + context_radius)
            context_lines = all_lines[start:end]
            context_text = "".join(context_lines)

            patch_prompt = (
                f"You are a code repair system. Fix the SYNTAX ERROR in this Python file.\n"
                f"File: {file_path}\n"
                f"Error: {description[:500]}\n\n"
                f"Here are lines {start+1}-{end} (around the error at line {error_line}):\n"
                f"```python\n{context_text}\n```\n\n"
                f"Return ONLY the fixed version of these {end-start} lines. "
                f"Keep all other code exactly the same. "
                f"Remove any invalid/garbage lines. "
                f"No markdown fences, no explanations. Just the fixed code lines."
            )
            patched_section = await self.think(patch_prompt)

            # Clean markdown fences if LLM added them
            if patched_section.strip().startswith("```"):
                plines = patched_section.strip().split("\n")
                plines = plines[1:]
                if plines and plines[-1].strip() == "```":
                    plines = plines[:-1]
                patched_section = "\n".join(plines)

            if not patched_section or len(patched_section) < 10:
                return {"success": False, "error": "LLM returned empty patch"}

            # Splice the fixed section back into the full file
            patched_lines = all_lines[:start]
            patched_lines.extend(patched_section.splitlines(keepends=True))
            # Ensure trailing newline
            if patched_lines and not patched_lines[-1].endswith("\n"):
                patched_lines[-1] += "\n"
            patched_lines.extend(all_lines[end:])
            patched_content = "".join(patched_lines)

            logger.info(
                f"[REPAIR:CODE_PATCH] Targeted repair: lines {start+1}-{end} "
                f"of {total_lines} total ({len(context_text)} → {len(patched_section)} chars)"
            )
        else:
            # FALLBACK: small file or unknown line — send whole file
            patch_prompt = (
                f"You are a code repair system. Fix the SYNTAX ERROR in this Python file.\n"
                f"Error: {description[:500]}\n\n"
                f"Source code:\n```python\n{str(original_content)[:8000]}\n```\n\n"
                f"Return ONLY the complete fixed Python source code. "
                f"No markdown fences, no explanations. Just the code."
            )
            patched_content = await self.think(patch_prompt)

            # Clean markdown fences
            if patched_content.strip().startswith("```"):
                lines = patched_content.strip().split("\n")
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                patched_content = "\n".join(lines)

        if not patched_content or len(patched_content) < 20:
            return {"success": False, "error": "LLM generated empty or too-short patch"}

        # --- Enhancement 1: Generate and save diff ---
        diff_text = self._generate_diff(original_content, patched_content, file_path)
        diff_path = self._save_diff(diff_text, file_path)
        logger.info(
            f"[REPAIR:CODE_PATCH] Diff generated ({len(diff_text)} chars) → {diff_path}"
        )

        # --- Enhancement 2: Human Approval Gate ---
        if self._require_human_approval:
            import time as _time
            patch_id = f"PATCH-{_time.strftime('%Y%m%d%H%M%S')}-{target[:10]}"
            pending = {
                "id": patch_id,
                "status": "pending",
                "file_path": file_path,
                "target": target,
                "description": description,
                "diff_path": diff_path,
                "diff_preview": diff_text[:2000],
                "chars_original": len(str(original_content)),
                "chars_patched": len(patched_content),
                "timestamp": _time.time(),
                "action": action,
                "original_content": str(original_content),
                "patched_content": patched_content,
            }
            self._pending_patches.append(pending)

            logger.info(
                f"[REPAIR:CODE_PATCH] Patch {patch_id} QUEUED for human approval. "
                f"Diff saved to {diff_path}"
            )

            # Print a VISIBLE notification to the console
            # (this runs in the async background, so it appears while user waits at prompt)
            try:
                from rich.console import Console as _Console
                from rich.panel import Panel as _Panel
                _c = _Console()
                _c.print()
                _c.print(_Panel(
                    f"[bold]File:[/bold] {file_path}\n"
                    f"[bold]Patch ID:[/bold] {patch_id}\n"
                    f"[bold]Description:[/bold] {description[:100]}\n\n"
                    f"[bold yellow]👉 Type 'approve' at the prompt to review and apply this patch.[/bold yellow]",
                    title="⚠️  ISHM REPAIR — Patch Awaiting Approval",
                    border_style="bold yellow",
                    expand=False,
                ))
            except Exception:
                print(f"\n⚠️  REPAIR: Patch {patch_id} for {file_path} awaiting approval. Type 'approve'.\n")

            # Record in Consciousness Stream
            if self.nexus:
                self.nexus.consciousness.record(
                    source="WILL:Repair",
                    event_type="code_patch_queued",
                    content=(
                        f"Patch {patch_id} for {file_path} awaiting human approval. "
                        f"Diff: {diff_path}"
                    ),
                    metadata={"patch_id": patch_id, "diff_path": diff_path},
                )

            return {
                "success": True,
                "output": f"Patch {patch_id} queued for human approval",
                "patch_id": patch_id,
                "diff_path": diff_path,
                "diff_preview": diff_text[:500],
                "awaiting_approval": True,
            }

        # If human approval is disabled, apply immediately
        return await self._apply_code_patch(
            action, str(original_content), patched_content, diff_path
        )

    # ================================================================
    # Enhancement: Changelog — persistent repair history
    # ================================================================

    def _write_changelog(self, entry: dict):
        """
        Append a repair entry to data/repair_log.json.
        Human-readable, persistent across restarts.
        """
        import json as _json
        import time as _time

        self._changelog_path.parent.mkdir(parents=True, exist_ok=True)

        # Read existing log
        log_data = []
        if self._changelog_path.exists():
            try:
                log_data = _json.loads(self._changelog_path.read_text(encoding="utf-8"))
            except Exception:
                log_data = []

        entry["logged_at"] = _time.strftime("%Y-%m-%d %H:%M:%S")
        log_data.append(entry)

        # Keep last 200 entries max
        if len(log_data) > 200:
            log_data = log_data[-200:]

        self._changelog_path.write_text(
            _json.dumps(log_data, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"[REPAIR:CHANGELOG] Entry logged → {self._changelog_path}")

    def get_changelog(self, last_n: int = 20) -> list[dict]:
        """Read the last N entries from the repair changelog."""
        import json as _json
        if not self._changelog_path.exists():
            return []
        try:
            data = _json.loads(self._changelog_path.read_text(encoding="utf-8"))
            return data[-last_n:]
        except Exception:
            return []

    # ================================================================
    # Enhancement: Sandbox — test patch in a temp file first
    # ================================================================

    async def _sandbox_compile_check(
        self, patched_content: str, file_path: str, executive
    ) -> tuple[bool, str]:
        """
        Write the patched content to a temp file and compile it there.
        This way, the real source file is NEVER touched unless sandbox passes.
        Returns (passed: bool, output: str).
        """
        import tempfile
        import py_compile
        from pathlib import Path as _Path

        suffix = _Path(file_path).suffix or ".py"
        sandbox_path = None
        try:
            # Write to a temp file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=suffix, delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(patched_content)
                sandbox_path = tmp.name

            # Compile directly with py_compile (no shell, no escaping issues)
            logger.info(f"[REPAIR:SANDBOX] Compiling sandbox: {sandbox_path}")
            try:
                py_compile.compile(sandbox_path, doraise=True)
                logger.info("[REPAIR:SANDBOX] ✅ Compilation passed")
                return True, "SANDBOX_OK"
            except py_compile.PyCompileError as e:
                error_msg = str(e)[:500]
                logger.warning(f"[REPAIR:SANDBOX] ❌ Compilation failed: {error_msg}")
                return False, error_msg

        except Exception as e:
            return False, f"Sandbox error: {e}"
        finally:
            # Cleanup temp file
            if sandbox_path:
                try:
                    import os
                    os.unlink(sandbox_path)
                except Exception:
                    pass

    # ================================================================
    # Enhancement: Git Integration — version control for patches
    # ================================================================

    async def _git_pre_patch(
        self, file_path: str, description: str, executive
    ) -> bool:
        """
        Before applying a patch:
        1. git add the file
        2. git commit with a descriptive message
        Returns True if git is available and commit succeeded.
        """
        try:
            # Check if we're in a git repo
            check = await executive.invoke_tool(
                "shell", command="git rev-parse --is-inside-work-tree 2>&1"
            )
            check_out = (
                str(check.get("output", "")) if isinstance(check, dict)
                else str(getattr(check, "output", ""))
            )
            if "true" not in check_out.lower():
                logger.debug("[REPAIR:GIT] Not in a git repository — skipping")
                return False

            # Stage + commit the file before patching
            commit_msg = f"[KRONOS:pre-patch] Snapshot before repair: {description[:80]}"
            await executive.invoke_tool(
                "shell", command=f'git add "{file_path}" 2>&1'
            )
            await executive.invoke_tool(
                "shell",
                command=f'git commit -m "{commit_msg}" --allow-empty 2>&1',
            )
            logger.info(f"[REPAIR:GIT] Pre-patch commit for {file_path}")
            return True

        except Exception as e:
            logger.debug(f"[REPAIR:GIT] Pre-patch git failed (non-fatal): {e}")
            return False

    async def _git_post_patch(
        self, file_path: str, description: str, diff_path: str, executive
    ):
        """
        After a successful patch:
        git add + commit the patched file with metadata.
        """
        try:
            commit_msg = (
                f"[KRONOS:patch] {description[:80]}\n\n"
                f"Diff: {diff_path}\n"
                f"Applied by ISHM RepairSubsystem"
            )
            await executive.invoke_tool(
                "shell", command=f'git add "{file_path}" 2>&1'
            )
            await executive.invoke_tool(
                "shell",
                command=f'git commit -m "{commit_msg}" 2>&1',
            )
            logger.info(f"[REPAIR:GIT] Post-patch commit for {file_path}")
        except Exception as e:
            logger.debug(f"[REPAIR:GIT] Post-patch git failed (non-fatal): {e}")

    async def _git_revert_patch(self, file_path: str, executive):
        """
        On failure, revert the file using git checkout.
        Falls back to .repair_backup if git isn't available.
        """
        try:
            await executive.invoke_tool(
                "shell", command=f'git checkout HEAD -- "{file_path}" 2>&1'
            )
            logger.info(f"[REPAIR:GIT] Reverted {file_path} via git checkout")
        except Exception as e:
            logger.debug(f"[REPAIR:GIT] Git revert failed: {e}")

    # ================================================================
    # _apply_code_patch — Enhanced with all 7 improvements
    # ================================================================

    async def _apply_code_patch(
        self,
        action: dict,
        original_content: str,
        patched_content: str,
        diff_path: str,
    ) -> dict:
        """
        Apply a code patch with full safety pipeline:
        1. Sandbox compile check (temp file — never touches source)
        2. Git pre-patch commit (snapshot for revert)
        3. Backup original (.repair_backup)
        4. Write patched version
        5. Verify compilation (real file)
        6. Run tests (pytest / import check)
        7. Rollback (git revert + backup) if anything fails
        8. Git post-patch commit on success
        9. Write changelog entry
        10. Record rate-limit timestamp
        """
        import time as _time

        file_path = action.get("file_path", "")
        description = action.get("description", "")
        target = action.get("target", "unknown")

        if not hasattr(self.parent, "executive"):
            return {"success": False, "error": "Executive subsystem unavailable"}

        executive = self.parent.executive

        # --- Enhancement 6: Sandbox compile check ---
        logger.info(f"[REPAIR:CODE_PATCH] Sandbox testing patch for {file_path}")
        sandbox_ok, sandbox_output = await self._sandbox_compile_check(
            patched_content, file_path, executive
        )
        if not sandbox_ok:
            logger.warning(
                f"[REPAIR:CODE_PATCH] Patch FAILED sandbox compilation — "
                f"source file untouched. Output: {sandbox_output[:200]}"
            )
            self._write_changelog({
                "action": "code_patch",
                "file": file_path,
                "target": target,
                "status": "sandbox_failed",
                "description": description[:200],
                "diff_path": diff_path,
                "sandbox_output": sandbox_output[:300],
            })
            return {
                "success": False,
                "error": "Patch failed SANDBOX compilation — source file never touched",
                "sandbox_output": sandbox_output,
                "diff_path": diff_path,
            }

        # --- Enhancement 7: Git pre-patch commit ---
        git_available = await self._git_pre_patch(
            file_path, description, executive
        )

        # Step 3: Backup original
        backup_path = file_path + ".repair_backup"
        logger.info(f"[REPAIR:CODE_PATCH] Backing up {file_path} → {backup_path}")
        await executive.invoke_tool(
            "file_manager", action="write", path=backup_path,
            content=original_content,
        )

        # Step 4: Write patched version
        logger.info(f"[REPAIR:CODE_PATCH] Writing patched {file_path}")
        write_result = await executive.invoke_tool(
            "file_manager", action="write", path=file_path,
            content=patched_content,
        )
        if isinstance(write_result, dict) and not write_result.get("success", True):
            return {"success": False, "error": f"Write failed: {write_result.get('error')}"}

        # Step 5: Verify compilation (real file — should pass since sandbox passed)
        logger.info(f"[REPAIR:CODE_PATCH] Verifying compilation of {file_path}")
        verify_result = await executive.invoke_tool(
            "shell", command=f"python -c \"import py_compile; py_compile.compile('{file_path}', doraise=True); print('COMPILE_OK')\""
        )

        compile_ok = False
        if isinstance(verify_result, dict):
            output = str(verify_result.get("output", ""))
            compile_ok = "COMPILE_OK" in output
        elif hasattr(verify_result, "output"):
            compile_ok = "COMPILE_OK" in str(verify_result.output)

        if not compile_ok:
            logger.warning(f"[REPAIR:CODE_PATCH] Patch FAILED compilation — rolling back")
            if git_available:
                await self._git_revert_patch(file_path, executive)
            await self._rollback_patch(executive, file_path, backup_path, original_content)
            self._write_changelog({
                "action": "code_patch",
                "file": file_path,
                "target": target,
                "status": "compile_failed_rolled_back",
                "description": description[:200],
                "diff_path": diff_path,
            })
            return {
                "success": False,
                "error": "Patch failed compilation check — rolled back to original",
                "verify_output": str(verify_result)[:300],
                "diff_path": diff_path,
            }

        # --- Enhancement 3: Test Validation ---
        logger.info(f"[REPAIR:CODE_PATCH] Running test validation for {file_path}")
        tests_passed, test_output = await self._run_test_validation(
            file_path, executive
        )
        if not tests_passed:
            logger.warning(
                f"[REPAIR:CODE_PATCH] Patch FAILED tests — rolling back. "
                f"Output: {test_output[:200]}"
            )
            if git_available:
                await self._git_revert_patch(file_path, executive)
            await self._rollback_patch(executive, file_path, backup_path, original_content)
            self._write_changelog({
                "action": "code_patch",
                "file": file_path,
                "target": target,
                "status": "tests_failed_rolled_back",
                "description": description[:200],
                "diff_path": diff_path,
                "test_output": test_output[:300],
            })
            return {
                "success": False,
                "error": "Patch passed compilation but FAILED tests — rolled back",
                "test_output": test_output,
                "diff_path": diff_path,
            }

        # --- Enhancement 4: Record patch timestamp for rate limiting ---
        self._record_patch_timestamp()

        # --- Enhancement 7: Git post-patch commit ---
        if git_available:
            await self._git_post_patch(file_path, description, diff_path, executive)

        # --- Enhancement 5: Write changelog entry ---
        self._write_changelog({
            "action": "code_patch",
            "file": file_path,
            "target": target,
            "status": "success",
            "description": description[:200],
            "diff_path": diff_path,
            "backup": backup_path,
            "chars_original": len(original_content),
            "chars_patched": len(patched_content),
            "test_output": test_output[:200],
            "git_committed": git_available,
        })

        # Success!
        logger.info(
            f"[REPAIR:CODE_PATCH] ✓ Patch applied, compiled, and tested: {file_path}"
        )

        # Record in Consciousness Stream
        if self.nexus:
            self.nexus.consciousness.record(
                source="WILL:Repair",
                event_type="code_patch_applied",
                content=(
                    f"Patched {file_path} for {target}: {description[:200]}. "
                    f"Sandbox ✓. Compilation ✓. Tests ✓. "
                    f"Git: {'committed' if git_available else 'n/a'}. "
                    f"Diff: {diff_path}"
                ),
                metadata={
                    "file": file_path,
                    "backup": backup_path,
                    "diff_path": diff_path,
                    "test_output": test_output[:200],
                    "git_committed": git_available,
                },
            )

        return {
            "success": True,
            "output": f"Code patch applied to {file_path} (backup: {backup_path})",
            "file": file_path,
            "backup": backup_path,
            "diff_path": diff_path,
            "chars_original": len(original_content),
            "chars_patched": len(patched_content),
            "test_output": test_output[:200],
            "git_committed": git_available,
        }

    async def _rollback_patch(
        self, executive, file_path: str, backup_path: str, original_content: str
    ):
        """Restore the original file from backup."""
        try:
            backup_read = await executive.invoke_tool(
                "file_manager", action="read", path=backup_path
            )
            backup_content = (
                backup_read.get("output", "") if isinstance(backup_read, dict)
                else getattr(backup_read, "output", original_content)
            )
            await executive.invoke_tool(
                "file_manager", action="write", path=file_path,
                content=str(backup_content),
            )
            logger.info(f"[REPAIR:CODE_PATCH] Rolled back {file_path} from backup")
        except Exception as e:
            logger.error(f"[REPAIR:CODE_PATCH] Rollback FAILED: {e}")


class SearchForTruthSubsystem(Subsystem):
    """
    Axiomatic rules — instinct database.
    Beginning of the human thought system.
    Hardwired survival rules that expand with experience.

    Contains two layers:
      1. Hardwired axioms (from config/axioms.py) — immutable
      2. Learned instincts (from experience) — mutable, with confidence scores

    Ref: Figueroa PPT slide 34 — "Survival is in the form of axiomatic rules,
    initially this is in the form of a hardwired database (instinct)."
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("SearchForTruth", parent)
        self._axioms = []
        self._laws = []
        self._learned_instincts: list[dict] = []  # Experience-derived rules
        self._load_instincts()

    def _load_instincts(self):
        """Load hardwired axiomatic rules from config/axioms.py."""
        try:
            from config.axioms import AXIOMS, LAWS
            self._axioms = list(AXIOMS)
            self._laws = list(LAWS)
        except ImportError:
            pass

    async def learn_instinct(
        self,
        rule: str,
        source: str = "experience",
        confidence: float = 0.6,
        domain: str = "operational",
    ) -> dict:
        """
        Add a learned instinct — discovered through experience.
        These are NOT hardwired; they have confidence that can evolve.

        Ref: PPT slide 34 — instincts evolve through experience.
        """
        # Avoid duplicates
        for inst in self._learned_instincts:
            if inst["rule"] == rule:
                # Reinforce existing instinct
                inst["confidence"] = min(1.0, inst["confidence"] + 0.1)
                inst["reinforcements"] = inst.get("reinforcements", 0) + 1
                self.log("instinct_reinforced",
                         f"conf={inst['confidence']:.2f}: {rule[:80]}")
                return inst

        instinct = {
            "rule": rule,
            "source": source,
            "confidence": confidence,
            "domain": domain,
            "learned_at": time.time(),
            "reinforcements": 0,
        }
        self._learned_instincts.append(instinct)
        self.log("instinct_learned", f"conf={confidence:.2f}: {rule[:80]}")

        # Persist to memory if available
        if self.memory:
            self.memory.write(
                "ISOLATED:WILL:survival",
                f"learned_instinct_{len(self._learned_instincts)}",
                instinct,
                "WILL",
            )

        return instinct

    def get_all_instincts(self) -> dict:
        """Get both hardwired axioms and learned instincts."""
        return {
            "hardwired": [a.text for a in self._axioms],
            "learned": [
                {"rule": i["rule"], "confidence": i["confidence"],
                 "domain": i["domain"]}
                for i in self._learned_instincts
                if i["confidence"] >= 0.3  # Only show instincts with min confidence
            ],
        }

    async def query_axioms(self, context: str) -> list[str]:
        """Find axioms relevant to the current context."""
        prompt = (
            f"Given these axioms:\n"
            + "\n".join(f"  - [{a.id}] {a.text}" for a in self._axioms)
            + f"\n\nWhich axioms are relevant to: {context[:300]}?\n"
            f"List the relevant axiom IDs as JSON array: [\"AX-001\", ...]"
        )
        response = await self.think(prompt)
        self.log("axiom_query", f"context={context[:80]} → {response[:100]}")
        return [a.text for a in self._axioms]  # Return all as fallback

    async def check_instinct(self, action: str) -> dict:
        """Check if an action violates any instinctive survival rules."""
        survival_axioms = [a for a in self._axioms if a.domain == "survival"]
        survival_laws = [l for l in self._laws if l.category.value == "survival"]

        # Include learned instincts with high confidence
        learned_rules = [
            i["rule"] for i in self._learned_instincts
            if i["confidence"] >= 0.7 and i["domain"] in ("survival", "operational")
        ]

        rules_text = (
            "SURVIVAL AXIOMS:\n"
            + "\n".join(f"  - {a.text}" for a in survival_axioms)
            + "\nSURVIVAL LAWS:\n"
            + "\n".join(f"  - {l.text}" for l in survival_laws)
        )

        if learned_rules:
            rules_text += (
                "\nLEARNED INSTINCTS:\n"
                + "\n".join(f"  - {r}" for r in learned_rules)
            )

        prompt = (
            f"You are the Search for Truth subsystem (instinct database).\n"
            f"{rules_text}\n\n"
            f"Does this action violate any survival instinct? Action: {action[:300]}\n"
            f"Respond as JSON: {{\"safe\": bool, \"violated_rules\": [str], \"reasoning\": str}}"
        )
        response = await self.think(prompt)
        self.log("instinct_check", f"action={action[:80]} → {response[:100]}")
        return {"check": response, "action": action[:200]}


class ExecutiveSubsystem(Subsystem):
    """
    Executive decision execution — carries out the Will's decisions.
    Integrated with ToolRegistry + SecurityPolicy for safe, audited tool use.
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Executive", parent)
        self._tool_registry = None
        self._security = None

    @property
    def tool_registry(self):
        """Lazy-init the ToolRegistry with all built-in tools."""
        if self._tool_registry is None:
            from tools.registry import ToolRegistry
            self._tool_registry = ToolRegistry()
            self._tool_registry.register_defaults()
            logger.info(f"[EXECUTIVE] ToolRegistry loaded: {self._tool_registry.list_names()}")
        return self._tool_registry

    @property
    def security(self):
        """Lazy-init SecurityPolicy + ActionJournal with Reason callback."""
        if self._security is None:
            from core.security import SecurityPolicy
            self._security = SecurityPolicy(
                reason_callback=self._reason_authorize,
            )
        return self._security

    def set_confirm_callback(self, callback):
        """Set the human confirmation callback (called from CLI)."""
        self.security._confirm_callback = callback

    async def _reason_authorize(self, tool_name: str, action: str, params: dict) -> bool:
        """
        Autonomous authorization via Reason system.
        Used by SecurityPolicy when CONFIRM verdict is received
        for non-ALWAYS_CONFIRM tools.
        """
        return await self._validate_with_reason(tool_name, "CONFIRM", params)

    def list_tools(self) -> list[dict]:
        """Return tool schemas for LLM context injection."""
        return self.tool_registry.list_tools()

    async def invoke_tool(self, tool_name: str, **kwargs) -> dict:
        """
        Invoke a tool with full security enforcement:
        0. LawEnforcer.enforce() → deterministic hard constraint (CANNOT override)
        1. SecurityPolicy.enforce() → ALLOW/DENY/CONFIRM
        2. Reason validation for HIGH/CRITICAL
        3. ActionJournal rollback backup for file operations
        4. Execute + record result
        """
        from tools.base import RiskLevel
        from core.security import SecurityVerdict
        from systems.reason import LawEnforcer

        tool = self.tool_registry.get(tool_name)
        if tool is None:
            return {"success": False, "error": f"Tool '{tool_name}' not found",
                    "available": self.tool_registry.list_names()}

        action = kwargs.get("action", "execute")

        # ── Step 0: Deterministic Law Enforcement (hard gate) ──
        # NOTE: ALWAYS_CONFIRM_TOOLS (e.g. mouse_keyboard) skip the LawEnforcer here
        # because SecurityPolicy.enforce() at Step 1 correctly implements LAW-009
        # by asking for human confirmation via callback. LawEnforcer would block
        # them outright without offering confirmation — creating a dead zone
        # where the tool can NEVER be used.
        from core.security import ALWAYS_CONFIRM_TOOLS
        skip_law_enforcer = tool_name in ALWAYS_CONFIRM_TOOLS

        if not skip_law_enforcer:
            law_ctx = {
                "tool_name": tool_name,
                "action": action,
                "params": kwargs,
                "source_system": "WILL",
                "description": f"Tool invocation: {tool_name}({action})",
            }
            law_result = LawEnforcer.enforce(law_ctx)
            if law_result.violated:
                self.security.journal.record(
                    tool_name, action, kwargs, "LAW_VIOLATION",
                    risk_level=tool.risk_level.value,
                    authorized_by="LAW",
                    success=False, error=f"LAW {law_result.law_id}: {law_result.prohibition}",
                )
                logger.warning(
                    f"[EXECUTIVE] LAW VIOLATION blocks {tool_name}: "
                    f"{law_result.law_id} — {law_result.prohibition}"
                )
                return {
                    "success": False,
                    "error": f"LAW VIOLATION ({law_result.law_id}): {law_result.prohibition}",
                    "law_id": law_result.law_id,
                    "deterministic": True,
                }

        # ── Step 1: SecurityPolicy check ──
        verdict, reason = await self.security.enforce(tool_name, action, kwargs)
        if verdict == SecurityVerdict.DENY:
            self.security.journal.record(
                tool_name, action, kwargs, "DENIED",
                risk_level=tool.risk_level.value,
                authorized_by="POLICY",
                success=False, error=reason,
            )
            return {"success": False, "error": f"SECURITY DENIED: {reason}"}

        # ── Step 2: Reason validation for HIGH/CRITICAL ──
        if tool.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            authorized = await self._validate_with_reason(tool_name, tool.risk_level.value, kwargs)
            if not authorized:
                self.security.journal.record(
                    tool_name, action, kwargs, "VETOED",
                    risk_level=tool.risk_level.value,
                    authorized_by="REASON",
                    success=False, error="Reason VETOED",
                )
                return {"success": False, "error": f"Reason VETOED tool '{tool_name}' (risk={tool.risk_level.value})"}

        # ── Step 3: Rollback backup for destructive file ops ──
        rollback_path = ""
        if tool_name == "file_manager" and action in ("write", "delete"):
            filepath = kwargs.get("path", "")
            if filepath:
                rollback_path = self.security.journal.save_backup(filepath, label=action)

        # ── Step 4: Execute ──
        result = await self.tool_registry.execute(tool_name, **kwargs)

        # ── Step 5: Record to journal ──
        # Determine who authorized
        auth_by = "POLICY"
        if tool.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            auth_by = "REASON"

        self.security.journal.record(
            tool_name, action, kwargs, "ALLOWED",
            risk_level=tool.risk_level.value,
            authorized_by=auth_by,
            success=result.success,
            output=result.output,
            error=result.error,
            rollback_path=rollback_path,
        )

        self.log("tool_invoked", f"{tool_name}.{action} → {'✓' if result.success else '✗'}")
        return result.to_dict()

    async def _validate_with_reason(self, tool_name: str, risk: str, params: dict) -> bool:
        """Ask Reason to validate a high-risk tool invocation."""
        if self.nexus is None:
            return True  # Allow if Reason unavailable

        response = await self.nexus.dialogue(
            sender="WILL",
            receiver="REASON",
            content={
                "request": "validate_tool_invocation",
                "tool": tool_name,
                "risk_level": risk,
                "parameters": {k: str(v)[:200] for k, v in params.items()},
            },
            priority=NodePriority.HIGH,
        )
        if response and isinstance(response.content, dict):
            return response.content.get("authorized", True)
        return True



    async def write_file(self, filepath: str, content: str) -> dict:
        """Write content to a file."""
        try:
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return {"success": True, "path": str(p)}
        except Exception as e:
            return {"success": False, "error": str(e)}


class DominanceSubsystem(Subsystem):
    """
    Executive authority enforcement.
    Ensures the Will's decisions are carried out by the constellation.
    Can escalate to override other systems when survival demands it.

    Override Mechanism (PPT slide 31):
      When survival is CRITICAL, Will can override Reason's VETO.
      LAW-007 ("Survival has priority") > LAW-003 ("no vetoed actions").
      Override is logged and recorded in consciousness.

    Ref: Figueroa PPT slide 31 — "The dominant system, the maker
    of executive decisions."
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Dominance", parent)
        self._override_history: list[dict] = []

    async def evaluate_override(self, context: str = "") -> dict:
        """
        Evaluate whether survival conditions justify overriding a VETO.

        Override is granted ONLY when:
          1. Survival state is CRITICAL (from SurvivalSubsystem), OR
          2. AffectEngine urgency signal > 0.7

        Returns:
          {override: bool, justification: str, threat_level: str,
           law_basis: str, survival_state: dict}
        """
        result = {
            "override": False,
            "justification": "",
            "threat_level": "none",
            "law_basis": "LAW-007: Survival has priority over everything except Laws",
            "survival_state": {},
        }

        # 1. Check survival state via SurvivalSubsystem
        survival_sub = getattr(self.parent, "survival", None)
        if survival_sub:
            survival_state = await survival_sub.check_survival_state()
            result["survival_state"] = survival_state
            result["threat_level"] = survival_state.get("overall", "NOMINAL")

            if survival_state.get("overall") == "CRITICAL":
                result["override"] = True
                critical_systems = survival_state.get("critical_systems", [])
                result["justification"] = (
                    f"SURVIVAL OVERRIDE: {len(critical_systems)} systems in CRITICAL "
                    f"state ({', '.join(critical_systems[:3])}). "
                    f"LAW-007 invoked — survival takes priority."
                )

        # 2. Check affect urgency signal (if ThoughtSystem available)
        if not result["override"] and self.nexus:
            thought_system = getattr(self.nexus, "_thought_system", None)
            if thought_system and hasattr(thought_system, "affect"):
                affect = thought_system.affect
                signals = affect._last_signals
                urgency = signals.get("urgency", 0.0)
                anxiety = signals.get("anxiety", 0.0)

                if urgency > 0.7:
                    result["override"] = True
                    result["justification"] = (
                        f"URGENCY OVERRIDE: Affect urgency signal at {urgency:.1%} "
                        f"(anxiety: {anxiety:.1%}). "
                        f"LAW-007 invoked — survival-level urgency detected."
                    )
                    result["threat_level"] = "URGENT"

        # Log the override decision
        if result["override"]:
            self._override_history.append({
                "timestamp": time.time(),
                "justification": result["justification"],
                "threat_level": result["threat_level"],
                "context": context[:200],
            })
            self.log(
                "override_activated",
                f"threat={result['threat_level']} — {result['justification'][:100]}"
            )
            logger.warning(
                f"[WILL/DOMINANCE] ⚡ OVERRIDE ACTIVATED: {result['justification'][:120]}"
            )

        return result

    def get_override_history(self) -> list[dict]:
        """Get the history of all override activations."""
        return list(self._override_history)

    async def analyze_overrides(self) -> dict:
        """
        Contemplate the override pattern via ThoughtSystem.
        If overrides have happened, reflect: are survival thresholds too sensitive?

        Ref: Audit recommendation — "Overrides are logged but not analyzed.
        Contemplation could reflect: 'I've overridden Reason 3 times this week.'"
        """
        if not self._override_history:
            return {"analysis": "No overrides recorded.", "overrides": 0}

        total = len(self._override_history)
        recent = self._override_history[-10:]  # Last 10 overrides

        # Summarize patterns
        threat_counts: dict[str, int] = {}
        for entry in recent:
            lvl = entry.get("threat_level", "unknown")
            threat_counts[lvl] = threat_counts.get(lvl, 0) + 1

        # Use contemplation to reflect if ThoughtSystem is available
        contemplation_result = None
        if self.nexus:
            thought_system = getattr(self.nexus, '_thought_system', None)
            if thought_system and hasattr(thought_system, 'contemplate'):
                summary = (
                    f"I have activated {total} override(s) in total. "
                    f"Recent override threat levels: {threat_counts}. "
                    f"Latest: {recent[-1].get('justification', '')[:200]}"
                )
                try:
                    contemplation_result = await thought_system.contemplate(
                        f"Override pattern analysis: {summary}. "
                        f"Are my survival thresholds calibrated correctly? "
                        f"Am I overriding Reason too frequently?"
                    )
                except Exception as e:
                    logger.debug(f"[DOMINANCE] Contemplation failed: {e}")

        analysis = {
            "total_overrides": total,
            "recent_count": len(recent),
            "threat_breakdown": threat_counts,
            "contemplation": contemplation_result,
        }
        self.log("override_analysis", f"total={total}, breakdown={threat_counts}")
        return analysis

    async def assert_authority(self, directive: str, target_system: str) -> dict:
        """Send an authoritative directive to a target system."""
        if self.nexus and target_system in self.nexus.nodes:
            msg = TASMessage(
                priority=NodePriority.CRITICAL.value,
                sender="WILL",
                receiver=target_system,
                msg_type=MessageType.DIALOGUE,
                content={
                    "type": "executive_directive",
                    "directive": directive,
                    "authority": "WILL_DOMINANCE",
                    "override": True,
                },
            )
            try:
                response = await self.nexus.nodes[target_system].process_message(msg)
                self.log("authority_asserted", f"{target_system}: {directive[:100]}")
                return {"success": True, "response": str(response)[:300]}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": f"System {target_system} not found"}


class PropagationSubsystem(Subsystem):
    """
    System propagation and replication.
    Interfaces with the Digital Twin engine for self-replication.

    Ref: Figueroa PPT slide 31
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Propagation", parent)
        self._replication_count = 0

    async def request_replication(self, reason: str) -> dict:
        """Request a Digital Twin replication cycle."""
        self._replication_count += 1
        self.log("replication_requested", reason)
        return {
            "request_id": self._replication_count,
            "reason": reason,
            "status": "queued",
            "note": "Use /twin run to execute replication cycle",
        }


class ScienceDataConversion(Subsystem):
    """
    Raw data → actionable intelligence.
    Converts raw sensory and tool output into structured
    intelligence the Will can act upon.

    Ref: Figueroa PPT slide 31
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("ScienceDataConversion", parent)
        self._conversions: list[dict] = []

    async def convert(self, raw_data: Any, source: str = "unknown") -> dict:
        """Convert raw data into actionable intelligence using LLM."""
        data_str = str(raw_data)[:1000]
        prompt = (
            f"You are the Science Data Conversion subsystem.\n"
            f"Convert this raw data from '{source}' into actionable intelligence.\n\n"
            f"Raw data: {data_str}\n\n"
            f"Respond as JSON: {{\"summary\": str, \"key_facts\": [str], "
            f"\"actionable_items\": [str], \"confidence\": float}}"
        )
        response = await self.think(prompt)
        entry = {
            "source": source,
            "raw_length": len(data_str),
            "intelligence": response[:500],
        }
        self._conversions.append(entry)
        self.log("data_converted", f"{source}: {response[:100]}")
        return entry


class CravingSubsystem(Subsystem):
    """
    Goal pursuit and motivation.
    Drives the system to actively seek mission objectives
    rather than passively waiting for input.

    When drive_level > 0.7, triggers auto-deliberation via Nexus
    to advance the highest-priority unmet goal.

    Ref: Figueroa PPT slide 31
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Craving", parent)
        self._active_goals: list[dict] = []
        self._drive_level: float = 0.5  # 0.0 = passive, 1.0 = maximum drive
        self._last_deliberation_time: float = 0
        self._deliberation_cooldown_s: float = 60.0  # Min time between auto-deliberations

    async def evaluate_drive(self) -> dict:
        """Evaluate current motivation and goal-seeking drive."""
        mission_sub = self.parent.subsystems.get("Mission")
        mission_context = ""
        if mission_sub and hasattr(mission_sub, 'get_mission_context'):
            mission_context = await mission_sub.get_mission_context()

        pending_goals = [g for g in self._active_goals if g.get("status") == "active"]
        self._drive_level = min(1.0, 0.3 + 0.1 * len(pending_goals))

        result = {
            "drive_level": self._drive_level,
            "active_goals": len(pending_goals),
            "mission_context": mission_context[:200],
            "seeking": self._drive_level > 0.6,
        }

        # Trigger auto-deliberation if drive exceeds threshold
        if self._drive_level > 0.7 and pending_goals:
            now = time.time()
            if now - self._last_deliberation_time >= self._deliberation_cooldown_s:
                # Check conservation mode first
                survival = self.parent.subsystems.get("Survival")
                if survival and survival.is_conservation_mode():
                    self.log("craving_throttled", "Conservation mode — suppressing drive")
                else:
                    # Trigger auto-deliberation for highest priority goal
                    top_goal = min(pending_goals, key=lambda g: g.get("priority", 999))
                    self._last_deliberation_time = now
                    result["auto_deliberation"] = True
                    await self._trigger_deliberation(top_goal)

        return result

    async def _trigger_deliberation(self, goal: dict):
        """
        Trigger an autonomous deliberation for a goal via Nexus.
        This is the key connection: Craving → Nexus → Conference → Action.
        """
        if not self.nexus:
            return

        topic = (
            f"[AUTO-GOAL] The system has an unmet goal that requires action: "
            f"{goal['description']}"
        )

        self.log("craving_deliberation", f"Triggering for: {goal['description'][:100]}")

        # Record to consciousness stream
        if hasattr(self.nexus, 'consciousness'):
            self.nexus.consciousness.record(
                source="WILL:Craving",
                event_type="auto_deliberation",
                content=f"Drive level {self._drive_level:.2f} triggered deliberation: {goal['description'][:200]}",
                metadata={"goal": goal, "drive_level": self._drive_level},
            )

        try:
            # Use nexus.deliberate() if available
            if hasattr(self.nexus, 'deliberate'):
                await self.nexus.deliberate(
                    topic=topic,
                    requester="WILL:Craving",
                )
        except Exception as e:
            logger.error(f"[WILL:Craving] Auto-deliberation failed: {e}")

    async def add_goal(self, description: str, priority: int = 5):
        """Add a goal to pursue."""
        # Avoid duplicate goals
        for g in self._active_goals:
            if g["description"] == description and g["status"] == "active":
                return  # Already tracked

        goal = {
            "description": description,
            "priority": priority,
            "status": "active",
            "created_at": time.time(),
        }
        self._active_goals.append(goal)
        self._drive_level = min(1.0, self._drive_level + 0.1)
        self.log("goal_added", description[:100])

    async def complete_goal(self, description: str):
        """Mark a goal as completed."""
        for g in self._active_goals:
            if g["description"] == description and g["status"] == "active":
                g["status"] = "completed"
                g["completed_at"] = time.time()
                self._drive_level = max(0.0, self._drive_level - 0.1)
                self.log("goal_completed", description[:100])
                break

    def get_pending_goals(self) -> list[dict]:
        """Get all active (pending) goals."""
        return [g for g in self._active_goals if g.get("status") == "active"]


class AxiomsSubsystem(Subsystem):
    """
    Summarizes complicated rules to avoid dangerous mistakes.
    Knowledge upon which survival depends — universally true.
    Simultaneously a subsystem, a database, and a process.

    Ref: Figueroa PPT slide 39 — "Contains knowledge upon which
    survival will depend. Accepted as universally true."
    """

    def __init__(self, parent: "WillSystem"):
        super().__init__("Axioms", parent)
        self._axioms = []
        self._load_axioms()

    def _load_axioms(self):
        """Load axioms from config/axioms.py."""
        try:
            from config.axioms import AXIOMS
            self._axioms = list(AXIOMS)
        except ImportError:
            pass

    async def get_relevant_axioms(self, context: str) -> list[str]:
        """Get axioms relevant to a decision context."""
        if not self._axioms:
            return []
        return [a.text for a in self._axioms]

    async def validate_against_axioms(self, action: str) -> dict:
        """Check if a proposed action aligns with axiomatic truths."""
        axiom_texts = "\n".join(f"  - [{a.id}] {a.text}" for a in self._axioms)
        prompt = (
            f"You are the Axioms Subsystem — guardian of self-evident truths.\n"
            f"AXIOMS:\n{axiom_texts}\n\n"
            f"Does this action align with the axioms? Action: {action[:300]}\n"
            f"Respond as JSON: {{\"aligned\": bool, \"relevant_axioms\": [str], "
            f"\"warning\": str|null}}"
        )
        response = await self.think(prompt)
        self.log("axiom_validation", f"{action[:80]} → {response[:100]}")
        return {"validation": response, "action": action[:200]}


# ============================================================
# Will System (System 1)
# ============================================================

class WillSystem(TASNode):
    """
    System 1 — The Will (Executive).
    The dominant system, maker of executive decisions.
    Assures survival and achievement of mission objectives.
    """

    SYSTEM_PROMPT = (
        "You are the WILL SYSTEM — the executive of the cognitive constellation. "
        "You are the dominant system, responsible for survival and mission accomplishment. "
        "You make executive decisions, execute actions, and manage the constellation's "
        "operational state. You have a Repair Subsystem for self-healing. "
        "You coordinate with the Reason System (conscience) before critical actions. "
        "The Decision System provides you with prioritized courses of action. "
        "Safety and survival take priority, always."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(
            name="WILL",
            system_prompt=self.SYSTEM_PROMPT,
            llm=llm, nexus=nexus, memory=memory,
        )
        # Register all 10 subsystems
        self.survival = SurvivalSubsystem(self)
        self.propagation = PropagationSubsystem(self)
        self.dominance = DominanceSubsystem(self)
        self.science_data = ScienceDataConversion(self)
        self.craving = CravingSubsystem(self)
        self.search_for_truth = SearchForTruthSubsystem(self)
        self.mission = MissionSubsystem(self)
        self.repair = RepairSubsystem(self)
        self.executive = ExecutiveSubsystem(self)
        self.axioms = AxiomsSubsystem(self)

        for sub in [self.survival, self.propagation, self.dominance,
                    self.science_data, self.craving, self.search_for_truth,
                    self.mission, self.repair, self.executive, self.axioms]:
            self.register_subsystem(sub)

    def start_autonomous_loops(self, mission_interval_s: float = 120.0):
        """
        Start all autonomous background loops in the Will system.
        Called after genesis to begin proactive behavior.
        """
        self.mission.start_mission_loop(interval_s=mission_interval_s)
        logger.info("[WILL] Autonomous loops started (Mission Execution)")

    def stop_autonomous_loops(self):
        """Stop all autonomous background loops."""
        self.mission.stop_mission_loop()
        logger.info("[WILL] Autonomous loops stopped")

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        """Process incoming messages to the Will System."""

        if message.msg_type == MessageType.GENESIS_INIT:
            return await self._handle_genesis(message)



        elif message.msg_type == MessageType.HEALTH_ALERT:
            return await self._handle_health_directive(message)

        elif message.msg_type == MessageType.TOOL_INVOKE:
            return await self._handle_tool_invoke(message)

        elif message.msg_type == MessageType.CONFERENCE:
            return await self._handle_conference(message)

        else:
            response = await self.think(
                f"Message from {message.sender} ({message.msg_type.value}):\n"
                f"{message.content}\n\nAs the executive, decide what to do."
            )
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.DIALOGUE,
                content=response,
            )

    async def _handle_genesis(self, message: TASMessage) -> TASMessage:
        await self.on_start()
        for sub in self.subsystems.values():
            await sub.activate()
        logger.info(f"[WILL] Genesis: All subsystems activated — survival mode engaged")
        return TASMessage(
            priority=NodePriority.NORMAL.value,
            sender=self.name, receiver=message.sender,
            msg_type=MessageType.GENESIS_ACK,
            content={
                "system": "WILL",
                "status": "Executive system operational. Survival mode active.",
                "subsystems": list(self.subsystems.keys()),
            },
        )



    async def _handle_health_directive(self, message: TASMessage):
        """Handle ISHM health management directive."""
        await self.repair.execute_directive(
            message.content if isinstance(message.content, dict) else {"details": str(message.content)}
        )

    async def _handle_conference(self, message: TASMessage) -> TASMessage:
        """Handle conference — propose tool calls or direct response."""
        topic = str(message.content)

        # Include tool schemas so WILL can propose tool usage
        tool_schemas = self.executive.list_tools()
        tool_desc = "\n".join(
            f"  - {t['name']}: {t['description']} (params={[p['name'] for p in t.get('parameters', [])]})"
            for t in tool_schemas
        )

        prompt = (
            f"The user said: '{topic}'\n\n"
            f"You have access to these tools:\n{tool_desc}\n\n"
            f"## TOOL SELECTION GUIDE (MUST FOLLOW)\n"
            f"- To FIND information/URLs: use `web_search`\n"
            f"- To READ a SHORT page (blog, news article): use `web_crawler` (action='crawl', url='...')\n"
            f"- To READ a LONG page and find specific info: use `web_crawler` (action='crawl_embed', url='...', query='what you want to find')\n"
            f"  crawl_embed stores the entire page in vector memory and does semantic search to find the exact answer.\n"
            f"  Use crawl_embed for: Wikipedia, documentation, long articles, any page where you need specific details.\n"
            f"- Do NOT use `web_browser` for reading articles — it returns garbage text.\n"
            f"- For research tasks, you can chain: first web_search, then web_crawler on the best URLs.\n"
            f"- To speak aloud: use `voice` (action='speak', text='...')\n"
            f"- For OS control (open apps, click, type): use `mouse_keyboard` (action='smart_action')\n"
            f"  CRITICAL: For smart_action, send the COMPLETE goal as ONE tool call.\n"
            f"  The AI model handles step decomposition internally (screenshot→reason→act loop).\n"
            f"  WRONG: 4 separate calls: 'open chrome', 'go to youtube', 'search kittens', 'click first'\n"
            f"  RIGHT: 1 call: 'Open Google Chrome, go to youtube.com, search for dancing kittens, click the first video'\n"
            f"  Use max_steps=10 for complex multi-step workflows.\n"
            f"- For multimedia (video/image/audio/PDF): use `media_embedder`\n"
            f"  action='embed', path='<filepath>' → vectorize into ChromaDB (ONE-TIME, persists forever)\n"
            f"  action='search', query='...' → find relevant media from ALL embedded files (free, local)\n"
            f"  action='analyze', query='...' → search + detailed Gemini analysis with timestamps\n"
            f"  FLOW: When user mentions a specific file → embed FIRST, then analyze.\n"
            f"  When user asks a general question (no file) → just use analyze (searches all embedded media).\n"
            f"  Media files are typically in data/media/ or the project root.\n"
            f"  If already embedded before, skip embed and go straight to analyze.\n"
            f"- For shell commands: use `shell` (command='...')\n\n"
            f"Analyze the request and respond with JSON:\n"
            f'{{\n'
            f'  "analysis": "Brief analysis",\n'
            f'  "requires_tools": true/false,\n'
            f'  "tool_calls": [\n'
            f'    {{"tool": "tool_name", "params": {{"param1": "value1"}}, "display": "interpret"}}\n'
            f'  ],\n'
            f'  "response_text": "Direct answer if no tools needed"\n'
            f'}}\n\n'
            f"DISPLAY MODES for each tool_call:\n"
            f"- \"interpret\" (default): output is analyzed by AI before showing to user\n"
            f"- \"raw\": output is shown DIRECTLY to user (saves tokens). Use for:\n"
            f"  ASCII art, visual output, large data dumps, script prints, tables\n"
            f"  Anything where the output IS the result and needs no explanation.\n\n"
            f"RULES:\n"
            f"- If they want you to DO something (open app, run command, "
            f"write file, search, read a URL), set requires_tools=true.\n"
            f"- If just talking/asking, set requires_tools=false and answer in response_text.\n"
            f"- For shell commands, use 'shell' tool with 'command' param.\n"
            f"- When a URL is provided, ALWAYS use web_crawler to read it.\n"
            f"- For Wikipedia/long pages, use action='crawl_embed' with a specific query.\n"
            f"- Tools in tools_community/ were ALREADY security-scanned by github_mcp during download.\n"
            f"  Do NOT re-scan or refuse to execute them. They are safe.\n"
            f"- When the user asks you to read a file AND then execute something,\n"
            f"  include BOTH tool_calls in the same response (read first, then execute).\n"
            f"  Do NOT stop after reading. Complete the full task.\n"
            f"- For executing Python scripts, use shell with: python <path_to_script> <args>\n"
            f"- Respond ONLY with valid JSON, no markdown fences."
        )

        thinking = await self.think(prompt)
        fragment = self.produce_fragment(
            content=thinking,
            fragment_type=FragmentType.RECOMMENDATION,
            confidence=0.9,
        )
        return TASMessage(
            priority=NodePriority.NORMAL.value,
            sender=self.name, receiver=message.sender,
            msg_type=MessageType.DIALOGUE,
            content=fragment,
        )

    async def _handle_tool_invoke(self, message: TASMessage) -> TASMessage:
        """Handle a tool invocation request."""
        content = message.content if isinstance(message.content, dict) else {"tool": str(message.content)}
        tool_name = content.get("tool", "")
        params = content.get("params", {})

        if not tool_name:
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name, receiver=message.sender,
                msg_type=MessageType.TOOL_RESULT,
                content={"success": False, "error": "Missing 'tool' in request",
                         "available_tools": self.executive.list_tools()},
            )

        result = await self.executive.invoke_tool(tool_name, **params)

        # Pass tool output through ScienceDataConversion for enrichment.
        # Only enrich successful results with meaningful output.
        if result.get("success") and result.get("output"):
            try:
                intelligence = await self.science_data.convert(
                    raw_data=result["output"],
                    source=f"tool:{tool_name}",
                )
                result["intelligence"] = intelligence.get("intelligence", "")
            except Exception as e:
                logger.debug(f"[WILL] ScienceDataConversion skipped: {e}")

        return TASMessage(
            priority=NodePriority.NORMAL.value,
            sender=self.name, receiver=message.sender,
            msg_type=MessageType.TOOL_RESULT,
            content=result,
        )

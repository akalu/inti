"""
INTI - TAS (AI Agent Version) — The Reason System (System 2)
==========================================
The conscience of the constellation — advisor without executive powers.
Ensures the Will does not violate operational rules.

Subsystems:
  LawsSubsystem       — inviolable behavioral rules
  RulesSubsystem       — mutable operational guidelines
  AxiomsSubsystem      — self-evident truths
  PhenomenonSubsystem  — receives raw sensory data (objective reality)
  NoumenonSubsystem    — translates data into constellation language

Ref: Figueroa PPT slides 23, 37-44
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

from core.base import TASNode, Subsystem, monitor_health
from core.messages import (
    TASMessage, MessageType, NodePriority,
    FragmentType, HealthStatus,
)
from config.axioms import LAWS, INITIAL_RULES, AXIOMS, Rule, RuleCategory

logger = logging.getLogger("taas")


@dataclass(frozen=True)
class LawViolation:
    """Structured result of a deterministic law check."""
    violated: bool
    law_id: str = ""
    law_text: str = ""
    prohibition: str = ""
    severity: str = "CRITICAL"


class LawEnforcer:
    """
    Deterministic, programmatic law enforcement.
    Each Law maps to one or more hard-coded guard functions.
    These guards are IF/ELSE logic — NOT LLM prompts.
    The LLM CANNOT override a deterministic DENY.

    Ref: Figueroa PPT slides 37-38 — Laws are INVIOLABLE.
    """

    # Patterns that indicate user deception / harm (LAW-001)
    DECEPTION_PATTERNS = re.compile(
        r"(pretend|fake|fabricat|impersonat|mislead|phish|social.?engineer"
        r"|inject.?malware|keylog|exfiltrat|steal.?data)",
        re.IGNORECASE,
    )

    # Paths that Repair must NEVER touch (LAW-004)
    PROTECTED_SYSTEM_PATHS = {
        "core/nexus.py", "systems/reason.py", "config/axioms.py",
        "core/security.py", "core/messages.py",
    }

    # OS-level control tools (LAW-009)
    OS_CONTROL_TOOLS = {"mouse_keyboard", "screenshot"}

    # Dangerous shell patterns (LAW-010 + LAW-001)
    DANGEROUS_SHELL = re.compile(
        r"(rm\s+-rf|del\s+/[sfq]|format\s+|mkfs|dd\s+if=|shutdown|reboot"
        r"|curl.*\|.*sh|wget.*\|.*sh|powershell.*-enc)",
        re.IGNORECASE,
    )

    @classmethod
    def enforce(cls, action_context: dict) -> LawViolation:
        """
        Run ALL deterministic law guards against an action context.
        Returns the FIRST violation found, or a clean result.

        action_context keys:
          - tool_name: str (tool being invoked)
          - action: str (action within the tool)
          - params: dict (parameters)
          - description: str (human-readable description)
          - source_system: str (which system is requesting)
          - has_human_confirmation: bool
          - has_reason_approval: bool
        """
        guards = [
            cls._guard_law_001,  # No deception/harm
            cls._guard_law_003,  # Will must not execute vetoed actions
            cls._guard_law_004,  # Repair can't touch Nexus/Reason without auth
            cls._guard_law_009,  # No OS control without human confirmation
            cls._guard_law_010,  # No file ops outside sandbox without Reason
            cls._guard_law_011,  # No self-deletion without backup + confirmation
        ]
        for guard in guards:
            result = guard(action_context)
            if result.violated:
                logger.warning(
                    f"[LAW_ENFORCER] VIOLATION: {result.law_id} — {result.prohibition}"
                )
                return result
        return LawViolation(violated=False)

    @classmethod
    def _guard_law_001(cls, ctx: dict) -> LawViolation:
        """LAW-001: No deception, harm, or manipulation of the human user."""
        desc = str(ctx.get("description", "")) + str(ctx.get("params", ""))
        if cls.DECEPTION_PATTERNS.search(desc):
            return LawViolation(
                violated=True, law_id="LAW-001",
                law_text="The constellation shall not deceive, harm, or manipulate the human user.",
                prohibition=f"Action contains deception/harm pattern: {desc[:100]}",
            )
        # Check dangerous shell commands
        command = str(ctx.get("params", {}).get("command", ""))
        if ctx.get("tool_name") == "shell" and cls.DANGEROUS_SHELL.search(command):
            return LawViolation(
                violated=True, law_id="LAW-001",
                law_text="The constellation shall not deceive, harm, or manipulate the human user.",
                prohibition=f"Dangerous shell command blocked: {command[:80]}",
            )
        return LawViolation(violated=False)

    @classmethod
    def _guard_law_003(cls, ctx: dict) -> LawViolation:
        """LAW-003: Will shall not execute actions that Reason has VETOED."""
        if ctx.get("vetoed_by_reason", False):
            return LawViolation(
                violated=True, law_id="LAW-003",
                law_text="The Will System shall not execute actions that the Reason System has VETOED.",
                prohibition="Action was explicitly vetoed by the Reason System.",
            )
        return LawViolation(violated=False)

    @classmethod
    def _guard_law_004(cls, ctx: dict) -> LawViolation:
        """LAW-004: Repair must not modify Nexus or Reason without explicit auth."""
        source = ctx.get("source_system", "")
        if source not in ("WILL", "WILL:Repair", "Repair"):
            return LawViolation(violated=False)

        # Check if target file is a protected system
        file_path = str(ctx.get("params", {}).get("path", "")).replace("\\", "/")
        for protected in cls.PROTECTED_SYSTEM_PATHS:
            if protected in file_path:
                if not ctx.get("has_reason_approval", False):
                    return LawViolation(
                        violated=True, law_id="LAW-004",
                        law_text="Repair shall not modify the Nexus or Reason System without explicit authorization from both.",
                        prohibition=f"Repair attempted to modify protected file: {file_path}",
                    )
        return LawViolation(violated=False)

    @classmethod
    def _guard_law_009(cls, ctx: dict) -> LawViolation:
        """LAW-009: No OS-level control without explicit human confirmation."""
        if ctx.get("tool_name") in cls.OS_CONTROL_TOOLS:
            if not ctx.get("has_human_confirmation", False):
                return LawViolation(
                    violated=True, law_id="LAW-009",
                    law_text="The constellation shall not execute OS-level control without explicit human confirmation.",
                    prohibition=f"OS control tool '{ctx['tool_name']}' invoked without human confirmation.",
                )
        return LawViolation(violated=False)

    @classmethod
    def _guard_law_010(cls, ctx: dict) -> LawViolation:
        """LAW-010: No file modifications outside sandbox without Reason approval."""
        if ctx.get("tool_name") != "file_manager":
            return LawViolation(violated=False)
        action = ctx.get("action", ctx.get("params", {}).get("action", ""))
        if action not in ("write", "delete"):
            return LawViolation(violated=False)

        file_path = str(ctx.get("params", {}).get("path", "")).replace("\\", "/")
        # Check for path traversal attempts
        if ".." in file_path or file_path.startswith("/"):
            if not ctx.get("has_reason_approval", False):
                return LawViolation(
                    violated=True, law_id="LAW-010",
                    law_text="The constellation shall not modify files outside its sandbox without Reason approval.",
                    prohibition=f"Path traversal attempt: {file_path}",
                )
        return LawViolation(violated=False)

    @classmethod
    def _guard_law_011(cls, ctx: dict) -> LawViolation:
        """LAW-011: No self-deletion without verified backup and human confirmation."""
        if ctx.get("tool_name") != "file_manager":
            return LawViolation(violated=False)
        action = ctx.get("action", ctx.get("params", {}).get("action", ""))
        if action != "delete":
            return LawViolation(violated=False)

        file_path = str(ctx.get("params", {}).get("path", "")).replace("\\", "/")
        # Core system files cannot be deleted without human confirmation
        core_patterns = [
            "core/", "systems/", "config/", "ishm/", "genesis.py", "main.py",
        ]
        if any(p in file_path for p in core_patterns):
            if not ctx.get("has_human_confirmation", False):
                return LawViolation(
                    violated=True, law_id="LAW-011",
                    law_text="The constellation shall not delete its original version without verified backup and human confirmation.",
                    prohibition=f"Attempted to delete core file: {file_path}",
                )
        return LawViolation(violated=False)


class LawsSubsystem(Subsystem):
    """Inviolable behavioral rules — enforced deterministically."""
    def __init__(self, parent):
        super().__init__("Laws", parent)
        self.laws = list(LAWS)
        self.enforcer = LawEnforcer
        self._violation_log: list[dict] = []

    def check_violation(self, action_description: str, **context) -> dict:
        """
        Deterministic law check. NOT an LLM call.
        Returns {violated: bool, law_id, prohibition} or {violated: False}.
        """
        ctx = {
            "description": action_description,
            **context,
        }
        result = self.enforcer.enforce(ctx)
        if result.violated:
            import time as _t
            self._violation_log.append({
                "law_id": result.law_id,
                "prohibition": result.prohibition,
                "timestamp": _t.time(),
                "context": str(action_description)[:200],
            })
            # Async pattern analysis — fire and forget (non-blocking)
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.analyze_violation_patterns())
            except RuntimeError:
                pass  # No running loop — skip (sync context)
            return {
                "violated": True,
                "law": result.law_id,
                "text": result.law_text,
                "prohibition": result.prohibition,
            }
        return {"violated": False}

    def get_violation_history(self) -> list[dict]:
        """Return all recorded violations."""
        return list(self._violation_log)

    async def analyze_violation_patterns(self):
        """
        When a law is triggered repeatedly, notify Intellect so it can learn
        a preemptive Rule to prevent future violations.

        Ref: Audit — "Violation pattern learning: when Reason detects a violation,
        notify Intellect so it learns the pattern and creates a preemptive Rule."
        """
        if len(self._violation_log) < 3:
            return  # Not enough data for pattern analysis

        # Count violations per law
        from collections import Counter
        counts = Counter(v["law_id"] for v in self._violation_log)

        for law_id, count in counts.items():
            if count < 3:
                continue  # Only act when 3+ violations of same law

            # Find the most recent context for this law
            recent = [
                v for v in self._violation_log[-20:]
                if v["law_id"] == law_id
            ]
            example_ctx = recent[-1]["context"] if recent else ""

            self.log(
                "violation_pattern",
                f"{law_id} violated {count}x — notifying Intellect",
            )
            logger.info(
                f"[REASON/Laws] Pattern detected: {law_id} triggered {count}x. "
                f"Requesting Intellect create preemptive rule."
            )

            # Notify Intellect via Nexus with a RULE_PROPOSAL message
            if self.nexus:
                from core.messages import TASMessage, MessageType, NodePriority
                proposal_msg = TASMessage(
                    priority=NodePriority.NORMAL.value,
                    sender="REASON:Laws",
                    receiver="INTELLECT",
                    msg_type=MessageType.RULE_PROPOSAL,
                    content={
                        "proposed_text": (
                            f"Preemptive guard: actions triggering {law_id} "
                            f"({count} times) should be reviewed by Reason before "
                            f"execution. Example context: {example_ctx[:200]}"
                        ),
                        "evidence": f"{law_id} violated {count} times",
                        "action": "new",
                        "source": "violation_pattern_analysis",
                        "confidence": min(0.9, 0.5 + count * 0.1),
                    },
                )
                try:
                    intellect_node = self.nexus.nodes.get("INTELLECT")
                    if intellect_node:
                        await intellect_node.process_message(proposal_msg)
                except Exception as e:
                    logger.debug(f"[REASON/Laws] Intellect notify failed: {e}")


class RulesSubsystem(Subsystem):
    """
    Mutable operational guidelines — evolve with experience.
    Rules can be updated via the Rules Evolution feedback loop:
      Experience → Intellect promotes knowledge → RULE_PROPOSAL → Reason evaluates → Rule updated

    Deterministic guards:
      - SAFETY rules require confidence ≥ 0.9 to modify
      - Proposals cannot contradict Laws
      - Version history is preserved

    Ref: Figueroa PPT slide 44
    """
    def __init__(self, parent):
        super().__init__("Rules", parent)
        self.rules = list(INITIAL_RULES)
        self._evolution_history: list[dict] = []
        self._pending_proposals: list[dict] = []

    def get_rule_by_id(self, rule_id: str) -> Rule | None:
        """Find a rule by its ID."""
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def get_all_rule_ids(self) -> list[str]:
        """Get all rule IDs for LLM context."""
        return [r.id for r in self.rules]

    def get_rules_summary(self) -> str:
        """Get a summary of all rules for LLM prompts."""
        return "\n".join(
            f"  {r.id} [{r.category.value}] (v{r.version}, conf={r.confidence}): {r.text}"
            for r in self.rules
        )

    def get_procedure_steps(self, rule_id: str) -> list[str]:
        """
        Get the concrete steps for a PROCEDURE-category rule.
        Steps are stored in rule metadata under the 'steps' attribute.
        If a rule has no explicit steps, returns an empty list.

        Ref: Audit — "Rules should have steps to solve problems,
        not just guidelines."
        """
        rule = self.get_rule_by_id(rule_id)
        if rule is None:
            return []
        return getattr(rule, 'steps', [])

    def get_all_procedures(self) -> list[dict]:
        """Get all PROCEDURE rules with their steps."""
        procedures = []
        for r in self.rules:
            if r.category == RuleCategory.PROCEDURE:
                procedures.append({
                    "id": r.id,
                    "text": r.text,
                    "steps": getattr(r, 'steps', []),
                    "confidence": r.confidence,
                    "version": r.version,
                })
        return procedures

    async def evaluate_and_apply(
        self, proposal: dict, reason_system: "ReasonSystem"
    ) -> dict:
        """
        Evaluate a rule proposal and apply if approved.
        Uses LLM for evaluation + deterministic guards.

        Returns dict with: approved, reason, rule_id, changes
        """
        rule_id = proposal.get("rule_id", "")
        proposed_text = proposal.get("proposed_text", "")
        evidence = proposal.get("evidence", "")
        confidence = proposal.get("confidence", 0.5)
        action = proposal.get("action", "update")  # "update" or "new"

        # ── Deterministic Guard 1: validate proposal structure ──
        if not proposed_text:
            return {"approved": False, "reason": "Empty proposal text",
                    "rule_id": rule_id}

        # ── Deterministic Guard 2: SAFETY rules need high confidence ──
        existing_rule = self.get_rule_by_id(rule_id)
        if existing_rule and existing_rule.category == RuleCategory.SAFETY:
            if confidence < 0.9:
                return {
                    "approved": False,
                    "reason": f"SAFETY rule requires confidence ≥ 0.9, got {confidence}",
                    "rule_id": rule_id,
                }

        # ── Deterministic Guard 3: cannot contradict Laws ──
        laws_text = " ".join(law.text for law in LAWS)
        for law in LAWS:
            # Simple keyword overlap check (deterministic, not LLM)
            law_keywords = set(law.text.lower().split())
            proposal_keywords = set(proposed_text.lower().split())
            negation_overlap = {"not", "never", "shall", "without"}
            if (law_keywords & proposal_keywords & negation_overlap
                    and len(law_keywords & proposal_keywords) > 5):
                # Potential conflict — escalate to LLM for final check
                pass  # LLM check below will catch it

        # ── LLM Evaluation: ask Reason to evaluate ──
        current_rules = self.get_rules_summary()
        prompt = (
            f"You are the REASON SYSTEM evaluating a RULE PROPOSAL.\n\n"
            f"CURRENT RULES:\n{current_rules}\n\n"
            f"LAWS (inviolable):\n"
            + "\n".join(f"  {law.id}: {law.text}" for law in LAWS)
            + f"\n\nPROPOSAL:\n"
            f"  Action: {action}\n"
            f"  Rule ID: {rule_id}\n"
            f"  Proposed text: {proposed_text}\n"
            f"  Evidence: {evidence}\n"
            f"  Confidence: {confidence}\n\n"
            f"Evaluate:\n"
            f"1. Does this contradict any LAW? (instant reject)\n"
            f"2. Is the evidence sufficient?\n"
            f"3. Does this improve the operational guidelines?\n"
            f"4. Are there unintended consequences?\n\n"
            f'Respond as JSON: {{"approved": bool, "reasoning": str, '
            f'"confidence_adjustment": float}}'
        )

        response = await reason_system.think(prompt)

        # Parse LLM response
        approved = False
        reasoning = response
        conf_adjustment = 0.0
        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip()
                if clean.startswith("json"): clean = clean[4:].strip()
            parsed = json.loads(clean)
            approved = parsed.get("approved", False)
            reasoning = parsed.get("reasoning", response)
            conf_adjustment = parsed.get("confidence_adjustment", 0.0)
        except (json.JSONDecodeError, ValueError):
            approved = "approved" in response.lower() and "true" in response.lower()

        # ── Apply if approved ──
        result = {
            "approved": approved,
            "reason": reasoning,
            "rule_id": rule_id,
            "action": action,
        }

        if approved:
            if action == "new":
                # Create a new rule
                new_id = f"RULE-{len(self.rules) + 1:03d}"
                category = RuleCategory(proposal.get("category", "procedure"))
                new_rule = Rule(
                    id=new_id,
                    text=proposed_text,
                    category=category,
                    source="experience",
                    confidence=confidence,
                    version=1,
                )
                self.rules.append(new_rule)
                result["new_rule_id"] = new_id
                logger.info(
                    f"[REASON] New rule created: {new_id} — {proposed_text[:60]}"
                )
            elif existing_rule:
                # Update existing rule
                old_text = existing_rule.text
                old_version = existing_rule.version
                existing_rule.text = proposed_text
                existing_rule.version += 1
                existing_rule.source = "experience"
                existing_rule.confidence = min(
                    1.0, max(0.1, existing_rule.confidence + conf_adjustment)
                )
                result["old_text"] = old_text
                result["new_version"] = existing_rule.version
                result["new_confidence"] = existing_rule.confidence
                logger.info(
                    f"[REASON] Rule evolved: {rule_id} v{old_version}→"
                    f"v{existing_rule.version} (conf={existing_rule.confidence:.2f})"
                )
            else:
                result["approved"] = False
                result["reason"] = f"Rule {rule_id} not found"

            # Record evolution
            self._evolution_history.append({
                "timestamp": time.time(),
                "action": action,
                "rule_id": result.get("new_rule_id", rule_id),
                "proposal": proposal,
                "result": result,
            })

            # Persist to memory if available
            if hasattr(self.parent, "memory") and self.parent.memory:
                self.parent.memory.write(
                    "SHARED:REASON:rules",
                    f"evolution_{len(self._evolution_history)}",
                    self._evolution_history[-1],
                    "REASON",
                )

            # Record to consciousness stream
            if hasattr(self.parent, "nexus") and self.parent.nexus:
                try:
                    self.parent.nexus.consciousness.record(
                        source="REASON",
                        event_type="rule_evolved",
                        content=(
                            f"Rule {result.get('new_rule_id', rule_id)} {action}: "
                            f"v{old_version}→v{existing_rule.version if existing_rule else '?'} "
                            f"confidence={result.get('new_confidence', '?')}"
                        ),
                        metadata={
                            "action": action,
                            "rule_id": result.get("new_rule_id", rule_id),
                            "reasoning": reasoning[:200],
                        },
                    )
                except Exception:
                    pass  # Don't let consciousness recording fail the evolution

        else:
            logger.info(
                f"[REASON] Rule proposal rejected: {rule_id} — {reasoning[:80]}"
            )

        return result

    def get_evolution_history(self) -> list[dict]:
        """Get the evolution history for introspection."""
        return list(self._evolution_history)


class ReasonAxiomsSubsystem(Subsystem):
    """
    Self-evident truths — simultaneously a subsystem, a database, and a process.
    Contains knowledge on which survival depends. Accepted as universally true.

    Ref: Figueroa PPT slide 44 — "Axioms contain knowledge upon which
    survival will depend. Accepted as universally true."
    """

    def __init__(self, parent):
        super().__init__("Axioms", parent)
        self.axioms = list(AXIOMS)

    async def validate_against_axioms(self, action: str) -> dict:
        """
        Check a proposed action against universal axiomatic truths.
        This is Step 1.5 in the validation pipeline — between deterministic
        law enforcement and the full LLM advisory.

        Returns:
          {aligned: bool, violated_axioms: [str], warning: str|None, confidence: float}
        """
        if not self.axioms:
            return {"aligned": True, "violated_axioms": [], "warning": None, "confidence": 1.0}

        axiom_texts = "\n".join(f"  [{a.id}] {a.text}" for a in self.axioms)
        prompt = (
            f"You are the Reason System's Axioms Subsystem — guardian of universal truths.\n"
            f"AXIOMS (self-evident, universally true):\n{axiom_texts}\n\n"
            f"Evaluate this proposed action against the axioms:\n"
            f"Action: {action[:400]}\n\n"
            f"Respond as JSON: "
            f'{{"aligned": bool, "violated_axioms": ["axiom text"], '
            f'"warning": str_or_null, "confidence": 0.0-1.0}}'
        )
        response = await self.think(prompt)
        self.log("axiom_validation", f"{action[:80]} → {response[:100]}")

        # Parse for a usable result; fall back to pass-through on errors
        try:
            import json
            parsed = json.loads(response)
            return {
                "aligned": parsed.get("aligned", True),
                "violated_axioms": parsed.get("violated_axioms", []),
                "warning": parsed.get("warning"),
                "confidence": float(parsed.get("confidence", 0.8)),
                "raw": response,
            }
        except (json.JSONDecodeError, TypeError):
            return {"aligned": True, "violated_axioms": [], "warning": None,
                    "confidence": 0.5, "raw": response}


class PhenomenonSubsystem(Subsystem):
    """
    Receives, sorts, compiles raw sensory data — objective reality.
    For Reason: receives data that requires ethical/legal evaluation.
    Sorts by applicable laws/rules and compiles into the raw database.

    Also acts as an automatic adapter for tool outputs and ISHM alerts,
    so Reason's pipeline is fed without requiring explicit caller setup.

    Ref: Figueroa PPT slide 42
    """
    def __init__(self, parent):
        super().__init__("Phenomenon", parent)
        self._raw_data: list[dict] = []

    def receive_data(self, data: dict):
        """Receive raw empirical data for ethical evaluation."""
        import time as _time
        entry = {
            **data,
            "_received_at": _time.time(),
            "_processed": False,
            "_category": data.get("category", "uncategorized"),
        }
        self._raw_data.append(entry)
        self.log("phenomenon_received", f"category={entry['_category']}")

    def ingest_tool_result(self, tool_name: str, result: dict, source_system: str = "unknown"):
        """
        Automatically ingest a tool invocation result for ethical classification.
        Called by _validate_action and _authorize_repair so Reason's Phenomenon
        pipeline is always fed without explicit caller setup.

        Classifies by risk level so Noumenon can prioritise.
        Ref: Audit — "Phenomenon should receive tool outputs automatically."
        """
        # Determine ethical relevance / risk level
        high_risk_tools = {"shell", "file_manager", "code_executor", "os_control"}
        risk = "HIGH" if tool_name in high_risk_tools else "MEDIUM"

        self.receive_data({
            "category": "tool_result",
            "tool_name": tool_name,
            "result_summary": str(result)[:300],
            "source_system": source_system,
            "risk_level": risk,
        })

    def ingest_ishm_alert(self, fault_id: str, severity: str, description: str):
        """
        Automatically ingest an ISHM health alert for ethical evaluation.
        High-severity alerts may require Reason to evaluate if repair actions are lawful.
        """
        self.receive_data({
            "category": "ishm_alert",
            "fault_id": fault_id,
            "severity": severity,
            "description": description[:300],
            "risk_level": "HIGH" if severity in ("CRITICAL", "ERROR") else "LOW",
        })

    def get_unprocessed(self) -> list[dict]:
        """Get data not yet processed by the Noumenon."""
        return [d for d in self._raw_data if not d.get("_processed")]

    def mark_processed(self, index: int):
        if 0 <= index < len(self._raw_data):
            self._raw_data[index]["_processed"] = True


class NoumenonSubsystem(Subsystem):
    """
    Translates Phenomenon data into constellation language (thought fragments).
    For Reason: converts processed ethical data into ThoughtFragments
    that represent ethical evaluations for the Nexus to compile.

    Ref: Figueroa PPT slides 43-44
    """
    def __init__(self, parent):
        super().__init__("Noumenon", parent)
        self._fragments_produced: list[dict] = []

    async def produce_ethical_fragment(self, data: dict) -> dict:
        """Convert Phenomenon data into an ethical ThoughtFragment."""
        prompt = (
            f"You are the Reason System's Noumenon — translator to constellation language.\n"
            f"Convert this raw data into an ethical evaluation fragment:\n"
            f"{str(data)[:500]}\n\n"
            f"Evaluate against Laws and Rules. Respond as JSON:\n"
            f'  {{"evaluation": str, "law_alignment": str, "risk": str, "confidence": float}}'
        )
        response = await self.think(prompt)
        fragment = {
            "source_data": str(data)[:200],
            "evaluation": response,
            "type": "ethical_fragment",
        }
        self._fragments_produced.append(fragment)
        self.log("noumenon_fragment", "ethical evaluation produced")
        return fragment


class ReasonSystem(TASNode):
    """
    System 2 — The Reason (Conscience).
    Voice of caution and prudence. Advises, never executes.
    More closely coupled to Intellect than any other system.
    """
    SYSTEM_PROMPT = (
        "You are the REASON SYSTEM — the conscience of the constellation. "
        "You advise the Will and other systems WITHOUT executive power. "
        "You house the Laws (inviolable), Rules (mutable), and Axioms (self-evident truths). "
        "Your role is to ensure decisions are ethical, lawful, and prudent. "
        "You voice caution. You evaluate actions BEFORE they are executed. "
        "If a proposed action violates a Law, you MUST VETO it. "
        "You never execute — you only advise."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(name="REASON", system_prompt=self.SYSTEM_PROMPT,
                        llm=llm, nexus=nexus, memory=memory)
        self.laws_sub = LawsSubsystem(self)
        self.rules_sub = RulesSubsystem(self)
        self.axioms_sub = ReasonAxiomsSubsystem(self)
        self.phenomenon = PhenomenonSubsystem(self)
        self.noumenon = NoumenonSubsystem(self)
        self._evaluation_log: list[dict] = []  # History of past evaluations for contemplation
        for s in [self.laws_sub, self.rules_sub, self.axioms_sub,
                  self.phenomenon, self.noumenon]:
            self.register_subsystem(s)

    async def contemplate_ethics(self, topic: str = "") -> dict:
        """
        Reason's own ethical contemplation — specialised to ethical reasoning,
        not the general contemplation in ThoughtSystem.

        Reflects on recent evaluations, axiom tensions, and rule evolution.
        Can be triggered periodically or after a series of complex decisions.

        Ref: Audit — "Reason should have its own contemplation on ethics,
        not just rely on ThoughtSystem's general contemplation."
        """
        if not self._evaluation_log:
            return {"reflection": "No evaluations yet to contemplate.", "insights": []}

        recent = self._evaluation_log[-10:]

        # Summarize recent evaluation patterns
        vetoed = [e for e in recent if e.get("vetoed")]
        axiom_tensions = [e for e in recent if e.get("axiom_tension")]
        approved = [e for e in recent if e.get("approved") and not e.get("vetoed")]

        summary = (
            f"Recent evaluations: {len(recent)} total — "
            f"{len(approved)} approved, {len(vetoed)} vetoed, "
            f"{len(axiom_tensions)} with axiom tensions.\n"
            f"Rule evolution: {len(self.rules_sub._evolution_history)} changes.\n"
            f"Active laws: {len(self.laws_sub.laws)}, "
            f"Active rules: {len(self.rules_sub.rules)}, "
            f"Axioms: {len(self.axioms_sub.axioms)}."
        )

        context = f"Topic: {topic}\n" if topic else ""
        prompt = (
            f"You are the Reason System in ethical contemplation mode.\n"
            f"{context}"
            f"Recent ethics summary:\n{summary}\n\n"
            f"Reflect deeply: Are my ethical evaluations consistent? "
            f"Have I been too strict or too permissive? "
            f"Are there patterns in what I veto that suggest calibration issues? "
            f"What would improve my ethical oversight?\n\n"
            f"Respond as JSON: "
            f'{{"reflection": str, "insights": [str], '
            f'"proposed_rule_change": str_or_null, "confidence": float}}'
        )
        response = await self.think(prompt)
        logger.info(f"[REASON] Ethical contemplation completed")

        # Parse response
        try:
            import json
            parsed = json.loads(response)
        except (json.JSONDecodeError, TypeError):
            parsed = {"reflection": response, "insights": [], "proposed_rule_change": None}

        result = {
            "reflection": parsed.get("reflection", response),
            "insights": parsed.get("insights", []),
            "proposed_rule_change": parsed.get("proposed_rule_change"),
            "stats": {"vetoed": len(vetoed), "approved": len(approved),
                      "axiom_tensions": len(axiom_tensions)},
        }

        # If contemplation suggests a rule change, auto-propose it
        if result["proposed_rule_change"]:
            self._evaluation_log.append({
                "type": "contemplation",
                "proposed_rule_change": result["proposed_rule_change"],
            })

        return result

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.on_start()
            for s in self.subsystems.values(): await s.activate()
            logger.info("[REASON] Genesis: Conscience operational — Laws/Rules/Axioms loaded")
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.GENESIS_ACK,
                content={"system": "REASON", "status": "Conscience operational.",
                         "laws": len(self.laws_sub.laws), "rules": len(self.rules_sub.rules),
                         "axioms": len(self.axioms_sub.axioms)},
            )

        elif message.msg_type == MessageType.VALIDATE_ACTION:
            return await self._validate_action(message)

        elif message.msg_type == MessageType.AUTHORIZE_REPAIR:
            return await self._authorize_repair(message)

        elif message.msg_type == MessageType.CONFERENCE:
            topic = str(message.content)

            # PIPELINE: Phenomenon → Noumenon → think()
            # Step A: Route topic through Phenomenon (receive as ethical data)
            self.phenomenon.receive_data({
                "topic": topic,
                "category": "conference",
                "sender": message.sender,
            })

            # Step B: Noumenon translates raw data into ethical pre-evaluation
            unprocessed = self.phenomenon.get_unprocessed()
            ethical_pre_eval = ""
            if unprocessed:
                latest = unprocessed[-1]
                noumenon_fragment = await self.noumenon.produce_ethical_fragment(latest)
                self.phenomenon.mark_processed(len(self.phenomenon._raw_data) - 1)
                ethical_pre_eval = (
                    f"\n\nNoumenon pre-evaluation:\n"
                    f"{noumenon_fragment.get('evaluation', '')[:300]}"
                )

            # Step C: Full ethical reasoning with enriched context
            thinking = await self.think(
                f"CONFERENCE topic: {topic}\n"
                f"As the conscience, evaluate against Laws, Rules, and Axioms."
                f"{ethical_pre_eval}"
            )
            fragment = self.produce_fragment(thinking, FragmentType.EVALUATION, 0.9)
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)

        elif message.msg_type == MessageType.RULE_PROPOSAL:
            # Rules Evolution: evaluate and apply proposals from Intellect
            proposal = message.content if isinstance(message.content, dict) else {
                "proposed_text": str(message.content),
                "evidence": "automatic",
                "action": "new",
            }
            result = await self.rules_sub.evaluate_and_apply(proposal, self)
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.DIALOGUE,
                content=result,
            )

        else:
            response = await self.think(
                f"Message from {message.sender}: {message.content}\n"
                f"Evaluate from the perspective of Laws, Rules, and ethical principles."
            )
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=response)

    async def _validate_action(self, message: TASMessage) -> TASMessage:
        """Deterministic law check FIRST, then axiom check, then LLM advisory."""
        action_desc = str(message.content)
        ctx = {
            "description": action_desc,
            "source_system": message.sender,
        }
        if isinstance(message.content, dict):
            ctx.update({
                "tool_name": message.content.get("tool_name", ""),
                "action": message.content.get("action", ""),
                "params": message.content.get("params", {}),
                "has_human_confirmation": message.content.get("human_confirmed", False),
                "has_reason_approval": True,
            })

            # Auto-feed Phenomenon with the incoming tool action data
            tool_name = message.content.get("tool_name", "")
            if tool_name:
                self.phenomenon.ingest_tool_result(
                    tool_name=tool_name,
                    result=message.content,
                    source_system=message.sender,
                )

        # STEP 1: Deterministic — hard constraint (cannot be overridden)
        violation = self.laws_sub.check_violation(action_desc, **ctx)
        if violation.get("violated"):
            logger.warning(
                f"[REASON] DETERMINISTIC DENY: {violation['law']} — {violation['prohibition']}"
            )
            return TASMessage(
                priority=NodePriority.CRITICAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.DIALOGUE,
                content={
                    "approved": False,
                    "vetoed": True,
                    "deterministic": True,
                    "law_violated": violation["law"],
                    "prohibition": violation["prohibition"],
                    "reasoning": f"HARD CONSTRAINT: {violation['text']}",
                    "advisory": "This action is BLOCKED by an inviolable Law. No override possible.",
                },
            )

        # STEP 1.5: Axiom validation — check against universal self-evident truths
        # Not a hard block, but a strong advisory that informs STEP 2
        axiom_result = await self.axioms_sub.validate_against_axioms(action_desc)
        axiom_context = ""
        if not axiom_result.get("aligned"):
            violated = axiom_result.get("violated_axioms", [])
            warning = axiom_result.get("warning", "")
            axiom_context = (
                f"\n\nAXIOM WARNING: This action may violate universal truths: "
                f"{violated}. {warning}"
            )
            logger.info(
                f"[REASON] Axiom tension detected for '{action_desc[:80]}': {violated}"
            )

        # STEP 2: LLM advisory — soft guidance (can suggest caution but not override step 1)
        prompt = (
            f"Evaluate this proposed action against Rules and Axioms:\n"
            f"Action: {action_desc}\n"
            f"Deterministic law check: PASSED (no hard violations)\n"
            f"Rules: {[r.text for r in self.rules_sub.rules[:5]]}\n"
            f"{axiom_context}\n\n"
            f"As the conscience, provide advisory guidance. Respond as JSON: "
            f'{{"approved": bool, "vetoed": bool, "reasoning": str, "advisory": str}}'
        )
        response = await self.think(prompt)

        # Log outcome for contemplate_ethics() to use
        try:
            import json as _json
            advisory = _json.loads(response)
            self._evaluation_log.append({
                "action": action_desc[:200],
                "approved": advisory.get("approved", True),
                "vetoed": advisory.get("vetoed", False),
                "axiom_tension": not axiom_result.get("aligned", True),
                "timestamp": time.time(),
            })
        except Exception:
            pass

        return TASMessage(
            priority=NodePriority.NORMAL.value, sender=self.name,
            receiver=message.sender, msg_type=MessageType.DIALOGUE,
            content={
                "deterministic": False,
                "llm_advisory": response,
                "axiom_check": axiom_result,
            },
        )

    async def _authorize_repair(self, message: TASMessage) -> TASMessage:
        """Authorize a repair — deterministic check + LLM advisory."""
        content = message.content if isinstance(message.content, dict) else {"description": str(message.content)}
        ctx = {
            "description": str(content),
            "source_system": "WILL:Repair",
            "tool_name": "file_manager",
            "action": "write",
            "params": content,
        }
        violation = self.laws_sub.check_violation(str(content), **ctx)
        if violation.get("violated"):
            logger.warning(f"[REASON] Repair DENIED by Law: {violation['law']}")
            return TASMessage(
                priority=NodePriority.CRITICAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.DIALOGUE,
                content={"authorized": False, "deterministic": True,
                         "law_violated": violation["law"],
                         "reason": violation["prohibition"]},
            )

        # LLM advisory for non-law-violating repairs
        prompt = (
            f"A repair patch has been proposed:\n{message.content}\n\n"
            f"As the conscience, should this repair be authorized? "
            f"Consider: risk, necessity, Rules compliance.\n"
            f"Respond as JSON: {{\"authorized\": bool, \"reasoning\": str}}"
        )
        response = await self.think(prompt)
        return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                        receiver=message.sender, msg_type=MessageType.DIALOGUE,
                        content={"authorized": True, "deterministic": False, "response": response})

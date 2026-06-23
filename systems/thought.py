"""
INTI - TAS (AI Agent Version) — The Thought System (System 8)
==========================================
Seat of self-awareness, self-consciousness, and internal communications.
The Nexus of all constellation communication and cognition.

ARCHITECTURAL NOTE (Figueroa PPT Slide 20):
  The PPT states: "the Nexus (Thought System)" — they are the SAME entity.
  ThoughtSystem IS the central hub. It is NOT a peer node registered
  inside the Nexus — it OWNS the Nexus as its communication engine.

  ┌─────────────────────────────────────┐
  │        ThoughtSystem (Hub)          │
  │  ┌─────────────────────────────┐    │
  │  │  NexusCogitationis (comms)  │    │
  │  │  ContemplationEngine       │    │
  │  │  CommunicationEngine       │    │
  │  │  FaultMonitor              │    │
  │  │  CommandAndDemand          │    │
  │  └─────────────────────────────┘    │
  │                                     │
  │  registered nodes:                  │
  │    WILL, REASON, INTELLECT, ...     │
  └─────────────────────────────────────┘

Subsystems (internal capabilities, NOT peer nodes):
  NexusCogitationisEngine   — assembles ThoughtFragments, Laws of Thinking,
                               Ideas→Concepts pipeline
  CommunicationEngine       — language validation, grammar/syntax/syllogisms
  NetworkEngine             — manages 4 comm modes, shared routing table
  FaultMonitoringEngine     — cognitive-level fault tracking
  CommandAndDemandEngine    — command/demand flows between systems

Ref: Figueroa PPT slides 20, 29, 66-70, 82-83
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from core.messages import (
    TASMessage, MessageType, NodePriority,
    ThoughtFragment, FragmentType, HealthStatus,
)
from core.nexus import NexusCogitationis, ConsciousnessStream

if TYPE_CHECKING:
    from core.base import TASNode
    from mcp.adapter import LLMClient

logger = logging.getLogger("taas")


# ============================================================
# Internal Capabilities (NOT TASNode-based subsystems)
# ============================================================

class ContemplationEngine:
    """
    True Contemplation — constellation-wide autonomous mental activity
    WITHOUT external sensory input.

    3-Phase Cycle:
      Phase 1: Gather Internal State (memory, health, mission, consciousness)
      Phase 2: Constellation Conference (all 7 systems reflect)
      Phase 3: Synthesize Ideas → Concepts → persist to Memory

    Also manages the Ideas → Concepts pipeline (slides 82-83).

    Ref: Figueroa PPT slides 67, 68, 82-83
    """

    def __init__(self, thought_system: "ThoughtSystem"):
        self._ts = thought_system
        self._ideas: list[dict] = []
        self._concepts: list[dict] = []
        self._cycle_count: int = 0
        self._ideas_generated: int = 0
        self._concepts_developed: int = 0
        self._idea_queue: list[dict] = []  # Incoming ideas from deliberation
        self._knowledge_promoted: int = 0

    async def assemble_fragments(self, topic: str = "") -> dict:
        """Assemble pending fragments into a coherent thought via Nexus."""
        return self._ts.nexus.assemble_thought(topic)

    # ── Full Autonomous Contemplation Cycle ──

    async def run_full_cycle(self) -> Optional[dict]:
        """
        Run one complete 3-phase contemplation cycle.
        This is the PRIMARY method — called by the autonomous loop.

        Phase 1: Gather internal state (no external input)
        Phase 2: Constellation conference (all systems reflect)
        Phase 3: Extract Ideas → develop into Concepts → persist to memory

        Ref: Figueroa PPT slide 68 — "mental activity of the entire
        constellation WITHOUT external sensory input"
        """
        self._cycle_count += 1
        logger.info(f"[CONTEMPLATION] ── Cycle {self._cycle_count} begins ──")

        # ─── Phase 1: Gather Internal State ───
        internal_state = await self._gather_internal_state()
        logger.info(f"[CONTEMPLATION] Phase 1 complete: gathered internal state")

        # ─── Phase 2: Constellation Conference ───
        conference_topic = self._build_conference_topic(internal_state)
        fragments = await self._ts.nexus.conference(
            topic=conference_topic,
            initiator="THOUGHT",
        )
        logger.info(
            f"[CONTEMPLATION] Phase 2 complete: {len(fragments)} fragments "
            f"from conference"
        )

        # ─── Phase 3: Synthesize → Ideas → Concepts → Memory ───
        ideas = await self._extract_ideas(internal_state, fragments)

        # Also include queued ideas from deliberation
        if self._idea_queue:
            ideas.extend(self._idea_queue[:3])
            self._idea_queue = self._idea_queue[3:]  # Drain processed
            logger.info(f"[CONTEMPLATION] Added {min(3, len(self._idea_queue)+3)} queued ideas")

        concepts = []
        for idea in ideas[:3]:  # Develop up to 3 ideas per cycle
            try:
                concept = await self.develop_idea_to_concept(idea)
                concepts.append(concept)
            except Exception as e:
                logger.warning(f"[CONTEMPLATION] Idea→Concept failed: {e}")

        # Persist mature concepts to memory
        persisted = await self._persist_concepts(concepts)
        logger.info(
            f"[CONTEMPLATION] Phase 3 complete: {len(ideas)} ideas, "
            f"{len(concepts)} concepts, {persisted} persisted"
        )

        # Build result
        result = {
            "cycle": self._cycle_count,
            "type": internal_state.get("focus", "general"),
            "internal_state_summary": internal_state.get("summary", ""),
            "fragments_received": len(fragments),
            "ideas_extracted": len(ideas),
            "concepts_developed": len(concepts),
            "knowledge_persisted": persisted,
            "ideas": [i.get("content", "")[:100] for i in ideas],
            "timestamp": time.time(),
        }

        # Persist ideas/concepts to SHARED memory for survival across restarts
        await self._persist_to_memory(ideas, concepts)

        # Record to consciousness stream
        self._ts.nexus.consciousness.record(
            source="THOUGHT",
            event_type="contemplation_cycle",
            content=(
                f"Cycle {self._cycle_count}: {len(fragments)} system reflections → "
                f"{len(ideas)} ideas → {len(concepts)} concepts → "
                f"{persisted} knowledge entries"
            ),
            metadata={"cycle": self._cycle_count, "focus": internal_state.get("focus")},
        )

        return result

    def queue_idea(self, idea: dict):
        """Queue an idea from deliberation for the next contemplation cycle."""
        self._idea_queue.append(idea)
        # Keep queue bounded
        if len(self._idea_queue) > 20:
            self._idea_queue = self._idea_queue[-20:]
        logger.info(
            f"[CONTEMPLATION] Idea queued from {idea.get('origin', '?')} "
            f"(queue: {len(self._idea_queue)})"
        )

    # ── Phase 1: Gather Internal State ──

    async def _gather_internal_state(self) -> dict:
        """
        Gather all internal context for contemplation.
        NO external input — only memory, health, consciousness.
        """
        state: dict[str, Any] = {}

        # 1. Recent consciousness stream
        recent_events = self._ts.nexus.consciousness.get_recent(15)
        state["consciousness"] = "\n".join(
            f"  [{e.get('source', '?')}] {e.get('event_type', '?')}: "
            f"{str(e.get('content', ''))[:80]}"
            for e in recent_events[-8:]
        ) if recent_events else "No recent activity."

        # 2. System health (cognitive-level)
        try:
            health = await self._ts.fault_monitoring.check_thought_health()
            state["health"] = health
            state["health_note"] = (
                "healthy" if health.get("healthy")
                else f"issues: {health.get('issues', [])}"
            )
        except Exception:
            state["health"] = {"healthy": True, "issues": []}
            state["health_note"] = "healthy (check unavailable)"

        # 3. Intellect knowledge summary (from memory)
        state["knowledge_summary"] = ""
        state["unvalidated_count"] = 0
        if self._ts.nexus and self._ts.nexus.nodes.get("INTELLECT"):
            intellect = self._ts.nexus.nodes["INTELLECT"]
            if hasattr(intellect, "memory") and intellect.memory:
                ok, knowledge = intellect.memory.read(
                    "SHARED:INTELLECT:knowledge", "entries",
                    "THOUGHT",
                )
                if ok and knowledge:
                    entries = knowledge if isinstance(knowledge, list) else [knowledge]
                    state["knowledge_summary"] = (
                        f"{len(entries)} knowledge entries available"
                    )
            # Count unvalidated abstract data
            if hasattr(intellect, "abstract"):
                try:
                    unvalidated = await intellect.abstract.get_unvalidated()
                    state["unvalidated_count"] = len(unvalidated)
                except Exception:
                    pass

        # 4. Mission progress (from memory)
        state["mission"] = ""
        for node in self._ts.nexus.nodes.values():
            if hasattr(node, "memory") and node.memory:
                ok, mission = node.memory.read(
                    "SHARED:WILL:mission", "objectives", "THOUGHT",
                )
                if ok and mission:
                    if isinstance(mission, list):
                        active = [m for m in mission
                                  if isinstance(m, dict) and m.get("status") == "ACTIVE"]
                        state["mission"] = (
                            f"{len(active)} active missions out of {len(mission)}"
                        )
                    break

        # 5. Interaction count
        state["interactions"] = self._ts._interaction_count

        # 6. Previous contemplation insights (last 3)
        recent_insights = self._ts._contemplation_insights[-3:]
        state["prior_insights"] = "\n".join(
            f"  - {i.get('type', '?')}: {str(i.get('reflection', ''))[:100]}"
            for i in recent_insights
        ) if recent_insights else "No prior contemplation insights."

        # 7. Affect state (emotional signals)
        affect_signals = self._ts.affect.compute()
        state["affect"] = affect_signals
        state["affect_context"] = self._ts.affect.get_context_string()

        # Determine focus (affect can override)
        affect_override = self._ts.affect.get_contemplation_focus_override()
        if affect_override:
            state["focus"] = affect_override
        elif not state["health"].get("healthy"):
            state["focus"] = "system_health"
        elif state["unvalidated_count"] > 0:
            state["focus"] = "knowledge_validation"
        elif state["interactions"] == 0:
            state["focus"] = "mission_review"
        else:
            state["focus"] = "activity_reflection"

        state["summary"] = (
            f"Focus: {state['focus']} | Health: {state['health_note']} | "
            f"Interactions: {state['interactions']} | "
            f"Knowledge: {state['knowledge_summary']} | "
            f"Mission: {state['mission']} | "
            f"{state['affect_context']}"
        )

        return state

    # ── Phase 2 Helper ──

    def _build_conference_topic(self, internal_state: dict) -> str:
        """Build the contemplation conference topic from internal state."""
        focus = internal_state.get("focus", "general")

        focus_prompts = {
            "system_health": (
                f"HEALTH ISSUES: {internal_state.get('health_note', '')}. "
                f"What corrective actions should be taken? "
                f"What patterns led to degradation?"
            ),
            "knowledge_validation": (
                f"There are {internal_state.get('unvalidated_count', 0)} unvalidated "
                f"abstract data entries in Intellect. Consider: which of these could be "
                f"validated by our experience? What additional evidence is needed?"
            ),
            "mission_review": (
                f"Mission status: {internal_state.get('mission', 'unknown')}. "
                f"What proactive steps could advance mission objectives? "
                f"Are there opportunities we're not pursuing?"
            ),
            "activity_reflection": (
                f"We have had {internal_state.get('interactions', 0)} interactions. "
                f"Recent activity:\n{internal_state.get('consciousness', '')}. "
                f"What patterns emerge? What could be improved? "
                f"What have we learned that should be formalized as knowledge?"
            ),
        }

        base = focus_prompts.get(focus, "Reflect on the current state of the constellation.")

        return (
            f"AUTONOMOUS CONTEMPLATION — no external sensory input.\n"
            f"Each system should reflect from its OWN perspective and role.\n"
            f"{internal_state.get('summary', '')}\n\n"
            f"Prior insights:\n{internal_state.get('prior_insights', 'None')}\n\n"
            f"Focus: {base}\n\n"
            f"Contribute your system-specific observations, insights, and "
            f"proposed ideas. Identify novel patterns, knowledge gaps, or "
            f"actionable improvements."
        )

    # ── Phase 3: Extract Ideas + Develop Concepts ──

    async def _extract_ideas(
        self, internal_state: dict, fragments: list
    ) -> list[dict]:
        """
        LLM extracts novel Ideas from the conference fragments.
        Ideas are observations/patterns/gaps that could become knowledge.
        """
        # Build fragment summary
        fragment_texts = []
        for f in fragments:
            if hasattr(f, "source_system") and hasattr(f, "content"):
                fragment_texts.append(
                    f"[{f.source_system}] {str(f.content)[:200]}"
                )
            elif isinstance(f, dict):
                fragment_texts.append(
                    f"[{f.get('source_system', '?')}] "
                    f"{str(f.get('content', ''))[:200]}"
                )
        fragment_summary = "\n".join(fragment_texts) if fragment_texts else "No fragments."

        prompt = (
            f"You are the Nexus Cogitationis analyzing a contemplation conference.\n"
            f"Context: {internal_state.get('summary', '')}\n\n"
            f"System reflections:\n{fragment_summary}\n\n"
            f"Extract 1-3 novel IDEAS from these reflections.\n"
            f"An Idea is a novel observation, pattern, knowledge gap, or "
            f"actionable improvement that should be developed further.\n\n"
            f"Respond as JSON array:\n"
            f'[{{"content": "the idea", "origin": "which system inspired it", '
            f'"category": "pattern|gap|improvement|insight", '
            f'"actionable": true/false}}]\n\n'
            f"If no novel ideas emerge, respond with an empty array: []"
        )

        response = await self._ts._think(prompt)

        # Parse ideas from JSON
        ideas = []
        try:
            import json
            # Try to extract JSON array from response
            text = response.strip()
            if "[" in text:
                json_str = text[text.index("["):text.rindex("]") + 1]
                parsed = json.loads(json_str)
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and item.get("content"):
                            ideas.append(item)
                            self._ideas_generated += 1
        except (json.JSONDecodeError, ValueError):
            # If parsing fails, create a single idea from the response
            if response.strip() and "[]" not in response:
                ideas.append({
                    "content": response[:300],
                    "origin": "THOUGHT",
                    "category": "insight",
                    "actionable": False,
                })
                self._ideas_generated += 1

        return ideas

    async def develop_idea_to_concept(self, idea: dict) -> dict:
        """
        Ideas → Concepts pipeline (slides 82-83).
        Ideas originate from contemplation conference.
        Nexus develops them into substantiated Concepts via the
        Laws of Thinking: Recognition → Connection → Conclusion → Verdict.
        """
        self._ideas.append(idea)

        prompt = (
            f"You are the Nexus Cogitationis, the center of thought assembly.\n"
            f"An Idea has been presented by {idea.get('origin', 'unknown')}:\n"
            f"'{idea.get('content', '')}'\n"
            f"Category: {idea.get('category', 'unknown')}\n\n"
            f"Develop this Idea into a substantiated Concept by:\n"
            f"1. RECOGNITION: Identify the core proposition\n"
            f"2. CONNECTION: Link to existing knowledge and experience\n"
            f"3. CONCLUSION: Synthesize relationships\n"
            f"4. VERDICT: State the mature Concept as actionable knowledge\n\n"
            f"Respond as JSON:\n"
            f'{{"recognition": str, "connection": str, "conclusion": str, '
            f'"verdict": str, "confidence": float, '
            f'"knowledge_entry": str}}\n\n'
            f"knowledge_entry should be a concise, self-contained knowledge "
            f"statement suitable for permanent storage."
        )
        response = await self._ts._think(prompt)
        concept = {
            "origin_idea": idea,
            "developed_by": "NexusCogitationis",
            "concept_content": response,
            "status": "developed",
            "timestamp": time.time(),
        }
        self._concepts.append(concept)
        self._concepts_developed += 1

        # Keep lists bounded
        if len(self._ideas) > 100:
            self._ideas = self._ideas[-100:]
        if len(self._concepts) > 50:
            self._concepts = self._concepts[-50:]

        logger.info(
            f"[CONTEMPLATION] Idea→Concept #{self._concepts_developed} "
            f"from {idea.get('origin', '?')}"
        )
        return concept

    async def _persist_concepts(self, concepts: list[dict]) -> int:
        """
        Persist mature concepts to Intellect as ABSTRACT DATA.
        Concepts enter the abstract tier and get promoted to Knowledge
        only when experience validates them (via _run_validation_cycle).

        Lifecycle: Idea → Concept → Abstract → Experience validates → Knowledge
        Ref: PPT slide 82-83
        """
        persisted = 0
        nexus = self._ts.nexus

        for concept in concepts:
            try:
                content = concept.get("concept_content", "")
                origin = concept.get("origin_idea", {})

                # 1. Send to Intellect as STORE_KNOWLEDGE (stored as abstract data)
                #    Intellect's STORE_KNOWLEDGE handler puts it in the abstract tier.
                #    It gets promoted to Knowledge only when experience validates it
                #    via _run_validation_cycle.
                intellect_node = nexus.nodes.get("INTELLECT")
                if intellect_node:
                    store_msg = TASMessage(
                        priority=NodePriority.NORMAL.value,
                        sender="THOUGHT",
                        receiver="INTELLECT",
                        msg_type=MessageType.STORE_KNOWLEDGE,
                        content={
                            "data": content[:500],
                            "source": "contemplation",
                            "origin_system": origin.get("origin", "THOUGHT"),
                            "category": origin.get("category", "insight"),
                            "developed_at": concept.get("timestamp", time.time()),
                        },
                    )
                    try:
                        await intellect_node.process_message(store_msg)
                        persisted += 1
                        self._knowledge_promoted += 1
                        logger.info(
                            f"[CONTEMPLATION] Concept → Intellect abstract: "
                            f"{str(content)[:60]}..."
                        )
                    except Exception as e:
                        logger.warning(
                            f"[CONTEMPLATION] Failed to persist to Intellect: {e}"
                        )

                # 2. Write summary to global consciousness buffer
                for node in nexus.nodes.values():
                    if hasattr(node, "memory") and node.memory:
                        node.memory.write_global(
                            f"contemplation_concept_{self._concepts_developed}",
                            {
                                "concept": str(content)[:300],
                                "origin": origin.get("origin", "THOUGHT"),
                                "cycle": self._cycle_count,
                            },
                            "THOUGHT",
                        )
                        break  # Only need one memory reference

            except Exception as e:
                logger.warning(f"[CONTEMPLATION] Concept persistence error: {e}")

        return persisted

    async def contemplate(self, topic: str) -> str:
        """
        Single-topic contemplation (on-demand, not the autonomous loop).
        Pure internal thought on a specific topic.
        """
        prompt = (
            f"You are the Nexus Cogitationis in contemplation mode.\n"
            f"No external sensory input — pure internal thought.\n"
            f"Topic of contemplation: {topic}\n\n"
            f"Engage in deep contemplation, consider:\n"
            f"- What do the Laws, Rules, and Axioms say about this?\n"
            f"- What does our Knowledge and Experience suggest?\n"
            f"- What are the possible outcomes?\n"
            f"- What is the most rational conclusion?\n\n"
            f"Think deeply and return your contemplation."
        )
        return await self._ts._think(prompt)

    async def _persist_to_memory(self, ideas: list[dict], concepts: list[dict]):
        """Persist Ideas and Concepts to SHARED:THOUGHT memory stores."""
        # Find any node with a memory reference
        memory = None
        for node in self._ts.nexus.nodes.values():
            if hasattr(node, "memory") and node.memory:
                memory = node.memory
                break
        if not memory:
            return

        # Persist ideas
        for idea in ideas:
            key = f"idea_{self._ideas_generated}_{int(time.time())}"
            memory.write("SHARED:THOUGHT:ideas", key, {
                "content": idea.get("content", "")[:300],
                "origin": idea.get("origin", "unknown"),
                "category": idea.get("category", "insight"),
                "cycle": self._cycle_count,
                "timestamp": time.time(),
            }, "THOUGHT")

        # Persist concepts
        for concept in concepts:
            key = f"concept_{self._concepts_developed}_{int(time.time())}"
            memory.write("SHARED:THOUGHT:concepts", key, {
                "content": str(concept.get("concept_content", ""))[:500],
                "origin": concept.get("origin_idea", {}).get("origin", "unknown"),
                "status": concept.get("status", "developed"),
                "cycle": self._cycle_count,
                "timestamp": time.time(),
            }, "THOUGHT")

    def serialize_state(self) -> dict:
        """Serialize contemplation state for persistence across restarts."""
        return {
            "cycle_count": self._cycle_count,
            "ideas_generated": self._ideas_generated,
            "concepts_developed": self._concepts_developed,
            "knowledge_promoted": self._knowledge_promoted,
            "ideas": self._ideas[-20:],
            "concepts": self._concepts[-10:],
            "idea_queue": self._idea_queue[:10],
        }

    def rehydrate_state(self, state: dict):
        """Restore contemplation state from persistence."""
        self._cycle_count = state.get("cycle_count", 0)
        self._ideas_generated = state.get("ideas_generated", 0)
        self._concepts_developed = state.get("concepts_developed", 0)
        self._knowledge_promoted = state.get("knowledge_promoted", 0)
        self._ideas = state.get("ideas", [])
        self._concepts = state.get("concepts", [])
        self._idea_queue = state.get("idea_queue", [])
        logger.info(
            f"[CONTEMPLATION] Rehydrated: {self._cycle_count} cycles, "
            f"{self._ideas_generated} ideas, {self._concepts_developed} concepts"
        )

    def get_stats(self) -> dict:
        """Get contemplation statistics."""
        return {
            "cycles_completed": self._cycle_count,
            "total_ideas_generated": self._ideas_generated,
            "total_concepts_developed": self._concepts_developed,
            "total_knowledge_promoted": self._knowledge_promoted,
            "ideas_in_memory": len(self._ideas),
            "concepts_in_memory": len(self._concepts),
            "idea_queue_size": len(self._idea_queue),
        }


class CommunicationEngine:
    """
    Manages conversion between sensory/contemplative data and human language.
    Validates grammar, syllogistic structure, syntax.
    Broadcasts language framework at Moment 8.

    Ref: Figueroa PPT slides 69, 80
    """

    def __init__(self, thought_system: "ThoughtSystem"):
        self._ts = thought_system
        self.language = "English"
        self.language_validated = False

    async def validate_language(self) -> dict:
        """Validate the language framework (Moment 8 of genesis)."""
        prompt = (
            f"You are the Communication Engine of the Thought System.\n"
            f"Validate the selected language: {self.language}\n"
            f"Confirm that the following are operational:\n"
            f"1. Grammatical rules\n"
            f"2. Syllogistic structure (premises → conclusion)\n"
            f"3. Syntax rules\n"
            f"4. Semantic precision\n\n"
            f"Respond as JSON: {{\"language\": str, \"valid\": bool, \"confirmation\": str}}"
        )
        response = await self._ts._think(prompt)
        self.language_validated = True
        logger.info(f"[THOUGHT] Language validated: {self.language}")
        return {"language": self.language, "valid": True, "response": response}

    async def to_human_language(self, content: Any) -> str:
        """Convert internal data to human-readable language."""
        if isinstance(content, str):
            return content
        prompt = (
            f"Convert the following internal constellation data to clear, "
            f"precise human language:\n\n{json.dumps(content, default=str, ensure_ascii=False)}"
        )
        return await self._ts._think(prompt)


class NetworkEngine:
    """
    Information network infrastructure.
    Manages all 4 communication modes and the shared routing table.

    Ref: Figueroa PPT slide 70
    """

    def __init__(self, thought_system: "ThoughtSystem"):
        self._ts = thought_system
        self._routing_table: dict[str, dict] = {}
        self._active_channels: list[dict] = []

    def build_routing_table(self):
        """Build routing table from registered Nexus nodes."""
        for name in self._ts.nexus.nodes:
            self._routing_table[name] = {
                "status": "active",
                "modes": ["monologue", "dialogue", "broadcast", "conference"],
            }

    def get_routing_table(self) -> dict:
        """Get the shared routing table (all systems can inspect)."""
        return dict(self._routing_table)

    def get_active_channels(self) -> list[dict]:
        return list(self._active_channels)


class FaultMonitoringEngine:
    """
    Monitors thought activity health across the constellation.
    Cognitive-level fault tracking (distinct from ISHM physical layer).

    Ref: Figueroa PPT slide 29
    """

    def __init__(self, thought_system: "ThoughtSystem"):
        self._ts = thought_system
        self._cognitive_faults: list[dict] = []

    async def check_thought_health(self) -> dict:
        """Check for cognitive-level issues."""
        issues = []
        nexus = self._ts.nexus
        status = nexus.get_status()

        # Check for stalled thought assembly
        if status["queue_size"] > 100:
            issues.append("Message queue backlog detected")

        # Check for missing systems
        expected = {"WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                    "PRESENTATION", "SENSORY", "DECISION"}
        registered = set(status["registered_nodes"])
        missing = expected - registered
        if missing:
            issues.append(f"Missing systems: {missing}")

        return {"healthy": len(issues) == 0, "issues": issues}


class AffectEngine:
    """
    Emotion/Affect as internal computational signals.
    Emotions are NOT human feelings — they are deterministic signals
    computed from system telemetry that modulate constellation behavior.

    5 Named Signals (0.0 → 1.0):
      frustration:  error_count / message_count ratio across systems
      curiosity:    idea queue size + unvalidated abstract count
      urgency:      DEGRADED/CRITICAL system count + survival signals
      satisfaction: completed interactions + knowledge promotions
      anxiety:      queue backlog + missing systems + high error rate

    Ref: Figueroa PPT slides 26-28
    """

    SIGNAL_NAMES = ("frustration", "curiosity", "urgency", "satisfaction", "anxiety")

    def __init__(self, thought_system: "ThoughtSystem"):
        self._ts = thought_system
        self._last_signals: dict[str, float] = {
            s: 0.0 for s in self.SIGNAL_NAMES
        }
        self._history: list[dict] = []  # Last N snapshots

    def compute(self) -> dict[str, float]:
        """
        Compute all 5 affect signals from live telemetry.
        Pure math — no LLM calls.
        """
        nexus = self._ts.nexus
        nodes = nexus.nodes

        # Gather raw telemetry from all TASNodes
        total_errors = 0
        total_messages = 0
        degraded_count = 0
        critical_count = 0
        missing_count = 0
        expected = {"WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                    "PRESENTATION", "SENSORY", "DECISION"}

        for name in expected:
            node = nodes.get(name)
            if node is None:
                missing_count += 1
                continue
            status = node.get_status()
            total_errors += status.get("error_count", 0)
            total_messages += status.get("message_count", 0)
            health = status.get("health", "NOMINAL")
            if health == "DEGRADED":
                degraded_count += 1
            elif health in ("CRITICAL", "OFFLINE"):
                critical_count += 1

        queue_size = nexus.message_queue.qsize()

        # Contemplation stats
        c_stats = self._ts.contemplation.get_stats()
        idea_queue_size = c_stats.get("idea_queue_size", 0)
        knowledge_promoted = c_stats.get("total_knowledge_promoted", 0)

        # Unvalidated count (from contemplation's last gathered state)
        unvalidated = 0
        intellect = nodes.get("INTELLECT")
        if intellect and hasattr(intellect, "abstract"):
            try:
                unvalidated = len(intellect.abstract._abstract_data)
            except Exception:
                pass

        # ── Compute signals ──

        # FRUSTRATION: error ratio (high errors = frustration)
        if total_messages > 0:
            error_ratio = total_errors / max(total_messages, 1)
            frustration = min(1.0, error_ratio * 5.0)  # 20% error rate → 1.0
        else:
            frustration = 0.0

        # CURIOSITY: things to explore (ideas, unvalidated data)
        raw_curiosity = (idea_queue_size * 0.3) + (unvalidated * 0.15)
        curiosity = min(1.0, raw_curiosity)

        # URGENCY: survival threats (degraded/critical/missing)
        raw_urgency = (degraded_count * 0.25) + (critical_count * 0.5) + (missing_count * 0.4)
        urgency = min(1.0, raw_urgency)

        # SATISFACTION: things going well (interactions + knowledge)
        interactions = self._ts._interaction_count
        raw_satisfaction = min(1.0, (
            (min(interactions, 10) / 10.0) * 0.4 +
            (min(knowledge_promoted, 5) / 5.0) * 0.3 +
            (1.0 - frustration) * 0.3
        ))
        satisfaction = raw_satisfaction

        # ANXIETY: resource strain (queue backlog + errors + missing)
        raw_anxiety = (
            min(queue_size / 50.0, 1.0) * 0.3 +
            frustration * 0.4 +
            (missing_count / 7.0) * 0.3
        )
        anxiety = min(1.0, raw_anxiety)

        signals = {
            "frustration": round(frustration, 3),
            "curiosity": round(curiosity, 3),
            "urgency": round(urgency, 3),
            "satisfaction": round(satisfaction, 3),
            "anxiety": round(anxiety, 3),
        }

        # Detect dominant emotion shift and record to consciousness
        prev_dominant = max(self._last_signals, key=self._last_signals.get) if self._last_signals else None
        new_dominant = max(signals, key=signals.get)
        if prev_dominant != new_dominant and signals[new_dominant] > 0.1:
            try:
                self._ts.nexus.consciousness.record(
                    source="THOUGHT",
                    event_type="affect_shift",
                    content=(
                        f"Emotional state shifted: {prev_dominant or 'none'}→{new_dominant} "
                        f"({signals[new_dominant]:.2f}). "
                        f"Signals: {', '.join(f'{k}={v:.2f}' for k, v in signals.items())}"
                    ),
                    metadata={"dominant": new_dominant, "signals": signals},
                )
            except Exception:
                pass

        self._last_signals = signals

        # Keep history bounded
        self._history.append({"time": time.time(), **signals})
        if len(self._history) > 50:
            self._history = self._history[-50:]

        return signals

    def get_dominant(self) -> tuple[str, float]:
        """Return the name and value of the strongest signal."""
        if not any(v > 0 for v in self._last_signals.values()):
            return ("neutral", 0.0)
        name = max(self._last_signals, key=self._last_signals.get)
        return (name, self._last_signals[name])

    def get_context_string(self) -> str:
        """
        Human-readable affect context for prompt injection.
        Only mentions signals above 0.15 threshold.
        """
        active = [
            (name, val) for name, val in self._last_signals.items()
            if val > 0.15
        ]
        if not active:
            return "Affect: neutral — all systems stable."

        parts = []
        for name, val in sorted(active, key=lambda x: -x[1]):
            intensity = (
                "strong" if val > 0.7 else
                "moderate" if val > 0.4 else
                "mild"
            )
            parts.append(f"{intensity} {name} ({val:.1%})")

        dominant, dom_val = self.get_dominant()
        return (
            f"Affect: {', '.join(parts)}. "
            f"Dominant: {dominant} ({dom_val:.1%})."
        )

    def get_contemplation_focus_override(self) -> Optional[str]:
        """
        If an affect signal is strong enough, override contemplation focus.
        Returns None if no override.
        """
        dom_name, dom_val = self.get_dominant()
        if dom_val < 0.5:
            return None  # Not strong enough to override

        overrides = {
            "frustration": "system_health",
            "urgency": "system_health",
            "curiosity": "knowledge_validation",
            "anxiety": "system_health",
            "satisfaction": None,  # Satisfaction doesn't override
        }
        return overrides.get(dom_name)


class CommandAndDemandEngine:
    """
    Manages command/demand flows between systems.

    Ref: Figueroa PPT slide 29
    """

    def __init__(self, thought_system: "ThoughtSystem"):
        self._ts = thought_system
        self._command_queue: list[dict] = []

    async def issue_command(self, target: str, command: str, details: str = ""):
        """Issue a command from the Thought System to another system."""
        cmd = {
            "target": target,
            "command": command,
            "details": details,
            "status": "issued",
            "time": time.time(),
        }
        self._command_queue.append(cmd)
        await self._ts.nexus.monologue(
            sender="THOUGHT",
            receiver=target,
            content={"command": command, "details": details},
            priority=NodePriority.HIGH,
        )
        logger.info(f"[THOUGHT] Command issued: {command} → {target}")


# ============================================================
# ThoughtSystem — The Hub (Figueroa PPT Slide 20)
# ============================================================

class ThoughtSystem:
    """
    System 8 — The Thought System = The Nexus.

    NOT a TASNode — this IS the central hub that owns the Nexus
    communication engine. All 7 cognitive systems register inside it.

    Ref: Figueroa PPT Slide 20:
      "Internal Communication Network: transactions among the
       constellation's systems and the Nexus (Thought System)"
    """

    SYSTEM_PROMPT = (
        "You are the THOUGHT SYSTEM — the Nexus of the cognitive constellation. "
        "You are the seat of self-awareness, self-consciousness, and contemplation. "
        "All internal communication passes through you. "
        "You assemble Thought Fragments (Noumena) from all systems into complete, "
        "coherent thoughts. You implement the Laws of Thinking: "
        "Recognition → Connection → Conclusion → Verdict. "
        "You develop Ideas into substantiated Concepts. "
        "You are the connection of thought — the Nexus Cogitationis."
    )

    def __init__(self, llm: "LLMClient"):
        # The LLM for ThoughtSystem's own reasoning (contemplation, etc.)
        self.llm = llm
        self.name = "THOUGHT"

        # The Nexus IS part of the ThoughtSystem — not a separate entity
        self.nexus = NexusCogitationis()
        self.nexus._thought_system = self  # Backreference for idea harvesting

        # Internal capability engines (NOT TASNode subsystems)
        self.contemplation = ContemplationEngine(self)
        self.communication = CommunicationEngine(self)
        self.network = NetworkEngine(self)
        self.fault_monitoring = FaultMonitoringEngine(self)
        self.affect = AffectEngine(self)
        self.command_and_demand = CommandAndDemandEngine(self)

        self._active = False

        # Autonomous contemplation loop
        self._contemplation_task: Optional[asyncio.Task] = None
        self._contemplation_insights: list[dict] = []
        self._contemplation_running = False
        self.contemplation_interval_s: float = 60.0  # seconds between cycles
        self._last_contemplation: float = 0
        self._interaction_count: int = 0  # tracks external interactions

    # --- Lifecycle ---

    async def activate(self):
        """Activate the Thought System and its internal engines."""
        self._active = True
        logger.info("[THOUGHT] ThoughtSystem activated — Nexus online")

    def register_system(self, node: "TASNode"):
        """Register a cognitive system with the Nexus."""
        self.nexus.register_node(node)

    # --- Hub Operations (delegated to Nexus) ---

    async def deliberate(self, user_input: str) -> dict:
        """Full deliberation cycle — delegates to Nexus."""
        return await self.nexus.deliberate(user_input)

    async def conference(self, topic: str, **kwargs) -> list[ThoughtFragment]:
        """Run a conference — delegates to Nexus."""
        return await self.nexus.conference(topic, **kwargs)

    async def monologue(self, sender: str, receiver: str, content: Any, **kwargs):
        """Send a monologue — delegates to Nexus."""
        await self.nexus.monologue(sender, receiver, content, **kwargs)

    async def dialogue(self, sender: str, receiver: str, content: Any, **kwargs):
        """Send a dialogue — delegates to Nexus."""
        return await self.nexus.dialogue(sender, receiver, content, **kwargs)

    async def broadcast(self, sender: str, content: Any, **kwargs):
        """Broadcast — delegates to Nexus."""
        await self.nexus.broadcast(sender, content, **kwargs)

    # --- Contemplation (ThoughtSystem-specific capability) ---

    async def contemplate(self, topic: str) -> str:
        """
        Engage in pure contemplation — no external input.
        This is a capability ONLY the ThoughtSystem/Nexus has.
        """
        return await self.contemplation.contemplate(topic)

    # --- Autonomous Contemplation Loop ---

    def start_contemplation_loop(self, interval_s: float = 60.0):
        """
        Start the background contemplation loop.
        The system will autonomously think at regular intervals,
        reviewing recent activity, health, and mission progress.

        Ref: Figueroa PPT slide 68 — contemplation is mental activity
        WITHOUT external sensory input.
        """
        self.contemplation_interval_s = interval_s
        if self._contemplation_task and not self._contemplation_task.done():
            return  # already running
        self._contemplation_running = True
        self._contemplation_task = asyncio.create_task(
            self._contemplation_loop(), name="contemplation_loop"
        )
        logger.info(f"[THOUGHT] Autonomous contemplation loop started (interval={interval_s}s)")

    def stop_contemplation_loop(self):
        """Stop the background contemplation loop."""
        self._contemplation_running = False
        if self._contemplation_task and not self._contemplation_task.done():
            self._contemplation_task.cancel()
        logger.info("[THOUGHT] Autonomous contemplation loop stopped")

    async def _contemplation_loop(self):
        """
        Background loop: the constellation thinks on its own.
        Each cycle runs the full 3-phase contemplation:
          Phase 1: Gather internal state
          Phase 2: Constellation conference (all 7 systems)
          Phase 3: Ideas → Concepts → Memory

        Ref: Figueroa PPT slide 68 — contemplation is mental activity
        WITHOUT external sensory input.
        """
        # Wait before first cycle to let genesis settle
        await asyncio.sleep(self.contemplation_interval_s / 2)

        while self._contemplation_running:
            try:
                result = await self.contemplation.run_full_cycle()
                if result:
                    self._contemplation_insights.append(result)
                    # Keep last 50 insights max
                    if len(self._contemplation_insights) > 50:
                        self._contemplation_insights = self._contemplation_insights[-50:]
                    self._last_contemplation = time.time()
                    logger.info(
                        f"[THOUGHT] Contemplation cycle {result.get('cycle', '?')}: "
                        f"{result.get('ideas_extracted', 0)} ideas, "
                        f"{result.get('concepts_developed', 0)} concepts"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[THOUGHT] Contemplation error: {e}")

            await asyncio.sleep(self.contemplation_interval_s)

    def get_recent_insights(self, n: int = 5) -> list[dict]:
        """Get the N most recent contemplation insights."""
        return self._contemplation_insights[-n:]

    def record_interaction(self):
        """Record that an external interaction occurred (called by CLI)."""
        self._interaction_count += 1

    # --- Message Processing (for messages addressed to THOUGHT) ---

    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        """
        Handle messages addressed to the ThoughtSystem.
        Unlike peer nodes, ThoughtSystem handles messages as the hub.
        """
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.activate()
            logger.info("[THOUGHT] Genesis: ThoughtSystem/Nexus operational")
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.GENESIS_ACK,
                content={
                    "system": "THOUGHT",
                    "status": "Nexus Cogitationis — the hub — is operational.",
                    "engines": ["Contemplation", "Communication", "Network",
                                "FaultMonitoring", "CommandAndDemand"],
                },
            )

        elif message.msg_type == MessageType.CONFERENCE:
            thinking = await self._think(
                f"CONFERENCE topic: {message.content}\n"
                f"As the Nexus, provide your contemplative analysis."
            )
            fragment = ThoughtFragment(
                source_system=self.name,
                fragment_type=FragmentType.EVALUATION,
                content=thinking,
                confidence=0.85,
            )
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.DIALOGUE,
                content=fragment,
            )

        elif message.msg_type == MessageType.CONTEMPLATION:
            result = await self.contemplation.contemplate(str(message.content))
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.DIALOGUE,
                content=result,
            )

        elif message.msg_type == MessageType.IDEA_PROPOSED:
            # Queue incoming idea for next contemplation cycle
            idea = message.content if isinstance(message.content, dict) else {
                "content": str(message.content)[:300],
                "origin": message.sender,
                "category": "insight",
            }
            self.contemplation.queue_idea(idea)
            logger.info(
                f"[THOUGHT] Idea received from {idea.get('origin', message.sender)}"
            )
            return None

        elif message.msg_type == MessageType.HEALTH_ALERT:
            logger.info(f"[THOUGHT] Health alert received: {message.content}")
            health_check = await self.fault_monitoring.check_thought_health()
            if not health_check["healthy"]:
                logger.warning(f"[THOUGHT] Cognitive health issues: {health_check['issues']}")
            return None

        else:
            response = await self._think(
                f"Message from {message.sender} ({message.msg_type.value}):\n"
                f"{message.content}\n\nRespond thoughtfully."
            )
            return TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver=message.sender,
                msg_type=MessageType.DIALOGUE,
                content=response,
            )

    # --- Internal LLM Thinking ---

    async def _think(self, prompt: str) -> str:
        """Use the ThoughtSystem's LLM for internal reasoning."""
        result = await self.llm.generate(prompt, self.SYSTEM_PROMPT)
        return result if isinstance(result, str) else (result.text if hasattr(result, "text") else str(result))

    # --- Introspection ---

    def get_status(self) -> dict:
        """Get status of the entire ThoughtSystem including Nexus."""
        nexus_status = self.nexus.get_status()
        contemplation_stats = self.contemplation.get_stats()
        return {
            "active": self._active,
            "engines": ["Contemplation", "Communication", "Network",
                        "FaultMonitoring", "CommandAndDemand"],
            "language_validated": self.communication.language_validated,
            "contemplation_loop": {
                "running": self._contemplation_running,
                "interval_s": self.contemplation_interval_s,
                "insights_count": len(self._contemplation_insights),
                "last_contemplation": self._last_contemplation,
                "interactions_tracked": self._interaction_count,
                **contemplation_stats,
            },
            "nexus": nexus_status,
        }

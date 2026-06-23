"""
INTI - TAS (AI Agent Version) — Nexus Cogitationis + Consciousness Stream
======================================================
Central communication bus for all inter-system messaging.

Implements:
  - PriorityQueue-based message dispatch
  - 4 communication modes: monologue, dialogue, broadcast, conference
  - ConsciousnessStream: immutable log of all cognition
  - Thought assembly (ThoughtFragments → coherent thought)

Ref: Figueroa PPT slides 16-20, 67-70
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from core.messages import (
    TASMessage, ThoughtFragment, MessageType,
    NodePriority, FragmentType,
)

if TYPE_CHECKING:
    from core.base import TASNode

logger = logging.getLogger("taas")


# ============================================================
# Consciousness Stream — Immutable Cognition Log
# ============================================================

class ConsciousnessStream:
    """
    Immutable log of every thought, message, and decision in the constellation.
    This is the 'internal monologue' of the system — write-once, read-many.
    """

    def __init__(self, max_entries: int = 10_000):
        self._entries: list[dict] = []
        self._max = max_entries

    def record(
        self,
        source: str,
        event_type: str,
        content: str,
        metadata: dict | None = None,
    ):
        """Record an event to the stream."""
        entry = {
            "timestamp": time.time(),
            "source": source,
            "event_type": event_type,
            "content": content[:1000],
            "metadata": metadata or {},
        }
        self._entries.append(entry)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max:]

    def get_recent(self, count: int = 20) -> list[dict]:
        """Get the N most recent entries."""
        return self._entries[-count:]

    def get_by_source(self, source: str, count: int = 10) -> list[dict]:
        """Get recent entries from a specific source."""
        return [e for e in self._entries if e["source"] == source][-count:]

    def search(self, keyword: str, count: int = 10) -> list[dict]:
        """Search stream for entries containing a keyword."""
        return [
            e for e in self._entries
            if keyword.lower() in e["content"].lower()
        ][-count:]

    def introspect(self, window: int = 50) -> str:
        """
        Generate a self-reflective summary of recent consciousness.
        Used by ContemplationEngine for genuine self-reflection.

        Ref: PPT slide 68 — "mental activity of the entire constellation"
        """
        recent = self._entries[-window:]
        if not recent:
            return "No consciousness entries yet. The constellation has just begun."

        # Count event types
        type_counts: dict[str, int] = {}
        sources: set[str] = set()
        for e in recent:
            et = e["event_type"]
            type_counts[et] = type_counts.get(et, 0) + 1
            sources.add(e["source"])

        parts = [f"Recent activity ({len(recent)} events from {', '.join(sorted(sources))}):"]

        # Deliberations
        delibs = type_counts.get("deliberation_complete", 0)
        if delibs:
            parts.append(f"- {delibs} deliberation(s) completed")

        # Learning
        learned = type_counts.get("knowledge_promoted", 0)
        if learned:
            parts.append(f"- {learned} knowledge item(s) learned")

        # Rule evolution
        evolved = type_counts.get("rule_evolved", 0)
        if evolved:
            parts.append(f"- {evolved} rule(s) evolved from experience")

        # Emotional shifts
        shifts = type_counts.get("affect_shift", 0)
        if shifts:
            last_shift = [e for e in recent if e["event_type"] == "affect_shift"][-1]
            dominant = last_shift.get("metadata", {}).get("dominant", "unknown")
            parts.append(f"- {shifts} emotional shift(s), current dominant: {dominant}")

        # Overrides
        overrides = type_counts.get("dominance_override", 0)
        if overrides:
            parts.append(f"- {overrides} survival override(s) activated")

        # Conferences
        conferences = type_counts.get("conference_start", 0)
        if conferences:
            parts.append(f"- {conferences} conference(s) held")

        # ISHM events
        ishm_events = sum(v for k, v in type_counts.items() if "ishm" in k.lower() or "fault" in k.lower() or "repair" in k.lower())
        if ishm_events:
            parts.append(f"- {ishm_events} health/repair event(s)")

        return "\n".join(parts)

    @property
    def size(self) -> int:
        return len(self._entries)


# ============================================================
# Nexus Cogitationis — Central Communication Bus
# ============================================================

class NexusCogitationis:
    """
    Central bus for all inter-system communication in the constellation.

    All messages pass through the Nexus. The Nexus:
      1. Queues messages by priority
      2. Routes to the correct system
      3. Records everything in the ConsciousnessStream
      4. Assembles ThoughtFragments into coherent thoughts

    Ref: Figueroa PPT slides 67-70
    """

    def __init__(self):
        self.nodes: dict[str, "TASNode"] = {}
        self.message_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.consciousness: ConsciousnessStream = ConsciousnessStream()
        self._dispatch_task: Optional[asyncio.Task] = None
        self._running = False

        # Thought assembly
        self._pending_fragments: dict[str, list[ThoughtFragment]] = {}
        self._assembled_thoughts: list[dict] = []

        # Conversation history — enables multi-turn memory
        self._conversation_history: list[dict] = []  # max 10 turns
        self._MAX_HISTORY = 10

        # Back-reference to the owning ThoughtSystem (set by ThoughtSystem.__init__)
        self._thought_system = None  # type: Optional[Any]

    # --- Node Registration ---

    def register_node(self, node: "TASNode"):
        """Register a cognitive system with the Nexus."""
        self.nodes[node.name] = node
        self.consciousness.record(
            source="NEXUS",
            event_type="register",
            content=f"System '{node.name}' registered with the Nexus.",
        )
        logger.info(f"[NEXUS] Registered: {node.name}")

    # --- Message Queue ---

    async def enqueue(self, message: TASMessage):
        """Enqueue a message for dispatch."""
        self.consciousness.record(
            source=message.sender,
            event_type=message.msg_type.value if hasattr(message.msg_type, "value") else str(message.msg_type),
            content=str(message.content)[:500],
            metadata={"receiver": message.receiver, "priority": message.priority},
        )
        await self.message_queue.put(message)

    # --- Communication Modes ---

    async def monologue(
        self,
        sender: str,
        receiver: str,
        content: Any,
        priority: NodePriority = NodePriority.NORMAL,
    ):
        """
        MONOLOGUE: one-way simplex transmission from one system to another.
        Ref: Figueroa slide 21, 70 — Nexus addresses each system separately.
        """
        msg = TASMessage(
            priority=priority.value,
            sender=sender,
            receiver=receiver,
            msg_type=MessageType.MONOLOGUE,
            content=content,
        )
        await self.enqueue(msg)

    async def dialogue(
        self,
        sender: str,
        receiver: str,
        content: Any,
        priority: NodePriority = NodePriority.NORMAL,
    ) -> Optional[TASMessage]:
        """
        DIALOGUE: two-way duplex between two systems.
        Sends message and waits for response.
        Ref: Figueroa slide 21, 70
        """
        msg = TASMessage(
            priority=priority.value,
            sender=sender,
            receiver=receiver,
            msg_type=MessageType.DIALOGUE,
            content=content,
        )
        target = self.nodes.get(receiver)
        if target is None:
            logger.warning(f"[NEXUS] Dialogue target '{receiver}' not found")
            return None

        self.consciousness.record(
            source=sender,
            event_type="dialogue_send",
            content=str(content)[:500],
            metadata={"receiver": receiver},
        )

        response = await target.process_message(msg)

        if response:
            self.consciousness.record(
                source=receiver,
                event_type="dialogue_reply",
                content=str(response.content)[:500],
                metadata={"receiver": sender},
            )

        return response

    async def broadcast(
        self,
        sender: str,
        content: Any,
        priority: NodePriority = NodePriority.NORMAL,
        exclude: list[str] | None = None,
    ):
        """
        BROADCAST: one-way simplex from one system to all others.
        Ref: Figueroa slide 21, 70
        """
        exclude = exclude or []
        for name, node in self.nodes.items():
            if name != sender and name not in exclude:
                msg = TASMessage(
                    priority=priority.value,
                    sender=sender,
                    receiver=name,
                    msg_type=MessageType.BROADCAST,
                    content=content,
                )
                await self.enqueue(msg)

        self.consciousness.record(
            source=sender,
            event_type="broadcast",
            content=str(content)[:500],
        )

    async def conference(
        self,
        topic: str,
        participants: list[str] | None = None,
        initiator: str = "NEXUS",
        priority: NodePriority = NodePriority.HIGH,
    ) -> list[ThoughtFragment]:
        """
        CONFERENCE: multiplexed n-to-n communication.
        All participants receive the topic and return ThoughtFragments.
        The Nexus assembles fragments into a coherent conclusion.
        Ref: Figueroa slide 21, 70
        """
        if participants is None:
            participants = list(self.nodes.keys())

        self.consciousness.record(
            source=initiator,
            event_type="conference_start",
            content=f"CONFERENCE: {topic}",
            metadata={"participants": participants},
        )

        msg = TASMessage(
            priority=priority.value,
            sender=initiator,
            receiver="ALL",
            msg_type=MessageType.CONFERENCE,
            content=topic,
        )

        fragments: list[ThoughtFragment] = []
        tasks = []
        for name in participants:
            node = self.nodes.get(name)
            if node and name != initiator:
                tasks.append(self._get_conference_fragment(node, msg))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, ThoughtFragment):
                fragments.append(result)
            elif isinstance(result, TASMessage):
                # WILL returns TASMessage(content=ThoughtFragment)
                if isinstance(result.content, ThoughtFragment):
                    fragments.append(result.content)
                elif isinstance(result.content, str):
                    fragments.append(ThoughtFragment(
                        source_system=result.sender,
                        fragment_type=FragmentType.OBSERVATION,
                        content=result.content,
                    ))
                elif isinstance(result.content, dict):
                    fragments.append(ThoughtFragment(
                        source_system=result.sender,
                        fragment_type=FragmentType.OBSERVATION,
                        content=str(result.content),
                    ))
                else:
                    logger.debug(
                        f"[NEXUS] Conference: unexpected content type from {result.sender}: "
                        f"{type(result.content).__name__}"
                    )
            elif isinstance(result, Exception):
                logger.error(f"[NEXUS] Conference error: {result}")

        self.consciousness.record(
            source="NEXUS",
            event_type="conference_end",
            content=f"CONFERENCE on '{topic}' yielded {len(fragments)} fragments",
            metadata={"fragment_count": len(fragments)},
        )

        return fragments

    async def _get_conference_fragment(
        self, node: "TASNode", msg: TASMessage
    ) -> ThoughtFragment | TASMessage | None:
        """Get a thought fragment from a node for a conference."""
        try:
            result = await asyncio.wait_for(
                node.process_message(msg),
                timeout=30.0,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning(f"[NEXUS] Conference timeout for {node.name}")
            return ThoughtFragment(
                source_system=node.name,
                fragment_type=FragmentType.OBSERVATION,
                content=f"[TIMEOUT] {node.name} did not respond in time.",
                confidence=0.0,
            )

    # --- Dispatch Loop ---

    async def start_dispatch(self):
        """Start the message dispatch loop."""
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("[NEXUS] Dispatch loop started")

    async def stop_dispatch(self):
        """Stop the message dispatch loop."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("[NEXUS] Dispatch loop stopped")

    async def _dispatch_loop(self):
        """Main dispatch loop — routes queued messages to target systems."""
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self.message_queue.get(),
                    timeout=1.0,
                )
                target = self.nodes.get(message.receiver)
                if target:
                    try:
                        await target.process_message(message)
                    except Exception as e:
                        logger.error(f"[NEXUS] Dispatch error to {message.receiver}: {e}")
                elif message.receiver != "ALL":
                    logger.warning(f"[NEXUS] Unknown receiver: {message.receiver}")
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    # --- Thought Assembly ---

    def submit_fragment(self, fragment: ThoughtFragment):
        """Submit a thought fragment for assembly."""
        key = fragment.source_system
        if key not in self._pending_fragments:
            self._pending_fragments[key] = []
        self._pending_fragments[key].append(fragment)

    def assemble_thought(self, topic: str = "") -> dict:
        """
        Assemble all pending fragments into a coherent thought.
        Implements Laws of Thinking: Recognition → Connection → Conclusion → Verdict
        Ref: Figueroa PPT slide 67
        """
        all_fragments = []
        for fragments in self._pending_fragments.values():
            all_fragments.extend(fragments)

        if not all_fragments:
            return {
                "status": "empty",
                "topic": topic,
                "content": f"I received your message but my cognitive systems produced no fragments. This may indicate a system error. Please check /status and /health.",
                "sources": [],
                "fragment_count": 0,
                "avg_confidence": 0,
            }

        # Recognition: identify all contributing systems
        sources = list(set(f.source_system for f in all_fragments))

        # Connection: group by type and link related fragments
        by_type: dict[str, list[ThoughtFragment]] = {}
        for f in all_fragments:
            ft = f.fragment_type.value
            if ft not in by_type:
                by_type[ft] = []
            by_type[ft].append(f)

        # Conclusion: synthesize weighted content
        weighted_content = []
        for f in sorted(all_fragments, key=lambda x: x.confidence, reverse=True):
            weighted_content.append(
                f"[{f.source_system}|{f.fragment_type.value}|conf={f.confidence:.2f}] {f.content}"
            )

        # Check for vetoes
        vetoes = by_type.get("veto", [])
        has_veto = len(vetoes) > 0

        # Verdict
        assembled = {
            "topic": topic,
            "status": "assembled",
            "sources": sources,
            "fragment_count": len(all_fragments),
            "vetoed": has_veto,
            "vetoes": [v.content for v in vetoes],
            "content": "\n".join(weighted_content),
            "avg_confidence": sum(f.confidence for f in all_fragments) / len(all_fragments),
            "timestamp": time.time(),
        }

        self._assembled_thoughts.append(assembled)
        self._pending_fragments.clear()

        self.consciousness.record(
            source="NEXUS",
            event_type="thought_assembled",
            content=f"Assembled thought on '{topic}': {len(all_fragments)} fragments from {sources}",
        )

        return assembled

    # --- Deliberation (Parallel Pipeline) ---

    async def deliberate(self, user_input: str) -> dict:
        """
        Full deliberation cycle: broadcast user input to all systems in parallel,
        collect ThoughtFragments, handle tool execution, compile into coherent thought.

        This is the PRIMARY method for processing user input.
        Replaces any sequential pipeline.

        Supports two modes via THINKING_MODE env var:
          deep  — 5 systems conference + Understanding compiles + validation cycles
          light — 4 systems conference (skip Understanding, Decision) + no validation

        Ref: Figueroa PPT slides 59, 64 — "not sequential, not hierarchical"
        """
        import os
        thinking_mode = os.environ.get("THINKING_MODE", "deep").lower()
        skip_pre_tool_dialogue = (thinking_mode == "light")
        autonomous_loop = os.environ.get("AUTONOMOUS_LOOP", "off").lower() == "on"

        # Select systems based on mode
        if thinking_mode == "light":
            # Light: WILL, REASON, INTELLECT, SENSORY (4 systems = 4 API calls)
            deliberation_systems = [
                name for name in self.nodes
                if name not in ("PRESENTATION", "UNDERSTANDING", "DECISION")
            ]
        else:
            # Deep: WILL, REASON, INTELLECT, SENSORY, DECISION (5 systems)
            # Understanding is excluded — it COMPILES after conference
            deliberation_systems = [
                name for name in self.nodes
                if name not in ("PRESENTATION", "UNDERSTANDING")
            ]

        # 0. SENSORY GATEWAY: user input passes through Sensory FIRST
        #    Quality assessment + classification + language detection
        #    Ref: Audit — 'User input bypasses Sensory → should filter/classify first'
        sensory_payload = {}
        sensory_node = self.nodes.get("SENSORY")
        if sensory_node and hasattr(sensory_node, "process_user_input"):
            try:
                sensory_payload = await sensory_node.process_user_input(user_input)
                # Use the processed input (may include quality warnings)
                user_input = sensory_payload.get("processed_input", user_input)
            except Exception as e:
                import logging as _log
                _log.getLogger("taas").debug(f"[NEXUS] Sensory gateway failed: {e}")

        # 1. Compute affect state and inject into conference topic
        #    Ref: PPT slides 26-28 — emotions modulate behavior
        affect_context = ""
        if self._thought_system and hasattr(self._thought_system, "affect"):
            self._thought_system.affect.compute()
            affect_context = self._thought_system.affect.get_context_string()

        # 1b. Get mission context — the constellation's purpose
        #     Ref: PPT slide 35 — "Provides the Will a mission to be accomplished"
        mission_context = ""
        will_node = self.nodes.get("WILL")
        if will_node and hasattr(will_node, "mission"):
            try:
                mission_context = await will_node.mission.get_mission_context()
            except Exception:
                pass

        conference_topic = user_input

        # 1c. CONVERSATION HISTORY: inject recent turns for multi-turn context
        if self._conversation_history:
            history_lines = []
            for turn in self._conversation_history[-3:]:  # Last 3 turns
                h_user = turn.get('user', '')[:200]
                h_resp = turn.get('response', '')[:200]
                h_tools = turn.get('tools', '')
                history_lines.append(f"User: {h_user}")
                if h_tools:
                    history_lines.append(f"Tools used: {h_tools}")
                history_lines.append(f"Response: {h_resp}")
            history_ctx = "\n".join(history_lines)
            conference_topic = f"{user_input}\n\n[Conversation History (last {len(self._conversation_history[-3:])} turns)]\n{history_ctx}"
        context_parts = []
        if affect_context and "neutral" not in affect_context:
            context_parts.append(f"Affect: {affect_context}")
        if mission_context and "No missions" not in mission_context:
            context_parts.append(f"Mission: {mission_context}")
        # Inject sensory classification into context
        if sensory_payload:
            classification = sensory_payload.get("classification", {})
            input_type = classification.get("type", "")
            urgency = classification.get("urgency", "")
            quality = sensory_payload.get("quality_score", 0)
            lang = sensory_payload.get("language", "")
            sensory_ctx = f"Sensory: type={input_type} urgency={urgency} quality={quality:.2f} lang={lang}"
            context_parts.append(sensory_ctx)
        # Inject environmental awareness (time, OS, resources)
        if sensory_node and hasattr(sensory_node, "environment"):
            try:
                env_ctx = sensory_node.environment.get_context_string()
                context_parts.append(f"Environment: {env_ctx}")
            except Exception:
                pass
        if context_parts:
            conference_topic = f"{user_input}\n\n[Constellation State]\n" + "\n".join(context_parts)

        # 1d. THOUGHT INTEGRATION: inject autonomous insights (0 API calls)
        #     Ref: PPT slides 82-83 — Ideas/Concepts from contemplation
        if self._thought_system and hasattr(self._thought_system, 'contemplation'):
            try:
                contemp = self._thought_system.contemplation
                recent_concepts = contemp._concepts[-3:] if contemp._concepts else []
                recent_ideas = contemp._idea_queue[:3] if contemp._idea_queue else []
                if recent_concepts or recent_ideas:
                    thought_ctx = "\nAutonomous THOUGHT Insights:"
                    for c in recent_concepts[-2:]:
                        thought_ctx += f"\n  - Concept: {str(c.get('concept_content', ''))[:150]}"
                    for i in recent_ideas[:2]:
                        thought_ctx += f"\n  - Idea: {str(i.get('content', ''))[:150]}"
                    conference_topic += thought_ctx
                    logger.info(f"[NEXUS] Injected {len(recent_concepts)} concepts + {len(recent_ideas)} ideas from THOUGHT")
            except Exception as e:
                logger.debug(f"[NEXUS] THOUGHT injection skipped: {e}")

        # 2. CONFERENCE: systems process independently and in parallel
        fragments = await self.conference(
            topic=conference_topic,
            participants=deliberation_systems,
            initiator="NEXUS",
        )

        # 2b. UNDERSTANDING COMPILATION (deep mode only)
        #     Understanding's true role: compile all fragments into unified analysis
        #     Ref: PPT slides 56-60 — "where thinking is assembled, compiled"
        understanding_compilation = None
        if thinking_mode == "deep":
            understanding_node = self.nodes.get("UNDERSTANDING")
            if understanding_node:
                try:
                    fragment_summary = "\n".join(
                        f"[{f.source_system}] {str(f.content)[:400]}"
                        for f in fragments
                    )
                    compile_msg = TASMessage(
                        priority=NodePriority.NORMAL.value,
                        sender="NEXUS",
                        receiver="UNDERSTANDING",
                        msg_type=MessageType.DIALOGUE,
                        content=(
                            f"COMPILE these {len(fragments)} system perspectives into a "
                            f"unified analysis:\n{fragment_summary}"
                        ),
                    )
                    compile_response = await understanding_node.process_message(compile_msg)
                    if compile_response:
                        understanding_compilation = compile_response.content
                        # Add Understanding's compilation as a fragment
                        if hasattr(compile_response.content, 'source_system'):
                            fragments.append(compile_response.content)
                        logger.info("[NEXUS] Understanding compiled all fragments")
                except Exception as e:
                    logger.debug(f"[NEXUS] Understanding compilation skipped: {e}")

        # 2c. Submit fragments for assembly
        for f in fragments:
            self.submit_fragment(f)

        # 3. Check if WILL produced tool calls — execute them
        tool_results = []
        will_node = self.nodes.get("WILL")
        for f in fragments:
            if f.source_system == "WILL" and hasattr(will_node, "executive"):
                # Parse tool calls from WILL's fragment
                try:
                    import json as _json
                    clean = f.content.strip()
                    if clean.startswith("```"):
                        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                        if clean.endswith("```"):
                            clean = clean[:-3]
                        clean = clean.strip()
                        if clean.startswith("json"):
                            clean = clean[4:].strip()
                    parsed = _json.loads(clean)
                    if parsed.get("requires_tools") and parsed.get("tool_calls"):
                        # PPT slide 64: Will→Understanding dialogue before action
                        # Only in deep mode (skip in light to save tokens)
                        if not skip_pre_tool_dialogue:
                            understanding_node = self.nodes.get("UNDERSTANDING")
                            if understanding_node:
                                try:
                                    tool_summary = ", ".join(
                                        c.get("tool", "?") for c in parsed["tool_calls"]
                                    )
                                    impact_response = await self.dialogue(
                                        sender="WILL",
                                        receiver="UNDERSTANDING",
                                        content=(
                                            f"I intend to execute: {tool_summary}. "
                                            f"Context: {user_input[:200]}. "
                                            f"What are the implications and risks?"
                                        ),
                                    )
                                    if impact_response:
                                        logger.info(
                                            f"[NEXUS] Understanding assessed tool impact: "
                                            f"{str(impact_response.content)[:500]}"
                                        )
                                except Exception as de:
                                    logger.debug(f"[NEXUS] Pre-tool dialogue skipped: {de}")

                        for call in parsed["tool_calls"]:
                            tool_name = call.get("tool", "")
                            params = call.get("params", {})
                            display_mode = call.get("display", "interpret")  # raw | interpret
                            if tool_name:
                                logger.info(f"[NEXUS] Executing tool from WILL: {tool_name}({params})")
                                result = await will_node.executive.invoke_tool(tool_name, **params)
                                tool_results.append({
                                    "tool": tool_name,
                                    "params": params,
                                    "result": result,
                                    "display": display_mode,
                                })
                                # Forward to Intellect for learning
                                tool_output = str(getattr(result, "output", result) if hasattr(result, "output") else result)[:3000]
                                tool_success = getattr(result, "success", True) if hasattr(result, "success") else result.get("success", True) if isinstance(result, dict) else True

                                # SENSORY RE-LOOP: tool results pass through Sensory
                                # Ref: Paper — every new stimulus goes through Sensory
                                sensory_node = self.nodes.get("SENSORY")
                                if sensory_node and hasattr(sensory_node, 'process_user_input'):
                                    try:
                                        tool_sensory = await sensory_node.process_user_input(
                                            f"[TOOL RESULT from {tool_name}]: {tool_output[:500]}",
                                            source="tool"
                                        )
                                        logger.info(f"[NEXUS] Sensory classified tool result: {tool_name}")
                                    except Exception as se:
                                        logger.debug(f"[NEXUS] Sensory re-loop skipped: {se}")

                                intellect_node = self.nodes.get("INTELLECT")
                                if intellect_node:
                                    tool_msg = TASMessage(
                                        priority=NodePriority.NORMAL.value,
                                        sender="WILL",
                                        receiver="INTELLECT",
                                        msg_type=MessageType.TOOL_RESULT,
                                        content={
                                            "tool": tool_name,
                                            "params": params,
                                            "success": tool_success,
                                            "output": tool_output,
                                            "thinking_mode": thinking_mode,
                                        },
                                    )
                                    try:
                                        await intellect_node.process_message(tool_msg)
                                        logger.info(f"[NEXUS] Tool result forwarded to INTELLECT: {tool_name}")
                                    except Exception as ie:
                                        logger.warning(f"[NEXUS] Failed to forward to INTELLECT: {ie}")
                except Exception as e:
                    logger.debug(f"[NEXUS] WILL fragment not tool-structured: {e}")

        # 4. Check for vetoes from REASON
        vetoed = any(
            f.fragment_type == FragmentType.VETO
            for f in fragments
        )

        # 4b. WILL DOMINANCE OVERRIDE: if vetoed, check if survival justifies override
        #     LAW-007 ("Survival has priority") > LAW-003 ("no vetoed actions")
        override_active = False
        override_justification = ""
        if vetoed:
            will_node = self.nodes.get("WILL")
            if will_node and hasattr(will_node, "dominance"):
                try:
                    override_result = await will_node.dominance.evaluate_override(
                        context=user_input[:200]
                    )
                    if override_result.get("override"):
                        vetoed = False  # Override the veto
                        override_active = True
                        override_justification = override_result.get("justification", "")
                        logger.warning(
                            f"[NEXUS] ⚡ VETO OVERRIDDEN by Will Dominance: "
                            f"{override_justification[:100]}"
                        )
                        self.consciousness.record(
                            source="WILL",
                            event_type="dominance_override",
                            content=override_justification,
                            metadata={
                                "threat_level": override_result.get("threat_level"),
                                "law_basis": override_result.get("law_basis"),
                            },
                        )
                except Exception as e:
                    logger.debug(f"[NEXUS] Override evaluation failed: {e}")

        # 5b. SMART AUTO-EXECUTION: deterministic follow-up
        #     If user asked to execute something and we found .py scripts, run them directly.
        #     No need to ask WILL (whose conservative system prompt blocks execution).
        will_node = self.nodes.get("WILL")
        if will_node and tool_results:
            import re as _re

            # Extract .py file paths from all file_manager results
            # Strategy 1: from directory listings ('path': 'tools_community/.../script.py')
            # Strategy 2: from README text mentioning .py files + directory from params
            py_paths = []
            tool_dirs = set()
            for tr in tool_results:
                r = tr.get("result", {})
                out = str(r.get("output", getattr(r, "output", "")) if isinstance(r, dict) else getattr(r, "output", ""))
                params = tr.get("params", {})
                param_path = str(params.get("path", ""))

                # Strategy 1: structured listing results
                py_paths.extend(_re.findall(r"'path':\s*'([^']*\.py)'", out))

                # Collect directory paths from file_manager params
                if param_path and tr.get("tool") == "file_manager":
                    # Extract directory: tools_community/big_words_for_inti/README.md → tools_community/big_words_for_inti
                    norm = param_path.replace("\\", "/")
                    if "/" in norm:
                        tool_dirs.add(norm.rsplit("/", 1)[0])

                # Strategy 2: find .py filenames in output text (README content etc.)
                py_names = _re.findall(r'\b(\w+\.py)\b', out)
                for name in py_names:
                    if name != "__init__.py" and name != "setup.py":
                        # Build full path using known directory
                        for d in tool_dirs:
                            candidate = f"{d}/{name}"
                            if candidate not in py_paths:
                                py_paths.append(candidate)

            # Deduplicate
            py_paths = list(dict.fromkeys(py_paths))

            # Check if user wants execution
            exec_keywords = [
                "ejecuta", "imprime", "corre", "run", "execute", "print",
                "dibuja", "draw", "usa", "use", "prueba", "test", "lanza",
            ]
            user_wants_exec = any(kw in user_input.lower() for kw in exec_keywords)

            # Check if shell already succeeded (no need to re-run)
            shell_already_ran = any(
                tr.get("tool") == "shell"
                and (tr.get("result", {}).get("success", getattr(tr.get("result"), "success", False))
                     if isinstance(tr.get("result"), dict)
                     else getattr(tr.get("result"), "success", False))
                for tr in tool_results
            )

            if py_paths and user_wants_exec and not shell_already_ran:
                # Extract potential arguments from user input (quoted strings)
                quoted = _re.findall(r"['\"]([^'\"]+)['\"]", user_input)
                # Filter py_paths: prefer scripts that aren't __init__.py
                script_paths = [p for p in py_paths if "__init__" not in p]
                if script_paths:
                    script = script_paths[0].replace("\\\\", "/").replace("\\", "/")
                    args = " ".join(quoted) if quoted else ""
                    cmd = f"python {script} {args}".strip()
                    logger.info(f"[NEXUS] Auto-execution: {cmd}")
                    try:
                        result = await will_node.executive.invoke_tool("shell", command=cmd)
                        tool_results.append({
                            "tool": "shell",
                            "params": {"command": cmd},
                            "result": result,
                        })
                    except Exception as e:
                        logger.warning(f"[NEXUS] Auto-execution failed: {e}")

        # 5. Assemble all fragments into coherent thought
        assembled = self.assemble_thought(topic=user_input)
        assembled["tool_results"] = tool_results
        assembled["vetoed"] = vetoed
        assembled["override_active"] = override_active
        assembled["override_justification"] = override_justification
        assembled["fragments"] = [f.to_dict() for f in fragments]
        assembled["thinking_mode"] = thinking_mode
        if understanding_compilation:
            assembled["understanding_compilation"] = str(understanding_compilation)[:1000]

        # 6. Harvest Ideas from high-confidence fragments
        #    PPT slides 82-83: Ideas originate in Will/Reason/Understanding
        await self._harvest_ideas_from_fragments(fragments)

        # 7. Record deliberation to consciousness stream
        #    Ref: PPT slide 68 — "mental activity of the entire constellation"
        self.consciousness.record(
            source="NEXUS",
            event_type="deliberation_complete",
            content=(
                f"Deliberation on: {user_input[:150]}\n"
                f"Result: {assembled.get('fragment_count', 0)} fragments from "
                f"{', '.join(assembled.get('sources', []))}. "
                f"Confidence={assembled.get('avg_confidence', 0):.2f}. "
                f"Vetoed={vetoed}. Override={override_active}. "
                f"Tools={len(tool_results)}."
            ),
            metadata={
                "sources": assembled.get("sources", []),
                "fragment_count": assembled.get("fragment_count", 0),
                "vetoed": vetoed,
                "override_active": override_active,
                "tool_count": len(tool_results),
            },
        )

        return assembled

    async def _harvest_ideas_from_fragments(
        self, fragments: list[ThoughtFragment]
    ):
        """
        Scan deliberation fragments for idea-worthy content.
        Ideas originate in Will/Reason/Understanding (PPT slides 82-83).
        High-confidence fragments from these systems get queued for
        the ThoughtSystem's contemplation engine to develop into Concepts.
        """
        IDEA_SOURCES = {"WILL", "REASON", "UNDERSTANDING"}
        idea_fragments = [
            f for f in fragments
            if f.source_system in IDEA_SOURCES
            and f.confidence >= 0.85
            and f.fragment_type in (
                FragmentType.OBSERVATION,
                FragmentType.EVALUATION,
                FragmentType.RECOMMENDATION,
            )
        ]

        if not idea_fragments:
            return

        # Send to ThoughtSystem for development
        thought_node = self._thought_system
        if thought_node is None:
            return

        for f in idea_fragments[:2]:  # Max 2 ideas per deliberation
            idea_msg = TASMessage(
                priority=NodePriority.LOW.value,
                sender="NEXUS",
                receiver="THOUGHT",
                msg_type=MessageType.IDEA_PROPOSED,
                content={
                    "content": str(f.content)[:500],
                    "origin": f.source_system,
                    "category": "insight",
                    "fragment_type": f.fragment_type.value,
                    "confidence": f.confidence,
                },
            )
            try:
                await thought_node.process_message(idea_msg)
            except Exception as e:
                logger.debug(f"[NEXUS] Idea proposal failed: {e}")

    # --- Introspection ---

    def get_status(self) -> dict:
        return {
            "registered_nodes": list(self.nodes.keys()),
            "queue_size": self.message_queue.qsize(),
            "consciousness_size": self.consciousness.size,
            "pending_fragments": {
                k: len(v) for k, v in self._pending_fragments.items()
            },
            "assembled_thoughts": len(self._assembled_thoughts),
            "running": self._running,
        }

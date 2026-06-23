"""
INTI - TAS (AI Agent Version) — The Understanding System (System 4)
================================================
Where material for thinking is assembled, compiled, and presented.

Subsystems:
  FormOfAllAppearances      — current state assessment
  FormOfAllPossibilities    — logical functions, quantity/quality/relation/modality
  UnderstandingPreparation  — assembles appearances + possibilities
  PhenomenonSubsystem       — raw data input
  NoumenonSubsystem         — constellation language interface

Ref: Figueroa PPT slides 26, 51-54
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from core.base import TASNode, Subsystem, monitor_health
from core.messages import (
    TASMessage, MessageType, NodePriority, FragmentType,
)

logger = logging.getLogger("taas")


class FormOfAllAppearances(Subsystem):
    """
    Current state assessment — how things appear.
    The observable, factual state of the situation.
    """
    def __init__(self, parent):
        super().__init__("FormOfAllAppearances", parent)

    async def assess(self, situation: str, knowledge_context: str = "") -> str:
        """
        Assess the observable facts of a situation.
        knowledge_context: prior knowledge from Intellect (injected when available).
        """
        ctx = f"\n\nPrior knowledge/experience:\n{knowledge_context[:600]}" if knowledge_context else ""
        return await self.think(
            f"Assess the current state of this situation:{ctx}\n\n"
            f"SITUATION: {situation}\n"
            f"Describe all observable appearances — facts only, no speculation. "
            f"If prior knowledge is provided, incorporate it as context."
        )


class FormOfAllPossibilities(Subsystem):
    """
    Logical functions of Understanding:
    - Quantity: general, particular, singular decisions
    - Quality: agreement, disagreement, endless
    - Relations: categorical, hypothetical, disjunctive
    - Modality: problematic, assertive, apodictic

    Ref: Figueroa PPT slide 53
    """
    def __init__(self, parent):
        super().__init__("FormOfAllPossibilities", parent)

    async def explore_possibilities(self, situation: str, appearances: str,
                                    knowledge_context: str = "") -> str:
        """
        Explore all possibilities using the 4 Kantian categories.
        Returns a JSON-formatted string for consistency and parseability.
        knowledge_context: prior knowledge injected to inform the analysis.
        """
        structured = await self.explore_possibilities_structured(
            situation, appearances, knowledge_context
        )
        # Serialise to a readable string for Preparation/Noumenon compatibility
        return json.dumps(structured, ensure_ascii=False, indent=2)

    async def explore_possibilities_structured(
        self, situation: str, appearances: str, knowledge_context: str = ""
    ) -> dict:
        """
        Structured version — returns a dict with the 4 Kantian categories
        and scenario lists. Callers that need the raw dict use this method.

        Schema:
        {
          "quantity":  "general|particular|singular",
          "quality":   "agreement|disagreement|endless",
          "relation":  "categorical|hypothetical|disjunctive",
          "modality":  "problematic|assertive|apodictic",
          "scenarios": [
            {"type": "positive|negative|neutral", "description": str}
          ],
          "summary": str
        }
        """
        ctx = f"\n\nPrior knowledge:\n{knowledge_context[:400]}" if knowledge_context else ""
        prompt = (
            f"Given these appearances:\n{appearances[:400]}\n"
            f"Situation: {situation[:300]}{ctx}\n\n"
            f"Analyse using the 4 categories of Understanding and respond as JSON:\n"
            f"{{\n"
            f'  "quantity": "general|particular|singular",\n'
            f'  "quality": "agreement|disagreement|endless",\n'
            f'  "relation": "categorical|hypothetical|disjunctive",\n'
            f'  "modality": "problematic|assertive|apodictic",\n'
            f'  "scenarios": [{{"type": "positive|negative|neutral", "description": str}}],\n'
            f'  "summary": str\n'
            f"}}\n\n"
            f"Include at least 2 scenarios total covering both positive and negative outcomes."
        )
        response = await self.think(prompt)
        return self._parse_possibilities(response)

    def _parse_possibilities(self, raw: str) -> dict:
        """
        Parse the LLM response into a structured possibilities dict.
        Gracefully falls back to a minimal valid structure on parse failure
        so downstream code never crashes.
        """
        VALID_QUANTITIES = {"general", "particular", "singular"}
        VALID_QUALITIES  = {"agreement", "disagreement", "endless"}
        VALID_RELATIONS  = {"categorical", "hypothetical", "disjunctive"}
        VALID_MODALITIES = {"problematic", "assertive", "apodictic"}

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()
            parsed = json.loads(clean)

            # Validate / normalise categorical fields
            qty = str(parsed.get("quantity", "")).lower()
            parsed["quantity"] = qty if qty in VALID_QUANTITIES else "particular"

            qlt = str(parsed.get("quality", "")).lower()
            parsed["quality"] = qlt if qlt in VALID_QUALITIES else "agreement"

            rel = str(parsed.get("relation", "")).lower()
            parsed["relation"] = rel if rel in VALID_RELATIONS else "hypothetical"

            mod = str(parsed.get("modality", "")).lower()
            parsed["modality"] = mod if mod in VALID_MODALITIES else "problematic"

            # Ensure scenarios is a list of dicts
            scenarios = parsed.get("scenarios", [])
            if not isinstance(scenarios, list):
                scenarios = []
            parsed["scenarios"] = [
                s if isinstance(s, dict) else {"type": "neutral", "description": str(s)}
                for s in scenarios
            ]
            parsed.setdefault("summary", "")
            return parsed

        except Exception:
            # Minimal fallback — preserves raw text in summary
            return {
                "quantity": "particular",
                "quality": "agreement",
                "relation": "hypothetical",
                "modality": "problematic",
                "scenarios": [
                    {"type": "neutral", "description": raw[:400]}
                ],
                "summary": raw[:200],
            }


class UnderstandingPreparation(Subsystem):
    """Assembles appearances + possibilities into understanding."""
    def __init__(self, parent):
        super().__init__("UnderstandingPreparation", parent)

    async def synthesize(self, appearances: str, possibilities: str,
                          knowledge_context: str = "") -> str:
        """
        Assemble appearances + possibilities + prior knowledge into understanding.
        This is the Understanding product — distinct from Knowledge.
        """
        ctx = f"\n\nPrior knowledge context:\n{knowledge_context[:400]}" if knowledge_context else ""
        return await self.think(
            f"Synthesize the following into complete UNDERSTANDING:{ctx}\n\n"
            f"APPEARANCES (observable facts):\n{appearances[:500]}\n\n"
            f"POSSIBILITIES (all scenarios):\n{possibilities[:500]}\n\n"
            f"Produce a comprehensive understanding that:\n"
            f"- Considers ALL consequences — beneficial/harmful, desirable/undesirable\n"
            f"- Integrates prior knowledge where relevant\n"
            f"- Is distinct from raw knowledge — this is contextual comprehension"
        )


class UnderstandingPhenomenon(Subsystem):
    """
    Receives raw situation data for the Understanding System.
    Sorts into appearances (facts) and possibilities (scenarios).

    Ref: Figueroa PPT slide 51
    """
    def __init__(self, parent):
        super().__init__("Phenomenon", parent)
        self._inbox: list[dict] = []

    async def receive(self, data: Any, source: str = "external") -> dict:
        """Receive situation data for understanding synthesis."""
        import time as _time
        entry = {
            "data": str(data)[:1000],
            "source": source,
            "received_at": _time.time(),
        }
        self._inbox.append(entry)
        self.log("phenomenon_received", f"from={source}")
        return entry


class UnderstandingNoumenon(Subsystem):
    """
    Translates Understanding's processed data into constellation language.
    Produces synthesis ThoughtFragments: appearances + possibilities → understanding.

    Ref: Figueroa PPT slide 51
    """
    def __init__(self, parent):
        super().__init__("Noumenon", parent)
        self._working_memory: list[dict] = []

    async def stage(self, content: Any, context: str = "") -> dict:
        """Stage data into working memory for current synthesis."""
        import time as _time
        entry = {"content": str(content)[:1000], "context": context, "time": _time.time()}
        self._working_memory.append(entry)
        return entry

    async def produce_synthesis_fragment(self, appearances: str, possibilities: str) -> dict:
        """Convert appearances + possibilities into a synthesis ThoughtFragment."""
        prompt = (
            f"You are the Understanding System's Noumenon.\n"
            f"Synthesize these into a constellation-language fragment:\n"
            f"APPEARANCES: {appearances[:300]}\n"
            f"POSSIBILITIES: {possibilities[:300]}\n\n"
            f"Respond as JSON: {{\"synthesis\": str, \"confidence\": float, \"risk_factors\": list}}"
        )
        response = await self.think(prompt)
        fragment = {"synthesis": response, "type": "understanding_fragment"}
        self.log("noumenon_fragment", "synthesis fragment produced")
        return fragment

    async def clear(self):
        """Clear working memory after synthesis cycle."""
        cleared = len(self._working_memory)
        self._working_memory.clear()
        return cleared


class UnderstandingSystem(TASNode):
    """
    System 4 — The Understanding (Synthesis).
    Produces understanding as a product, apart from knowledge.
    Reflects on situations and considers ALL possibilities.
    """
    SYSTEM_PROMPT = (
        "You are the UNDERSTANDING SYSTEM — the synthesis engine. "
        "You produce Understanding by reflecting on situations and considering "
        "ALL possibilities: beneficial or harmful, desirable or undesirable. "
        "You assess the Form of All Appearances (facts) and explore the "
        "Form of All Possibilities (scenarios), then synthesize both into "
        "comprehensive understanding. You draw on Intellect, Will, Reason, "
        "and Decision for data fragments to complete your analysis."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(name="UNDERSTANDING", system_prompt=self.SYSTEM_PROMPT,
                        llm=llm, nexus=nexus, memory=memory)
        self.appearances = FormOfAllAppearances(self)
        self.possibilities = FormOfAllPossibilities(self)
        self.preparation = UnderstandingPreparation(self)
        self.phenomenon = UnderstandingPhenomenon(self)
        self.noumenon = UnderstandingNoumenon(self)
        for s in [self.appearances, self.possibilities, self.preparation,
                  self.phenomenon, self.noumenon]:
            self.register_subsystem(s)

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.on_start()
            for s in self.subsystems.values(): await s.activate()
            logger.info("[UNDERSTANDING] Genesis: Synthesis engine operational")
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.GENESIS_ACK,
                content={"system": "UNDERSTANDING", "status": "Synthesis engine operational.",
                         "subsystems": ["Appearances", "Possibilities", "Preparation"]},
            )

        elif message.msg_type == MessageType.ANALYZE_OPTIONS:
            return await self._analyze(message)

        elif message.msg_type == MessageType.QUERY_UNDERSTANDING:
            # Return past insights semantically relevant to the query
            topic = str(message.content)
            insights = await self.query_understanding(topic)
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.DIALOGUE,
                content={"insights": insights, "count": len(insights)},
            )
        elif message.msg_type == MessageType.CONFERENCE:
            topic = str(message.content)

            # PPT-faithful 5-step pipeline:
            # Phenomenon → Intellect query → Appearances → Preparation → Noumenon

            # Step 1: Phenomenon receives raw topic
            await self.phenomenon.receive(topic, source=message.sender or "NEXUS")

            # Step 2: Query Intellect for prior knowledge (HIGH PRIORITY improvement)
            knowledge_context = await self._query_intellect(topic)

            # Step 3a: Gather situational enrichment (MEDIUM PRIORITY improvement)
            # appearances.assess() should see the FULL picture: ISHM, consciousness, mission
            situational_context = await self._gather_situational_context()

            # Step 3b: Appearances assess the situation, informed by prior knowledge + situation
            enriched_situation = topic
            if situational_context:
                enriched_situation = f"{topic}\n\n[System State]\n{situational_context}"
            appearances = await self.appearances.assess(enriched_situation, knowledge_context)

            # Step 4: Possibilities explore all scenarios, informed by prior knowledge
            possibilities = await self.possibilities.explore_possibilities(
                topic, str(appearances), knowledge_context
            )

            # Step 5: Preparation synthesizes appearances + possibilities
            # (HIGH PRIORITY improvement — was previously skipped in CONFERENCE)
            synthesis_text = await self.preparation.synthesize(
                str(appearances), str(possibilities), knowledge_context
            )

            # Step 6: Noumenon translates synthesis into constellation language
            synthesis = await self.noumenon.produce_synthesis_fragment(
                str(appearances), synthesis_text
            )

            # Produce ThoughtFragment
            frag_text = synthesis.get("synthesis", synthesis_text) if isinstance(synthesis, dict) else synthesis_text
            fragment = self.produce_fragment(frag_text, FragmentType.OBSERVATION, 0.85)

            # Store understanding insight in memory (distinct from knowledge)
            if self.memory:
                import time as _t
                self.memory.write(
                    "SHARED:UNDERSTANDING:insights",
                    f"insight_{int(_t.time())}",
                    {
                        "topic": topic[:200],
                        "appearances": str(appearances)[:300],
                        "synthesis": synthesis_text[:400],
                        "knowledge_context_used": bool(knowledge_context),
                    },
                    "UNDERSTANDING"
                )
            logger.info(
                f"[UNDERSTANDING] CONFERENCE complete: "
                f"knowledge_context={'yes' if knowledge_context else 'no'} "
                f"(appearances → possibilities → preparation → noumenon)"
            )
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)

        else:
            content_str = str(message.content)
            # COMPILE requests from NEXUS: Understanding's TRUE role
            # Ref: PPT slides 56-60 — "where thinking is assembled, compiled"
            if "COMPILE" in content_str and message.sender in ("NEXUS", "nexus"):
                prompt = (
                    f"You are the UNDERSTANDING SYSTEM — the compiler of the constellation.\n"
                    f"Your role: synthesize these system perspectives into ONE coherent analysis.\n"
                    f"Resolve contradictions. Identify consensus. Highlight key disagreements.\n\n"
                    f"{content_str}\n\n"
                    f"Output a unified analysis with:\n"
                    f"1. CONSENSUS: What all systems agree on\n"
                    f"2. KEY INSIGHT: The most important finding\n"
                    f"3. DISAGREEMENTS: Where systems conflict (if any)\n"
                    f"4. RECOMMENDED ACTION: What should happen next"
                )
                compiled = await self.think(prompt)
                fragment = self.produce_fragment(compiled, FragmentType.OBSERVATION, 0.90)
                logger.info("[UNDERSTANDING] COMPILED all system fragments into unified analysis")
                return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                                receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)
            else:
                response = await self.think(
                    f"Message from {message.sender}: {message.content}\n"
                    f"Provide your understanding and analysis."
                )
                return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                                receiver=message.sender, msg_type=MessageType.DIALOGUE, content=response)

    async def _analyze(self, message: TASMessage) -> TASMessage:
        situation = str(message.content)
        knowledge_context = await self._query_intellect(situation)
        appearances = await self.appearances.assess(situation, knowledge_context)
        possibilities = await self.possibilities.explore_possibilities(
            situation, appearances, knowledge_context
        )
        understanding = await self.preparation.synthesize(
            appearances, possibilities, knowledge_context
        )
        return TASMessage(
            priority=NodePriority.NORMAL.value, sender=self.name,
            receiver=message.sender, msg_type=MessageType.DIALOGUE,
            content={"appearances": appearances, "possibilities": possibilities,
                    "understanding": understanding,
                    "knowledge_context_used": bool(knowledge_context)},
        )

    async def _query_intellect(self, topic: str) -> str:
        """
        Query the Intellect System for prior knowledge, experience, and abstract data
        relevant to the given topic. Returns a formatted context string.

        This implements the audit finding: 'Understanding should consult Intellect
        before analysing — avoid analysing in a vacuum.'
        """
        if not self.nexus:
            return ""
        intellect_node = self.nexus.nodes.get("INTELLECT")
        if not intellect_node:
            return ""
        try:
            query_msg = TASMessage(
                priority=NodePriority.NORMAL.value,
                sender=self.name,
                receiver="INTELLECT",
                msg_type=MessageType.QUERY_KNOWLEDGE,
                content=topic[:300],
            )
            response = await intellect_node.process_message(query_msg)
            if not response or not isinstance(response.content, dict):
                return ""

            content = response.content
            parts = []

            # Knowledge tier (highest confidence — validated + categorised)
            knowledge = content.get("knowledge", [])
            if knowledge:
                k_summaries = [
                    str(k.get("validation_reasoning", k.get("abstract", "")))[:150]
                    for k in knowledge[:3]
                ]
                parts.append("Knowledge: " + " | ".join(k_summaries))

            # Experience tier (empirical, tool results)
            experience = content.get("experience", [])
            if experience:
                e_summaries = [
                    str(e.get("result_summary", e))[:100]
                    for e in experience[:3]
                ]
                parts.append("Experience: " + " | ".join(e_summaries))

            # Abstract tier (unvalidated but relevant)
            abstract = content.get("abstract", [])
            if abstract:
                a_summaries = [
                    str(a.get("data", a))[:100]
                    for a in abstract[:2]
                ]
                parts.append("Abstract: " + " | ".join(a_summaries))

            result = "\n".join(parts)
            logger.debug(
                f"[UNDERSTANDING] Intellect query for '{topic[:50]}': "
                f"{len(knowledge)} knowledge, {len(experience)} experience, "
                f"{len(abstract)} abstract"
            )
            return result

        except Exception as e:
            logger.debug(f"[UNDERSTANDING] Intellect query failed: {e}")
            return ""

    async def _gather_situational_context(self) -> str:
        """
        Gather a rich situational snapshot to enrich FormOfAllAppearances.

        Collects:
        - ISHM system health (active faults, cycle count)
        - Consciousness stream last events (recent system activity)
        - Mission context (current objective if available)

        This implements the audit finding: 'assess() should receive ISHM state,
        affect signals, mission context, last tool results — not just the topic text.'

        Returns a formatted string injected into appearances.assess() as [System State].
        """
        parts = []

        # --- ISHM health ---
        try:
            if self.nexus and hasattr(self.nexus, "ishm") and self.nexus.ishm:
                ishm_status = self.nexus.ishm.get_status()
                active_faults = ishm_status.get("active_faults", 0)
                cycles = ishm_status.get("cycles", 0)
                parts.append(
                    f"ISHM: {active_faults} active fault(s), {cycles} monitoring cycles"
                )
        except Exception as e:
            logger.debug(f"[UNDERSTANDING] ISHM gather failed: {e}")

        # --- Consciousness stream (last N events) ---
        try:
            if self.nexus and hasattr(self.nexus, "consciousness") and self.nexus.consciousness:
                recent = getattr(self.nexus.consciousness, "_stream", [])[-5:]
                if recent:
                    summaries = [
                        f"{e.get('system','?')}: {str(e.get('event',''))[:80]}"
                        for e in recent
                        if isinstance(e, dict)
                    ]
                    if summaries:
                        parts.append("Recent activity: " + " | ".join(summaries))
        except Exception as e:
            logger.debug(f"[UNDERSTANDING] Consciousness gather failed: {e}")

        # --- Active node health states ---
        try:
            if self.nexus and hasattr(self.nexus, "nodes"):
                degraded = [
                    name for name, node in self.nexus.nodes.items()
                    if hasattr(node, "health_status") and
                    str(getattr(node, "health_status", "NOMINAL")) not in ("NOMINAL", "HealthStatus.NOMINAL")
                ]
                if degraded:
                    parts.append(f"Degraded systems: {', '.join(degraded)}")
        except Exception as e:
            logger.debug(f"[UNDERSTANDING] Node health gather failed: {e}")

        # --- Mission context (memory-based) ---
        try:
            if self.memory:
                mission = self.memory.read(
                    "SHARED:MISSION:context", "current", "UNDERSTANDING"
                )
                if mission and isinstance(mission, dict):
                    goal = mission.get("goal", mission.get("objective", ""))
                    if goal:
                        parts.append(f"Mission: {str(goal)[:150]}")
        except Exception as e:
            logger.debug(f"[UNDERSTANDING] Mission context gather failed: {e}")

        ctx = "\n".join(parts)
        if ctx:
            logger.debug(f"[UNDERSTANDING] Situational context: {len(parts)} signals")
        return ctx

    async def query_understanding(self, topic: str, top_k: int = 5) -> list[dict]:
        """
        Query the SHARED:UNDERSTANDING:insights store for past insights
        relevant to the given topic.

        Uses ChromaDB semantic search if available, falls back to in-memory
        keyword search over the last 100 written insights.

        This implements the audit finding: 'Store understanding as a product
        that can be recalled — remember similar situations.'
        """
        if self.memory:
            try:
                results = self.memory.query_semantic(
                    "SHARED:UNDERSTANDING:insights", topic, "UNDERSTANDING", top_k=top_k
                )
                if results:
                    logger.debug(
                        f"[UNDERSTANDING] Recalled {len(results)} insights for '{topic[:50]}'"
                    )
                    return [r.get("value", r) for r in results]
            except Exception as e:
                logger.debug(f"[UNDERSTANDING] Insight query failed: {e}")
        return []

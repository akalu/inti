"""
INTI - TAS (AI Agent Version) — The Decision System (System 7)
=============================================
Produces prioritized courses of action for the Will.

Subsystems:
  ArbitrationSub        — umpire between Understanding, Reason, and Intellect
  CourseOfActionSub     — generates ranked options with rationale (informed by Arbitration)
  PhenomenonSubsystem   — receives processed data from other systems
  NoumenonSubsystem     — constellation language interface

Ref: Figueroa PPT slides 25, 63-65
"""

from __future__ import annotations

import json
import logging
import time as _time
from typing import Any, Optional

from core.base import TASNode, Subsystem, monitor_health
from core.messages import (
    TASMessage, MessageType, NodePriority, FragmentType,
)

logger = logging.getLogger("taas")


class ArbitrationSubsystem(Subsystem):
    """
    Primary interface and umpire for Understanding, Reason, and Intellect.
    Before any decision is made, Arbitration consults all three systems
    and produces a unified briefing that informs CourseOfAction generation.

    Ref: Figueroa PPT slide 63 — 'Primary interface and umpire for
    Understanding, Reason, and Intellect in generating axioms, rules, and laws'
    """

    def __init__(self, parent):
        super().__init__("Arbitration", parent)
        self._arbitration_history: list[dict] = []

    async def arbitrate(self, situation: str) -> dict:
        """
        Consult Understanding, Reason, and Intellect, then arbitrate.

        Returns:
          {
            "understanding":   str  — what Understanding says about this
            "knowledge":       dict — what Intellect knows (wells of knowledge)
            "rules":           str  — what Reason says applies
            "conflicts":       list — disagreements between perspectives
            "unified_briefing": str — fused summary for CourseOfAction
            "data_tier":       str  — 'knowledge'|'experience'|'abstract'|'none'
            "decision_type":   str  — 'a_posteriori'|'a_priori'
          }
        """
        nexus = getattr(self.parent, "nexus", None)
        if not nexus:
            return self._empty_briefing(situation)

        # --- Query all three systems in parallel-ish fashion ---
        understanding_input = await self._query_system(
            nexus, "UNDERSTANDING", MessageType.QUERY_UNDERSTANDING,
            situation[:300]
        )
        knowledge_input = await self._query_system(
            nexus, "INTELLECT", MessageType.QUERY_KNOWLEDGE,
            situation[:300]
        )
        rules_input = await self._query_system(
            nexus, "REASON", MessageType.VALIDATE_ACTION,
            {"action": "analyze_rules", "context": situation[:300]}
        )

        # --- Determine data tier and decision type ---
        data_tier, decision_type = self._classify_data_tier(knowledge_input)

        # --- Query past decisions (experience-based learning) ---
        past_decisions_ctx = ""
        decision_system = self.parent
        if hasattr(decision_system, "query_past_decisions"):
            try:
                past = await decision_system.query_past_decisions(situation[:200], n_results=3)
                if past:
                    past_decisions_ctx = (
                        f"\n\nPAST DECISIONS (similar situations):\n"
                        + "\n".join(str(p.get("metadata", p))[:150] for p in past[:3])
                    )
                    # Past experience upgrades data tier
                    if data_tier in ("none", "abstract"):
                        data_tier = "experience"
                        decision_type = "a_posteriori"
            except Exception:
                pass

        # --- Arbitrate: fuse the 3 perspectives ---
        try:
            briefing = await self.think(
                f"You are the Decision System's ARBITRATION subsystem — the umpire.\n"
                f"Three systems have provided their perspectives on this situation:\n\n"
                f"SITUATION: {situation[:300]}\n\n"
                f"UNDERSTANDING (analysis): {str(understanding_input)[:400]}\n\n"
                f"INTELLECT (knowledge): {str(knowledge_input)[:400]}\n\n"
                f"REASON (rules/laws): {str(rules_input)[:400]}\n\n"
                f"Data tier: {data_tier} (decision type: {decision_type})"
                f"{past_decisions_ctx}\n\n"
                f"ARBITRATE: Fuse these perspectives into a unified briefing. "
                f"Identify any conflicts or disagreements between the three. "
                f"Conclude with a clear recommendation on how to proceed.\n\n"
                f'Respond as JSON: {{"unified_briefing": str, "conflicts": [str], '
                f'"recommendation_direction": str}}'
            )
        except Exception:
            briefing = ""

        result = {
            "understanding": str(understanding_input)[:500],
            "knowledge": knowledge_input if isinstance(knowledge_input, dict) else {"raw": str(knowledge_input)[:300]},
            "rules": str(rules_input)[:500],
            "conflicts": [],
            "unified_briefing": briefing,
            "data_tier": data_tier,
            "decision_type": decision_type,
        }

        self._arbitration_history.append({
            "situation": situation[:200],
            "data_tier": data_tier,
            "decision_type": decision_type,
            "time": _time.time(),
        })

        self.log(
            "arbitration_complete",
            f"tier={data_tier} type={decision_type}"
        )
        return result

    async def _query_system(self, nexus, system_name: str,
                            msg_type: MessageType, content) -> Any:
        """Query a constellation system and return its response content."""
        node = nexus.nodes.get(system_name)
        if not node:
            return ""
        try:
            query = TASMessage(
                priority=NodePriority.NORMAL.value,
                sender="DECISION",
                receiver=system_name,
                msg_type=msg_type,
                content=content,
            )
            response = await node.process_message(query)
            if response and response.content:
                return response.content
        except Exception as e:
            logger.debug(f"[DECISION] Arbitration query to {system_name} failed: {e}")
        return ""

    def _classify_data_tier(self, knowledge_input) -> tuple[str, str]:
        """
        Classify the data tier and decision type based on what Intellect returned.

        Wells of Knowledge principle:
        - knowledge (validated) → a_posteriori, confidence 0.9
        - experience (empirical) → a_posteriori, confidence 0.7
        - abstract (unvalidated) → a_priori, confidence 0.5
        - none → a_priori, confidence 0.3

        Ref: PPT — 'the decision is based on SUBSTANCE, not DESIRE'
        """
        if not isinstance(knowledge_input, dict):
            return "none", "a_priori"

        if knowledge_input.get("knowledge"):
            return "knowledge", "a_posteriori"
        elif knowledge_input.get("experience"):
            return "experience", "a_posteriori"
        elif knowledge_input.get("abstract"):
            return "abstract", "a_priori"
        else:
            return "none", "a_priori"

    def _empty_briefing(self, situation: str) -> dict:
        """Return an empty briefing when nexus is not available."""
        return {
            "understanding": "",
            "knowledge": {},
            "rules": "",
            "conflicts": [],
            "unified_briefing": f"No arbitration possible — operating on topic only: {situation[:200]}",
            "data_tier": "none",
            "decision_type": "a_priori",
        }

    # --- Confidence mapping ---
    DATA_TIER_CONFIDENCE = {
        "knowledge": 0.9,
        "experience": 0.7,
        "abstract": 0.5,
        "none": 0.3,
    }


class CourseOfActionSubsystem(Subsystem):
    """
    Generates and ranks courses of action.
    Each COA includes: option, priority, rationale, risk, dependencies.
    The Will executes the highest-priority COA approved by Reason.

    Now accepts an arbitration briefing so COAs are informed by
    Understanding, Intellect, and Reason — not just the raw topic.
    """
    def __init__(self, parent):
        super().__init__("CourseOfAction", parent)
        self._decisions: list[dict] = []

    async def generate_courses_of_action(self, situation: str,
                                          arbitration: dict | None = None) -> str:
        """
        Generate ranked courses of action for a given situation.
        If arbitration briefing is provided, COAs are informed by substance.
        """
        arb_context = ""
        if arbitration:
            arb_context = (
                f"\n\nARBITRATION BRIEFING (from Understanding, Intellect, Reason):\n"
                f"{str(arbitration.get('unified_briefing', ''))[:600]}\n"
                f"Data tier: {arbitration.get('data_tier', 'unknown')} "
                f"(decision type: {arbitration.get('decision_type', 'unknown')})\n"
                f"Conflicts: {arbitration.get('conflicts', [])}\n"
            )

        prompt = (
            f"You are the Decision System's Course of Action subsystem.\n"
            f"Situation: {situation[:400]}{arb_context}\n\n"
            f"Generate 3 prioritized courses of action.\n"
            f"For each, provide: option name, priority (1=highest), "
            f"rationale, risk level, dependencies on other systems.\n\n"
            f"Respond as JSON array: ["
            f'{{"option": str, "priority": int, "rationale": str, '
            f'"risk": str, "dependencies": list}}]'
        )
        result = await self.think(prompt)
        self._decisions.append({"situation": situation[:200], "result": result})
        return result

    async def iterative_refine(self, situation: str,
                                arbitration: dict | None = None,
                                rounds: int = 2) -> str:
        """
        Multi-round COA generation: generate → evaluate → refine.

        Round 1: Generate initial COAs
        Round 2+: Evaluate weaknesses, refine/replace weakest option

        Closer to PPT: 'The decision process is constant and dynamic,
        not sequential nor hierarchical.'
        """
        # Round 1: initial generation
        current = await self.generate_courses_of_action(situation, arbitration)

        for r in range(1, rounds):
            try:
                refine_prompt = (
                    f"You are the Decision System's Course of Action subsystem (refinement round {r+1}).\n"
                    f"Situation: {situation[:300]}\n"
                    f"Current courses of action: {current[:600]}\n\n"
                    f"CRITICALLY evaluate these options:\n"
                    f"1. Is the highest-priority option truly the best?\n"
                    f"2. Are there risks that were underestimated?\n"
                    f"3. Is there a better option not yet considered?\n\n"
                    f"Produce a REFINED set of 3 courses of action. "
                    f"Keep strong options, replace or improve weak ones.\n\n"
                    f"Respond as JSON array: ["
                    f'{{"option": str, "priority": int, "rationale": str, '
                    f'"risk": str, "dependencies": list, "refined_from": str}}]'
                )
                current = await self.think(refine_prompt)
                self.log("iterative_refine", f"round {r+1} complete")
            except Exception:
                break  # keep last valid result

        return current


class DecisionPhenomenon(Subsystem):
    """
    Receives processed data from other systems for decision-making.
    Input comes from Understanding, Intellect, and Sensory.

    Ref: Figueroa PPT slide 63
    """
    def __init__(self, parent):
        super().__init__("Phenomenon", parent)
        self._inputs: list[dict] = []

    async def receive(self, data: Any, source: str = "internal") -> dict:
        """Receive processed data for decision-making."""
        import time as _time
        entry = {
            "data": str(data)[:1000],
            "source": source,
            "received_at": _time.time(),
        }
        self._inputs.append(entry)
        self.log("phenomenon_received", f"from={source}")
        return entry

    def get_inputs(self) -> list[dict]:
        """Get all received decision inputs."""
        return list(self._inputs)


class DecisionNoumenon(Subsystem):
    """
    Translates Decision data into constellation language.
    Produces recommendation ThoughtFragments — courses of action
    that the Will can evaluate and execute.

    Ref: Figueroa PPT slides 63-65
    """
    def __init__(self, parent):
        super().__init__("Noumenon", parent)
        self._recommendations: list[dict] = []

    async def produce_recommendation_fragment(self, situation: str, courses: str) -> dict:
        """Convert courses of action into a recommendation ThoughtFragment."""
        prompt = (
            f"You are the Decision System's Noumenon — strategic translator.\n"
            f"Convert these courses of action into a recommendation fragment:\n"
            f"SITUATION: {situation[:300]}\n"
            f"COURSES: {courses[:500]}\n\n"
            f"Respond as JSON: {{\"top_recommendation\": str, \"confidence\": float, "
            f"\"risk\": str, \"alternatives\": list}}"
        )
        response = await self.think(prompt)
        fragment = {
            "situation": situation[:200],
            "recommendation": response,
            "type": "decision_fragment",
        }
        self._recommendations.append(fragment)
        self.log("noumenon_recommendation", "decision fragment produced")
        return fragment


class ValueSubsystem(Subsystem):
    """
    Evaluates courses of action against a value framework.
    Adapted from PPT: Preferences, Usefulness, Values, Happiness,
    Freedom, Aesthetics → simplified to 3 practical dimensions.

    Dimensions:
      usefulness (0.45) — does this directly solve the user's problem?
      safety     (0.35) — does this comply with rules/laws/constraints?
      elegance   (0.20) — is this the cleanest, simplest solution?

    Ref: Figueroa PPT slide 65 — 'Preferences, Usefulness, Values,
    Happiness, Freedom, Aesthetics'
    """

    DIMENSION_WEIGHTS = {
        "usefulness": 0.45,
        "safety": 0.35,
        "elegance": 0.20,
    }

    def __init__(self, parent):
        super().__init__("Value", parent)
        self._evaluation_history: list[dict] = []

    async def evaluate_courses(self, situation: str, courses_raw: str,
                                arbitration: dict | None = None) -> list[dict]:
        """
        Score each COA on usefulness, safety, and elegance.
        Returns a list of scored COAs, re-ranked by composite value score.
        """
        arb_ctx = ""
        if arbitration:
            rules = arbitration.get("rules", "")
            if rules:
                arb_ctx = f"\nApplicable rules/laws: {str(rules)[:300]}"

        try:
            prompt = (
                f"You are the Decision System's VALUE subsystem.\n"
                f"Evaluate each course of action on 3 dimensions (0.0 to 1.0):\n\n"
                f"SITUATION: {situation[:300]}{arb_ctx}\n"
                f"COURSES OF ACTION: {courses_raw[:600]}\n\n"
                f"For EACH option, score:\n"
                f"  usefulness (0-1): Does it directly solve the user's problem?\n"
                f"  safety (0-1): Does it comply with rules, constraints, and Laws?\n"
                f"  elegance (0-1): Is it the cleanest, simplest solution?\n\n"
                f"Respond as JSON array:\n"
                f'[{{"option": str, "usefulness": float, "safety": float, '
                f'"elegance": float}}]'
            )
            response = await self.think(prompt)

            # Parse response
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()

            scored = json.loads(clean)
            if not isinstance(scored, list):
                scored = [scored]

        except (json.JSONDecodeError, Exception):
            # Fallback: neutral scores
            scored = [{"option": "unknown", "usefulness": 0.5,
                       "safety": 0.5, "elegance": 0.5}]

        # Compute composite score and re-rank
        for item in scored:
            u = min(1.0, max(0.0, float(item.get("usefulness", 0.5))))
            s = min(1.0, max(0.0, float(item.get("safety", 0.5))))
            e = min(1.0, max(0.0, float(item.get("elegance", 0.5))))
            item["usefulness"] = round(u, 2)
            item["safety"] = round(s, 2)
            item["elegance"] = round(e, 2)
            item["value_score"] = round(
                u * self.DIMENSION_WEIGHTS["usefulness"] +
                s * self.DIMENSION_WEIGHTS["safety"] +
                e * self.DIMENSION_WEIGHTS["elegance"],
                3
            )

        # Sort by value_score descending
        scored.sort(key=lambda x: x.get("value_score", 0), reverse=True)

        # Assign new rank
        for i, item in enumerate(scored):
            item["value_rank"] = i + 1

        self._evaluation_history.append({
            "situation": situation[:200],
            "top_score": scored[0].get("value_score", 0) if scored else 0,
            "time": _time.time(),
        })

        self.log(
            "values_evaluated",
            f"{len(scored)} COAs scored, top={scored[0].get('value_score', 0) if scored else 0}"
        )
        return scored


class DecisionSystem(TASNode):
    """
    System 7 — The Decision (Prioritization).
    Takes input from Understanding, Intellect, and Sensory
    and produces prioritized courses of action for the Will.

    Features:
    - Arbitration: consults Understanding, Reason, Intellect
    - Value: scores COAs on usefulness, safety, elegance
    """
    SYSTEM_PROMPT = (
        "You are the DECISION SYSTEM — the strategic advisor. "
        "You take comprehensive understanding from the Understanding system, "
        "knowledge from Intellect, and environmental data from Sensory, "
        "and produce prioritized courses of action for the Will to execute. "
        "Each decision includes: option, priority, rationale, risk, and dependencies. "
        "You do NOT execute — the Will does. You RECOMMEND."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(name="DECISION", system_prompt=self.SYSTEM_PROMPT,
                        llm=llm, nexus=nexus, memory=memory)
        self.arbitration = ArbitrationSubsystem(self)
        self.value = ValueSubsystem(self)
        self.course_of_action = CourseOfActionSubsystem(self)
        self.phenomenon = DecisionPhenomenon(self)
        self.noumenon = DecisionNoumenon(self)
        for s in [self.arbitration, self.value, self.course_of_action,
                  self.phenomenon, self.noumenon]:
            self.register_subsystem(s)

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.on_start()
            for s in self.subsystems.values(): await s.activate()
            logger.info("[DECISION] Genesis: Decision system operational")
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.GENESIS_ACK,
                content={"system": "DECISION", "status": "Decision system operational.",
                         "subsystems": ["Arbitration", "Value", "CourseOfAction", "Phenomenon", "Noumenon"]},
            )

        elif message.msg_type == MessageType.DECIDE:
            # Direct decision request — arbitrate + evaluate values
            situation = str(message.content)
            arbitration = await self.arbitration.arbitrate(situation)
            coas = await self.course_of_action.generate_courses_of_action(
                situation, arbitration
            )
            value_scores = await self.value.evaluate_courses(
                situation, str(coas), arbitration
            )
            tier_conf = ArbitrationSubsystem.DATA_TIER_CONFIDENCE.get(
                arbitration["data_tier"], 0.3
            )
            top_value = value_scores[0].get("value_score", 0.5) if value_scores else 0.5
            final_conf = round(tier_conf * 0.6 + top_value * 0.4, 3)
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.DIALOGUE,
                content={
                    "courses_of_action": coas,
                    "value_scores": value_scores,
                    "data_tier": arbitration["data_tier"],
                    "decision_type": arbitration["decision_type"],
                    "confidence": final_conf,
                },
            )

        elif message.msg_type == MessageType.CONFERENCE:
            topic = str(message.content)

            # PPT-faithful pipeline:
            # Phenomenon → Arbitration → CourseOfAction → Value → Noumenon

            # Step 1: Phenomenon receives the raw conference topic
            await self.phenomenon.receive(topic, source=message.sender or "NEXUS")

            # Step 2: ARBITRATION — consult Understanding, Reason, Intellect
            arbitration = await self.arbitration.arbitrate(topic)

            # Step 3: CourseOfAction generates strategic options INFORMED by arbitration
            courses = await self.course_of_action.generate_courses_of_action(
                topic, arbitration
            )

            # Step 4: VALUE — score each COA on usefulness, safety, elegance
            value_scores = await self.value.evaluate_courses(
                topic, str(courses), arbitration
            )

            # Step 5: Noumenon translates to constellation language
            recommendation = await self.noumenon.produce_recommendation_fragment(
                topic, str(courses)
            )

            # Compute composite confidence: 60% data-tier + 40% top value score
            data_tier = arbitration.get("data_tier", "none")
            tier_conf = ArbitrationSubsystem.DATA_TIER_CONFIDENCE.get(data_tier, 0.3)
            top_value = value_scores[0].get("value_score", 0.5) if value_scores else 0.5
            confidence = round(tier_conf * 0.6 + top_value * 0.4, 3)

            # Produce fragment from the recommendation
            rec_text = recommendation.get("recommendation", str(recommendation)) if isinstance(recommendation, dict) else str(recommendation)
            fragment = self.produce_fragment(rec_text, FragmentType.RECOMMENDATION, confidence)

            # Persist decision to memory
            if self.memory:
                self.memory.write(
                    "SHARED:DECISION:history",
                    f"decision_{int(_time.time())}",
                    {
                        "topic": topic[:200],
                        "data_tier": data_tier,
                        "decision_type": arbitration.get("decision_type", "unknown"),
                        "confidence": confidence,
                        "top_value_score": top_value,
                        "courses": str(courses)[:400],
                    },
                    "DECISION"
                )

            logger.info(
                f"[DECISION] CONFERENCE complete: "
                f"tier={data_tier} type={arbitration.get('decision_type','?')} "
                f"confidence={confidence} top_value={top_value}"
            )
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)

        else:
            response = await self.think(
                f"Message from {message.sender}: {message.content}\n"
                f"Analyze and provide recommended courses of action."
            )
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=response)

    # ================================================================
    # LOW PRIORITY: Decision History + Learning
    # ================================================================

    async def query_past_decisions(self, query: str, n_results: int = 5) -> list[dict]:
        """
        Semantic search over past decisions using embeddings.

        Searches SHARED:DECISION:history for decisions similar to the query.
        Returns the most relevant past decisions so the system can learn:
        'Have I made a similar decision before? Did it work?'

        Ref: PPT — 'the object enters the wells of experience'
        """
        if not self.memory:
            return []

        try:
            results = self.memory.query(
                "SHARED:DECISION:history",
                query,
                n_results=n_results,
            )
            if isinstance(results, dict) and "documents" in results:
                docs = results["documents"][0] if results["documents"] else []
                metas = results["metadatas"][0] if results.get("metadatas") else []
                return [
                    {"document": d, "metadata": m}
                    for d, m in zip(docs, metas)
                ]
            return results if isinstance(results, list) else []
        except Exception as e:
            logger.debug(f"[DECISION] Past decision query failed: {e}")
            return []

    def record_outcome(self, decision_key: str, outcome: str,
                       success: bool, notes: str = ""):
        """
        Record the outcome of a past decision for learning.

        Over time, this builds a corpus of decision→outcome pairs that
        Arbitration and CourseOfAction can query to make better-informed
        decisions based on EXPERIENCE, not just abstract reasoning.
        """
        if not self.memory:
            return

        self.memory.write(
            "SHARED:DECISION:outcomes",
            f"outcome_{int(_time.time())}",
            {
                "decision_key": decision_key,
                "outcome": outcome[:500],
                "success": success,
                "notes": notes[:200],
                "recorded_at": _time.time(),
            },
            "DECISION"
        )
        logger.info(
            f"[DECISION] Outcome recorded: key={decision_key} success={success}"
        )

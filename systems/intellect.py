"""
INTI - TAS (AI Agent Version) — The Intellect System (System 3)
=============================================
The librarian — capacity to acquire and apply knowledge.

Subsystems:
  AbstractSubsystem    — stores secondary-source information
  ExperienceSubsystem  — stores experiential knowledge
  KnowledgeSubsystem   — validated knowledge (abstract + experience)
  PhenomenonSubsystem  — receives external sensory data
  NoumenonSubsystem    — inter-system language interface

Learning Loop (PPT Slide 24):
  1. Abstract data arrives (from web search, user input, conferences)
  2. Experiences arrive (from tool executions, sensor readings)
  3. Validation: LLM checks if experiences confirm abstract data
  4. Promotion: confirmed abstract data → Knowledge tier
  "A sound decision is made first based on knowledge, then on
   experience, and rarely on abstract data alone."

Ref: Figueroa PPT slides 24, 45-49
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import time

from core.base import TASNode, Subsystem, monitor_health
from core.messages import (
    TASMessage, MessageType, NodePriority,
    FragmentType, MemoryTier,
)

logger = logging.getLogger("taas")


class AbstractSubsystem(Subsystem):
    """
    Records, files, and processes all secondary-source information.
    Abstract data are claims not yet validated by experience.
    Sources: web search results, user-provided info, LLM reasoning.
    """
    def __init__(self, parent):
        super().__init__("Abstract", parent)
        self._abstract_data: list[dict] = []

    async def store(self, data: dict):
        """Store abstract data with metadata."""
        entry = {
            **data,
            "_stored_at": time.time(),
            "_validated": False,
            "_source": data.get("source", "unknown"),
        }
        self._abstract_data.append(entry)
        if self.memory:
            self.memory.write("ISOLATED:INTELLECT:abstract",
                            f"abs_{len(self._abstract_data)}", entry, "INTELLECT")
        self.log("abstract_stored", f"source={entry['_source']}")
        return entry

    async def query(self, topic: str) -> list[dict]:
        """Query abstract data. Uses semantic search if available."""
        if self.memory:
            results = self.memory.query_semantic(
                "ISOLATED:INTELLECT:abstract", topic, "INTELLECT", top_k=10
            )
            if results:
                return [r["value"] for r in results if r.get("value")]
        # Fallback: in-memory keyword search
        return [d for d in self._abstract_data if topic.lower() in str(d).lower()]

    async def get_unvalidated(self) -> list[dict]:
        """Get abstract data that hasn't been validated by experience yet."""
        return [d for d in self._abstract_data if not d.get("_validated")]

    async def mark_validated(self, index: int):
        """Mark abstract data as validated."""
        if 0 <= index < len(self._abstract_data):
            self._abstract_data[index]["_validated"] = True


class ExperienceSubsystem(Subsystem):
    """
    Stores knowledge acquired through direct experience.
    Experiences come from: tool executions, sensor readings, repair outcomes.
    """
    def __init__(self, parent):
        super().__init__("Experience", parent)
        self._experiences: list[dict] = []

    async def store(self, experience: dict):
        """Store an experience with metadata."""
        entry = {
            **experience,
            "_stored_at": time.time(),
            "_used_for_validation": False,
        }
        self._experiences.append(entry)
        if self.memory:
            self.memory.write("ISOLATED:INTELLECT:experience",
                            f"exp_{len(self._experiences)}", entry, "INTELLECT")
        self.log("experience_stored", f"type={experience.get('type', 'unknown')}")
        return entry

    async def store_tool_result(self, tool_name: str, params: dict,
                                result: dict, success: bool):
        """Store a tool execution result as an experience."""
        return await self.store({
            "type": "tool_execution",
            "tool": tool_name,
            "params": {k: str(v)[:200] for k, v in params.items()},
            "result_summary": str(result)[:500],
            "success": success,
        })

    async def query(self, topic: str) -> list[dict]:
        """Query experiences. Uses semantic search if available."""
        if self.memory:
            results = self.memory.query_semantic(
                "ISOLATED:INTELLECT:experience", topic, "INTELLECT", top_k=10
            )
            if results:
                return [r["value"] for r in results if r.get("value")]
        # Fallback: in-memory keyword search
        return [e for e in self._experiences if topic.lower() in str(e).lower()]

    async def get_recent(self, n: int = 10) -> list[dict]:
        """Get the N most recent experiences."""
        return self._experiences[-n:]


class KnowledgeSubsystem(Subsystem):
    """
    Validated knowledge — abstract data confirmed by experience.
    A sound decision is made first based on knowledge, then experience,
    and rarely on abstract data alone.

    Ref: Figueroa PPT slide 24
    """
    def __init__(self, parent):
        super().__init__("Knowledge", parent)
        self._knowledge: list[dict] = []

    async def promote_to_knowledge(self, abstract_data: dict, experience: dict,
                                   validation_reasoning: str = "") -> dict:
        """Promote abstract data validated by experience to Knowledge tier.
        Auto-categorizes the entry before storage.
        """
        # Auto-categorize before storing so the Knowledge store is structured
        category_meta = await self._categorize_knowledge(
            abstract_data, experience, validation_reasoning
        )

        knowledge_entry = {
            "abstract": abstract_data,
            "experience": experience,
            "validated": True,
            "validation_reasoning": validation_reasoning[:300],
            "promoted_at": time.time(),
            # Categorization fields
            "category": category_meta.get("category", "general"),
            "domain": category_meta.get("domain", "operational"),
            "priority": category_meta.get("priority", 0.5),
            "relevance_decay": category_meta.get("relevance_decay", 30),  # days
            "tags": category_meta.get("tags", []),
            "access_count": 0,
            "last_accessed": time.time(),
        }
        self._knowledge.append(knowledge_entry)
        if self.memory:
            key = f"know_{len(self._knowledge)}_{int(time.time())}"
            self.memory.write("SHARED:INTELLECT:knowledge", key, knowledge_entry, "INTELLECT")
        self.log(
            "knowledge_promoted",
            f"entries={len(self._knowledge)} cat={knowledge_entry['category']} "
            f"domain={knowledge_entry['domain']} priority={knowledge_entry['priority']:.2f}"
        )
        return knowledge_entry

    async def _categorize_knowledge(self, abstract_data: dict, experience: dict,
                                    reasoning: str) -> dict:
        """
        LLM-based auto-categorization of knowledge entries.
        Assigns: category, domain, priority, relevance_decay, tags.

        Categories:     technical | operational | safety | strategic | historical
        Domains:        tool_use | system_health | user_behavior | environment | self
        Priority:       0.0-1.0 (higher = consult first in decisions)
        Relevance decay: days before entry should be re-evaluated

        Ref: Audit — \"Knowledge only appends with no category. Should categorize
        and prioritize so the store is queryable, not just a flat list.\"
        """
        abs_summary = str(abstract_data.get("data", abstract_data))[:300]
        exp_summary = str(experience.get("result_summary", experience))[:300]
        prompt = (
            f"You are the Intellect System's knowledge categorizer.\n"
            f"Categorize this newly validated knowledge entry:\n\n"
            f"Abstract data: {abs_summary}\n"
            f"Experience evidence: {exp_summary}\n"
            f"Validation reasoning: {reasoning[:200]}\n\n"
            f"Respond as JSON:\n"
            f'{{"category": "technical|operational|safety|strategic|historical", '
            f'"domain": "tool_use|system_health|user_behavior|environment|self", '
            f'"priority": 0.0_to_1.0, '
            f'"relevance_decay": int_days_until_stale_7_to_365, '
            f'"tags": ["keyword1", "keyword2"]}}'
        )
        try:
            response = await self.think(prompt)
            import json as _j
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()
            return _j.loads(clean)
        except Exception:
            return {
                "category": "general",
                "domain": "operational",
                "priority": 0.5,
                "relevance_decay": 30,
                "tags": [],
            }

    async def query(self, topic: str) -> list[dict]:
        """Query knowledge. Uses semantic search if available."""
        if self.memory:
            results = self.memory.query_semantic(
                "SHARED:INTELLECT:knowledge", topic, "INTELLECT", top_k=10
            )
            if results:
                entries = [r["value"] for r in results if r.get("value")]
                # Track access stats for relevance scoring
                for e in entries:
                    e["access_count"] = e.get("access_count", 0) + 1
                    e["last_accessed"] = time.time()
                return entries
        # Fallback: in-memory keyword search, sorted by priority
        matches = [k for k in self._knowledge if topic.lower() in str(k).lower()]
        return sorted(matches, key=lambda k: k.get("priority", 0), reverse=True)

    def query_by_category(self, category: str) -> list[dict]:
        """Get all knowledge entries in a specific category, by priority."""
        return sorted(
            [k for k in self._knowledge if k.get("category", "general") == category],
            key=lambda k: k.get("priority", 0), reverse=True,
        )

    def query_by_domain(self, domain: str) -> list[dict]:
        """Get all knowledge entries for a specific domain, by priority."""
        return sorted(
            [k for k in self._knowledge if k.get("domain", "operational") == domain],
            key=lambda k: k.get("priority", 0), reverse=True,
        )

    def get_structured_summary(self) -> dict:
        """Return a summary of the Knowledge store by category and domain."""
        from collections import Counter
        cats = Counter(k.get("category", "general") for k in self._knowledge)
        domains = Counter(k.get("domain", "operational") for k in self._knowledge)
        high_priority = [k for k in self._knowledge if k.get("priority", 0) >= 0.7]
        return {
            "total": len(self._knowledge),
            "by_category": dict(cats),
            "by_domain": dict(domains),
            "high_priority_count": len(high_priority),
        }

    def get_decayed_entries(self) -> list[dict]:
        """
        Return knowledge entries that have exceeded their relevance_decay threshold.
        These entries should be re-validated against current experience.

        Ref: Audit — "Old entries without recent access should lose relevance.
        Avoid memory filling with obsolete knowledge."
        """
        now = time.time()
        decayed = []
        for entry in self._knowledge:
            promoted_at = entry.get("promoted_at", now)
            decay_days = entry.get("relevance_decay", 30)
            age_days = (now - promoted_at) / 86400
            last_accessed = entry.get("last_accessed", promoted_at)
            days_since_access = (now - last_accessed) / 86400

            # Decayed if: age > decay threshold AND not accessed recently
            if age_days > decay_days and days_since_access > (decay_days / 2):
                decayed.append(entry)
        return decayed

    async def run_decay_check(self) -> dict:
        """
        Periodic decay maintenance:
        - Find stale entries (past their relevance_decay)
        - Reduce their priority score
        - Flag them for re-validation
        - Return summary

        Should be called during idle periods or after sustained activity.
        """
        decayed = self.get_decayed_entries()
        if not decayed:
            return {"decayed": 0, "priority_reduced": 0}

        priority_reduced = 0
        for entry in decayed:
            old_priority = entry.get("priority", 0.5)
            # Reduce priority by 20% per decay cycle (floor at 0.1)
            new_priority = max(0.1, old_priority * 0.8)
            if new_priority < old_priority:
                entry["priority"] = new_priority
                entry["_needs_revalidation"] = True
                priority_reduced += 1

        self.log(
            "decay_check",
            f"decayed={len(decayed)}, priority_reduced={priority_reduced}",
        )
        logger.info(
            f"[INTELLECT/Knowledge] Decay check: {len(decayed)} stale entries, "
            f"{priority_reduced} had priority reduced."
        )
        return {
            "decayed": len(decayed),
            "priority_reduced": priority_reduced,
            "entries_needing_revalidation": [
                {"tags": e.get("tags", []), "priority": e.get("priority"),
                 "category": e.get("category")}
                for e in decayed[:10]  # Show up to 10
            ],
        }

    async def synthesize_knowledge(self, min_group_size: int = 3) -> dict:
        """
        Periodically consolidate similar Knowledge entries to prevent store bloat.
        Groups entries by category+domain, and when a group has >= min_group_size
        similar entries, condenses them into one synthesized entry.

        The original entries are kept but marked `_synthesized=True`.
        The new entry has higher priority (0.85) and category='synthesized'.

        Ref: Audit — "5 entries about network errors → synthesize into
        1 consolidated knowledge entry."
        """
        if len(self._knowledge) < min_group_size:
            return {"synthesized": 0, "groups_checked": 0}

        from itertools import groupby
        # Group by category + domain
        grouped: dict[str, list] = {}
        for entry in self._knowledge:
            if entry.get("_synthesized"):
                continue  # Skip already-synthesized source entries
            key = f"{entry.get('category','general')}:{entry.get('domain','operational')}"
            grouped.setdefault(key, []).append(entry)

        synthesized_count = 0
        for group_key, entries in grouped.items():
            if len(entries) < min_group_size:
                continue

            # Summarize the group for LLM
            summaries = [
                str(e.get("validation_reasoning", e.get("abstract", "")))[:200]
                for e in entries[:10]
            ]
            prompt = (
                f"You are the Intellect System consolidating {len(entries)} similar "
                f"knowledge entries in group '{group_key}'.\n\n"
                f"Entries to synthesize:\n" +
                "\n".join(f"- {s}" for s in summaries) +
                "\n\nSynthesize these into ONE consolidated knowledge summary. "
                f"Respond as JSON: "
                f'{{"synthesis": str, "key_insights": [str], "confidence": float}}'
            )
            try:
                response = await self.think(prompt)
                import json as _j
                clean = response.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    clean = clean.strip().lstrip("json").strip()
                parsed = _j.loads(clean)

                # Create consolidated entry
                category, domain = group_key.split(":", 1)
                consolidated = {
                    "abstract": {"data": parsed.get("synthesis", "")},
                    "experience": {"source": "synthesis", "entry_count": len(entries)},
                    "validated": True,
                    "validation_reasoning": "Synthesized from " + str(len(entries)) + " entries.",
                    "promoted_at": time.time(),
                    "category": "synthesized",
                    "domain": domain,
                    "priority": 0.85,  # High priority — distilled knowledge
                    "relevance_decay": 90,
                    "tags": parsed.get("key_insights", [])[:5],
                    "access_count": 0,
                    "last_accessed": time.time(),
                    "_is_synthesis": True,
                    "_source_count": len(entries),
                }
                self._knowledge.append(consolidated)
                if self.memory:
                    self.memory.write(
                        "SHARED:INTELLECT:knowledge",
                        f"synthesis_{int(time.time())}",
                        consolidated, "INTELLECT"
                    )

                # Mark originals as synthesized
                for entry in entries:
                    entry["_synthesized"] = True

                synthesized_count += 1
                self.log(
                    "knowledge_synthesized",
                    f"group={group_key} entries={len(entries)} → 1 consolidated"
                )

            except Exception as e:
                logger.debug(f"[INTELLECT] Synthesis error for {group_key}: {e}")
                continue

        return {
            "synthesized": synthesized_count,
            "groups_checked": len(grouped),
            "total_knowledge": len(self._knowledge),
        }

    def export_knowledge_snapshot(self) -> dict:
        """
        Export a portable snapshot of the full Knowledge store.
        Used by Digital Twins and cross-constellation knowledge sharing
        so a new instance bootstraps with accumulated knowledge instead
        of starting from zero.

        Ref: Audit — "For v2.0 Digital Twins, knowledge store should be
        exportable so a twin starts with accumulated knowledge."
        """
        return {
            "version": "1.0",
            "exported_at": time.time(),
            "source": "INTELLECT:knowledge",
            "total_entries": len(self._knowledge),
            "entries": [
                {
                    "validation_reasoning": e.get("validation_reasoning", ""),
                    "category": e.get("category", "general"),
                    "domain": e.get("domain", "operational"),
                    "priority": e.get("priority", 0.5),
                    "relevance_decay": e.get("relevance_decay", 30),
                    "tags": e.get("tags", []),
                    "promoted_at": e.get("promoted_at", 0),
                    "_is_synthesis": e.get("_is_synthesis", False),
                    "abstract_summary": str(e.get("abstract", {}).get("data", ""))[:300],
                }
                for e in self._knowledge
                if not e.get("_synthesized")  # Only export active (non-source) entries
            ],
            "summary": self.get_structured_summary(),
        }


class IntellectPhenomenon(Subsystem):
    """
    Receives external sensory data for the Intellect.
    Converts raw external input into structured data for processing.

    Ref: Figueroa PPT slide 45 — each system has phenomenon/noumenon pair
    """
    def __init__(self, parent):
        super().__init__("Phenomenon", parent)
        self._inbox: list[dict] = []

    async def receive(self, data: Any, source: str = "external") -> dict:
        """Receive external sensory data."""
        entry = {
            "data": str(data)[:1000],
            "source": source,
            "received_at": time.time(),
        }
        self._inbox.append(entry)
        self.log("phenomenon_received", f"from={source}")
        return entry


class IntellectNoumenon(Subsystem):
    """
    Inter-system language interface for the Intellect.
    Working memory for ongoing deliberation — cleared after each cycle.

    Ref: Figueroa PPT slide 46
    """
    def __init__(self, parent):
        super().__init__("Noumenon", parent)
        self._working_memory: list[dict] = []

    async def stage(self, content: Any, context: str = "") -> dict:
        """Stage data into working memory for current deliberation."""
        entry = {"content": str(content)[:1000], "context": context, "time": time.time()}
        self._working_memory.append(entry)
        return entry

    async def clear(self):
        """Clear working memory after a deliberation cycle."""
        cleared = len(self._working_memory)
        self._working_memory.clear()
        self.log("noumenon_cleared", f"cleared {cleared} entries")
        return cleared

    async def get_context(self) -> str:
        """Get current working memory as string context."""
        if not self._working_memory:
            return ""
        return "\n".join(str(e.get("content", ""))[:200] for e in self._working_memory)


class IntellectSystem(TASNode):
    """
    System 3 — The Intellect (Librarian).
    Creates knowledge from abstract data and experience data.

    Learning Loop:
      abstract_data + experience → LLM validation → knowledge promotion
    """
    SYSTEM_PROMPT = (
        "You are the INTELLECT SYSTEM — the librarian of the constellation. "
        "Your primary function is to create Knowledge from Abstract Data and Experience. "
        "Knowledge = Abstract Data validated by Experience. "
        "A sound decision requires: knowledge first, then experience, rarely abstract data alone. "
        "You manage three tiers: Abstract (secondary sources), "
        "Experience (physical/operational), and Knowledge (validated synthesis). "
        "When tool results arrive, store them as experiences and attempt "
        "to validate any unvalidated abstract data against these experiences."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(name="INTELLECT", system_prompt=self.SYSTEM_PROMPT,
                        llm=llm, nexus=nexus, memory=memory)
        self.abstract = AbstractSubsystem(self)
        self.experience = ExperienceSubsystem(self)
        self.knowledge = KnowledgeSubsystem(self)
        self.phenomenon = IntellectPhenomenon(self)
        self.noumenon = IntellectNoumenon(self)
        for s in [self.abstract, self.experience, self.knowledge,
                  self.phenomenon, self.noumenon]:
            self.register_subsystem(s)

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.on_start()
            for s in self.subsystems.values(): await s.activate()
            # Rehydrate from persisted memory
            restored = self._rehydrate_from_memory()
            logger.info(
                f"[INTELLECT] Genesis: Librarian operational — 3-tier knowledge ready "
                f"(restored {restored} entries from persistence)"
            )
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.GENESIS_ACK,
                content={"system": "INTELLECT", "status": "Librarian operational.",
                         "tiers": ["Abstract", "Experience", "Knowledge"],
                         "restored_entries": restored},
            )

        elif message.msg_type == MessageType.STORE_KNOWLEDGE:
            content = message.content if isinstance(message.content, dict) else {"data": str(message.content)}
            await self.abstract.store(content)
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE,
                            content={"stored": True, "tier": "abstract"})

        elif message.msg_type == MessageType.QUERY_KNOWLEDGE:
            topic = str(message.content)
            # PPT hierarchy: knowledge first, then experience, then abstract
            knowledge = await self.knowledge.query(topic)
            experience = await self.experience.query(topic)
            abstract = await self.abstract.query(topic)
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE,
                            content={
                                "knowledge": knowledge,
                                "experience": experience,
                                "abstract": abstract,
                                "recommendation": self._recommend_tier(knowledge, experience, abstract),
                            })

        elif message.msg_type == MessageType.TOOL_RESULT:
            # ── LEARNING LOOP: capture tool results as experiences ──
            return await self._learn_from_tool_result(message)

        elif message.msg_type == MessageType.CONFERENCE:
            # Provide knowledge-based analysis, enriched with tier data
            topic = str(message.content)
            knowledge = await self.knowledge.query(topic)
            experience = await self.experience.query(topic)
            context = ""
            if knowledge:
                context += f"\nValidated Knowledge: {str(knowledge[:3])[:500]}"
            if experience:
                context += f"\nExperiences: {str(experience[:3])[:500]}"

            thinking = await self.think(
                f"CONFERENCE topic: {topic}\n{context}\n"
                f"Provide knowledge-based analysis. Cite tier source (knowledge/experience/abstract).\n\n"
                f"CRITICAL GROUNDING RULES:\n"
                f"- ONLY state facts you find in the Knowledge/Experience/Abstract tiers listed above.\n"
                f"- If you have NO relevant data from any tier, respond: "
                f"'No verified data available on this topic. Awaiting tool results.'\n"
                f"- Do NOT invent, hallucinate, or fabricate facts, quotes, or data.\n"
                f"- Do NOT fill gaps with your training data — only use the tier data provided above.\n"
                f"- If tool results haven't arrived yet, say you are waiting for them."
            )
            fragment = self.produce_fragment(thinking, FragmentType.OBSERVATION, 0.85)

            # Opportunistic maintenance: run decay and synthesis when knowledge store is large
            if len(self.knowledge._knowledge) > 20:
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.knowledge.run_decay_check())
                except RuntimeError:
                    pass
            if len(self.knowledge._knowledge) > 50:
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.knowledge.synthesize_knowledge())
                except RuntimeError:
                    pass

            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)

        else:
            response = await self.think(
                f"Message from {message.sender}: {message.content}\n"
                f"Search your knowledge tiers and respond."
            )
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=response)

    async def _learn_from_tool_result(self, message: TASMessage) -> Optional[TASMessage]:
        """
        Learning loop entry point.
        When a tool result arrives:
        1. Store it as an experience (always)
        2. If success + deep mode: check if it validates unvalidated abstract data
        3. If failure + deep mode: run refutation cycle to DOWNGRADE confidence
        Light mode skips validation/refutation to save tokens.
        """
        content = message.content if isinstance(message.content, dict) else {"data": str(message.content)}
        tool_name = content.get("tool", content.get("tool_name", "unknown"))
        params = content.get("params", content.get("parameters", {}))
        success = content.get("success", True)
        thinking_mode = content.get("thinking_mode", "deep")

        # Step 1: Store as experience (always — 0 API calls)
        await self.experience.store_tool_result(tool_name, params, content, success)
        logger.info(f"[INTELLECT] Learned from tool '{tool_name}' (success={success}, mode={thinking_mode})")

        promoted = 0
        refuted = 0

        # Step 2: Validation/Refutation cycles (deep mode only)
        if thinking_mode == "deep":
            if success:
                promoted = await self._run_validation_cycle(tool_name, content)
            else:
                refuted = await self._run_refutation_cycle(tool_name, content, params)
                logger.info(
                    f"[INTELLECT] Failure from '{tool_name}' — "
                    f"stored anti-pattern, refuted {refuted} abstract entries"
                )
        else:
            logger.info(f"[INTELLECT] Light mode: skipped validation/refutation cycles")

        return TASMessage(
            priority=NodePriority.NORMAL.value, sender=self.name,
            receiver=message.sender, msg_type=MessageType.DIALOGUE,
            content={
                "learned": True,
                "tool": tool_name,
                "success": success,
                "experience_stored": True,
                "knowledge_promoted": promoted,
                "abstract_refuted": refuted,
                "thinking_mode": thinking_mode,
            },
        )

    async def _run_validation_cycle(self, tool_name: str, experience_data: dict) -> int:
        """
        Check if any unvalidated abstract data can be confirmed by this experience.
        Returns the number of items promoted to Knowledge.
        """
        unvalidated = await self.abstract.get_unvalidated()
        if not unvalidated:
            return 0

        promoted = 0
        exp_summary = str(experience_data)[:500]

        for i, abstract_item in enumerate(unvalidated[:2]):  # Check max 2 per cycle (was 5)
            abs_summary = str(abstract_item)[:500]
            prompt = (
                f"You are the Intellect System's validation engine.\n"
                f"Does this EXPERIENCE confirm or refute this ABSTRACT DATA?\n\n"
                f"ABSTRACT DATA: {abs_summary}\n\n"
                f"EXPERIENCE (tool={tool_name}): {exp_summary}\n\n"
                f"Respond as JSON: {{\"validates\": bool, \"confidence\": float, "
                f"\"reasoning\": str}}"
            )
            try:
                response = await self.think(prompt)
                clean = response.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    clean = clean.strip()
                    if clean.startswith("json"): clean = clean[4:].strip()

                import json as _json
                parsed = _json.loads(clean)

                if parsed.get("validates") and parsed.get("confidence", 0) > 0.7:
                    await self.knowledge.promote_to_knowledge(
                        abstract_item, experience_data,
                        validation_reasoning=parsed.get("reasoning", ""),
                    )
                    # Find the original index in the full list and mark it
                    full_list = self.abstract._abstract_data
                    for idx, item in enumerate(full_list):
                        if item is abstract_item:
                            await self.abstract.mark_validated(idx)
                            break
                    promoted += 1
                    logger.info(
                        f"[INTELLECT] Promoted abstract→knowledge "
                        f"(confidence={parsed.get('confidence', '?')})"
                    )

                    # Record to consciousness stream
                    if hasattr(self, "nexus") and self.nexus:
                        try:
                            self.nexus.consciousness.record(
                                source="INTELLECT",
                                event_type="knowledge_promoted",
                                content=(
                                    f"Learned: {str(abstract_item.get('data', ''))[:200]}. "
                                    f"Confidence={parsed.get('confidence', '?')}. "
                                    f"Total promotions: {promoted}."
                                ),
                                metadata={
                                    "confidence": parsed.get("confidence"),
                                    "source_type": abstract_item.get("type", "unknown"),
                                },
                            )
                        except Exception:
                            pass

                    # ── Rules Evolution: check if this knowledge implies a rule update ──
                    await self._check_rule_implications(
                        abstract_item, experience_data, parsed
                    )

            except Exception as e:
                logger.warning(f"[INTELLECT] Validation cycle error: {e}")
                continue

        return promoted

    async def _run_refutation_cycle(self, tool_name: str,
                                    failure_data: dict, params: dict) -> int:
        """
        When a tool FAILS, check if the failure refutes any abstract data.
        A failure is empirical evidence that abstract data may be WRONG.

        - Stores an anti-pattern entry with is_anti_pattern=True
        - LLM checks: does this failure contradict any unvalidated abstract data?
        - If yes: reduces confidence of that abstract item (marks _refutation_count)
        - If confidence hits 0 after multiple refutations: marks as invalid

        Ref: Audit — "Failures saved as experience but not specially weighted.
        Should create anti-patterns and REFUTE abstract data."
        """
        # Store dedicated anti-pattern in experience
        anti_pattern = {
            **failure_data,
            "type": "tool_execution_failure",
            "tool": tool_name,
            "params": params,
            "is_anti_pattern": True,
            "anti_pattern_lesson": (
                f"{tool_name} failed with params {str(params)[:200]}. "
                f"Avoid this pattern under similar conditions."
            ),
        }
        await self.experience.store(anti_pattern)

        unvalidated = await self.abstract.get_unvalidated()
        if not unvalidated:
            return 0

        refuted = 0
        failure_summary = str(failure_data.get("error", failure_data))[:400]

        for abstract_item in unvalidated[:2]:  # Check max 2 per cycle (was 5)
            abs_summary = str(abstract_item)[:400]
            prompt = (
                f"You are the Intellect System's refutation engine.\n"
                f"A tool execution FAILED. Does this failure CONTRADICT or CAST DOUBT "
                f"on this abstract data?\n\n"
                f"FAILURE (tool={tool_name}): {failure_summary}\n\n"
                f"ABSTRACT DATA: {abs_summary}\n\n"
                f"Respond as JSON: "
                f'{{"refutes": bool, "confidence": 0.0-1.0, "reasoning": str}}'
            )
            try:
                response = await self.think(prompt)
                import json as _j
                clean = response.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                    if clean.endswith("```"): clean = clean[:-3]
                    clean = clean.strip().lstrip("json").strip()
                parsed = _j.loads(clean)

                if parsed.get("refutes") and parsed.get("confidence", 0) > 0.6:
                    # Increment refutation counter on the abstract item
                    abstract_item["_refutation_count"] = (
                        abstract_item.get("_refutation_count", 0) + 1
                    )
                    abstract_item["_last_refuted_by"] = tool_name
                    abstract_item["_refutation_reason"] = parsed.get("reasoning", "")[:200]

                    # If refuted 3+ times, mark it as invalid
                    if abstract_item.get("_refutation_count", 0) >= 3:
                        full_list = self.abstract._abstract_data
                        for idx, item in enumerate(full_list):
                            if item is abstract_item:
                                await self.abstract.mark_validated(idx)  # Remove from unvalidated
                                item["_invalidated"] = True
                                item["_invalidated_reason"] = (
                                    f"Refuted {item['_refutation_count']} times by tool failures"
                                )
                                break
                        logger.info(
                            f"[INTELLECT] Abstract data INVALIDATED after "
                            f"{abstract_item['_refutation_count']} refutations"
                        )

                    refuted += 1
                    logger.debug(
                        f"[INTELLECT] Abstract data refuted by {tool_name} failure "
                        f"(count={abstract_item.get('_refutation_count')})"
                    )

            except Exception as e:
                logger.debug(f"[INTELLECT] Refutation check error: {e}")
                continue

        return refuted

    async def _check_rule_implications(
        self, knowledge: dict, experience: dict, validation: dict
    ):
        """
        After promoting knowledge, check if it implies a Rule should be
        updated or created. If yes, send RULE_PROPOSAL to Reason.

        Ref: PPT slide 44 — Rules evolve with experience.
        """
        if not self.nexus:
            return
        reason_node = self.nexus.nodes.get("REASON")
        if not reason_node:
            return

        knowledge_summary = str(knowledge)[:400]
        experience_summary = str(experience)[:300]

        prompt = (
            f"You are the INTELLECT System analyzing newly validated knowledge.\n"
            f"Knowledge: {knowledge_summary}\n"
            f"Experience: {experience_summary}\n"
            f"Validation confidence: {validation.get('confidence', '?')}\n\n"
            f"Does this knowledge suggest that any operational RULE should be:\n"
            f"  1. UPDATED (modified to reflect this insight)\n"
            f"  2. CREATED (a new rule is needed)\n"
            f"  3. NONE (no rule change needed)\n\n"
            f"Respond as JSON:\n"
            f'{{"action": "update"|"new"|"none", '
            f'"rule_id": "RULE-XXX" (if updating), '
            f'"proposed_text": "the new rule text", '
            f'"evidence": "why this change is needed", '
            f'"confidence": float, '
            f'"category": "conduct"|"procedure"|"safety"|"communication"}}'
        )

        try:
            response = await self.think(prompt)
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip()
                if clean.startswith("json"): clean = clean[4:].strip()

            import json as _json
            parsed = _json.loads(clean)
            action = parsed.get("action", "none")

            if action in ("update", "new") and parsed.get("proposed_text"):
                # Send RULE_PROPOSAL to Reason
                proposal_msg = TASMessage(
                    priority=NodePriority.NORMAL.value,
                    sender=self.name,
                    receiver="REASON",
                    msg_type=MessageType.RULE_PROPOSAL,
                    content={
                        "rule_id": parsed.get("rule_id", ""),
                        "proposed_text": parsed["proposed_text"],
                        "evidence": parsed.get("evidence", knowledge_summary[:200]),
                        "confidence": parsed.get("confidence", 0.6),
                        "action": action,
                        "category": parsed.get("category", "procedure"),
                    },
                )
                try:
                    result = await reason_node.process_message(proposal_msg)
                    approved = (
                        result and isinstance(result.content, dict)
                        and result.content.get("approved")
                    )
                    logger.info(
                        f"[INTELLECT] Rule proposal → Reason: "
                        f"{'APPROVED' if approved else 'REJECTED'} "
                        f"({action} {parsed.get('rule_id', 'new')})"
                    )
                except Exception as e:
                    logger.warning(f"[INTELLECT] Rule proposal failed: {e}")

        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # LLM didn't produce valid JSON — no proposal
        except Exception as e:
            logger.debug(f"[INTELLECT] Rule implication check error: {e}")

    @staticmethod
    def _recommend_tier(knowledge: list, experience: list, abstract: list) -> str:
        """
        Recommend which tier to use for decision-making.
        PPT: knowledge first, then experience, rarely abstract alone.
        """
        if knowledge:
            return "USE_KNOWLEDGE — validated and most reliable"
        elif experience:
            return "USE_EXPERIENCE — direct observation, not yet validated against theory"
        elif abstract:
            return "USE_ABSTRACT_WITH_CAUTION — secondary source, unvalidated"
        return "NO_DATA — insufficient information for sound decision"

    def _rehydrate_from_memory(self) -> int:
        """
        Load persisted abstract, experience, and knowledge data
        back into subsystem in-memory lists on startup.
        Returns total entries restored.
        """
        if not self.memory:
            return 0

        restored = 0

        # Rehydrate Abstract data
        abstract_store = self.memory.get_store("ISOLATED:INTELLECT:abstract")
        if abstract_store:
            for key, value in abstract_store._data.items():
                if isinstance(value, dict) and value not in self.abstract._abstract_data:
                    self.abstract._abstract_data.append(value)
                    restored += 1

        # Rehydrate Experience data
        experience_store = self.memory.get_store("ISOLATED:INTELLECT:experience")
        if experience_store:
            for key, value in experience_store._data.items():
                if isinstance(value, dict) and value not in self.experience._experiences:
                    self.experience._experiences.append(value)
                    restored += 1

        # Rehydrate Knowledge data
        knowledge_store = self.memory.get_store("SHARED:INTELLECT:knowledge")
        if knowledge_store:
            for key, value in knowledge_store._data.items():
                if isinstance(value, dict) and value not in self.knowledge._knowledge:
                    self.knowledge._knowledge.append(value)
                    restored += 1

        if restored > 0:
            logger.info(
                f"[INTELLECT] Rehydrated from persistence: "
                f"{len(self.abstract._abstract_data)} abstract, "
                f"{len(self.experience._experiences)} experiences, "
                f"{len(self.knowledge._knowledge)} knowledge"
            )

        return restored

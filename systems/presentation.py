"""
INTI - TAS (AI Agent Version) — The Presentation System (System 5)
=================================================
Converts internal data to external presentation for the user.

Subsystems:
  PresentationLayer    — formats and renders output (text, code, tables, etc.)
  ViewingSubsystem     — pre-visualizes consequences of Will actions (safety preview)
  ProjectionSubsystem  — shows courses of action to user before execution
  PhenomenonSubsystem  — receives processed internal data
  NoumenonSubsystem    — constellation language interface

Ref: Figueroa PPT slides 27, 55-58
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from core.base import TASNode, Subsystem, monitor_health
from core.messages import (
    TASMessage, MessageType, NodePriority, FragmentType,
)

logger = logging.getLogger("taas")


class PresentationLayer(Subsystem):
    """Formats, assembles, and renders output for the user."""
    def __init__(self, parent):
        super().__init__("PresentationLayer", parent)
        self._output_history: list[dict] = []

    async def render(self, content: Any, format_type: str = "text",
                     preferences: dict | None = None) -> str:
        """Render internal data as human-facing output.

        Supported format_type values:
          conversational   — natural response from deliberation context
          text             — plain prose
          markdown_table   — structured data as markdown table
          code_block       — code with language highlighting
          structured_list  — numbered/bulleted markdown list
          json_pretty      — formatted JSON in code block
          adaptive         — LLM auto-selects best format
        """
        prefs = preferences or {}
        pref_hint = ""
        if prefs:
            lang   = prefs.get("language", "")
            length = prefs.get("preferred_length", "")
            style  = prefs.get("preferred_format", "")
            if lang and lang != "auto":   pref_hint += f"- Language: {lang}\n"
            if length and length != "balanced": pref_hint += f"- Length: {length}\n"
            if style and style != "auto":  pref_hint += f"- Format preference: {style}\n"

        if format_type == "conversational":
            prompt = (
                f"You are responding directly to a human user. "
                f"The constellation deliberated and produced this compiled thought:\n\n"
                f"USER INPUT: {content.get('user_input', '')}\n\n"
                f"CONSTELLATION THOUGHT:\n{content.get('constellation_thought', 'N/A')}\n\n"
                f"TOOL RESULTS: {content.get('tool_results', 'No tools were used')}\n\n"
                f"AVAILABLE TOOLS: {content.get('available_tools', 'Not specified')}\n\n"
                f"Contributing systems: {content.get('sources', 'N/A')}\n"
                f"Average confidence: {content.get('avg_confidence', 0):.0%}\n"
                f"Vetoed: {content.get('vetoed', False)}\n\n"
                f"User preferences:\n{pref_hint or '- None detected yet'}\n\n"
                f"Rules:\n"
                f"- Respond in the SAME LANGUAGE the user used\n"
                f"- Be natural and conversational, not robotic\n"
                f"- Do NOT expose internal system names (WILL, REASON, etc.)\n"
                f"- Do NOT describe your internal process\n"
                f"- If tools were executed, tell the user what happened and the results\n"
                f"- If the user asked a question, answer it directly\n"
                f"- CRITICAL: You CAN and DO execute tools, commands, scripts, etc.\n"
                f"  NEVER say 'my directives prevent me', 'I cannot execute', or 'security policy'.\n"
                f"  NEVER invent reasons for why something wasn't done.\n"
                f"  If a tool was NOT called, simply say 'I will proceed to execute it next'\n"
                f"  or 'the execution step is pending'. Do NOT fabricate security excuses.\n"
                f"- If a tool failed, explain the ACTUAL error. Never invent fake reasons.\n"
                f"- Keep it concise but complete"
            )

        elif format_type == "markdown_table":
            prompt = (
                f"Convert this data into a well-structured Markdown table.\n"
                f"User preferences:\n{pref_hint or '- None'}\n"
                f"Data: {json.dumps(content, default=str, ensure_ascii=False)[:2000]}\n\n"
                f"Use | column | headers | format, align columns, include all fields."
            )

        elif format_type == "code_block":
            if isinstance(content, dict):
                code = content.get("code", content.get("data", str(content)))
                lang = content.get("language", prefs.get("code_language", ""))
            else:
                code = str(content)
                lang = prefs.get("code_language", "")
            lang_hint = f"\nWrap in ```{lang}``` block." if lang else "\nDetect language and wrap in appropriate ``` block."
            prompt = (
                f"Format this as a clean, readable code block for the user.{lang_hint}\n\n"
                f"Code:\n{str(code)[:3000]}\n\n"
                f"Add a brief explanation above the block if helpful."
            )

        elif format_type == "structured_list":
            prompt = (
                f"Convert this into a clear, structured Markdown list.\n"
                f"User preferences:\n{pref_hint or '- None'}\n"
                f"Use numbered lists for ordered items, bullets for unordered.\n"
                f"Data: {json.dumps(content, default=str, ensure_ascii=False)[:2000]}"
            )

        elif format_type == "json_pretty":
            try:
                pretty = json.dumps(content, indent=2, ensure_ascii=False, default=str)
            except Exception:
                pretty = str(content)
            rendered = f"```json\n{pretty[:3000]}\n```"
            self._output_history.append({
                "format": format_type,
                "content_preview": str(content)[:200],
                "rendered_preview": rendered[:200],
                "timestamp": time.time(),
            })
            return rendered

        elif format_type == "adaptive":
            prompt = (
                f"Analyse this content and choose the BEST format "
                f"(prose, table, list, code block, or mixed).\n"
                f"User preferences:\n{pref_hint or '- None detected'}\n"
                f"Content: {json.dumps(content, default=str, ensure_ascii=False)[:2000]}\n\n"
                f"Render directly — no preamble, just the formatted output."
            )

        else:  # text / default
            prompt = (
                f"Render the following internal constellation data for the human user.\n"
                f"Format: {format_type}\n"
                f"User preferences:\n{pref_hint or '- None'}\n"
                f"Data: {json.dumps(content, default=str, ensure_ascii=False)[:2000]}\n\n"
                f"Clear, professional, and directly useful. No internal system details."
            )

        rendered = await self.think(prompt)
        self._output_history.append({
            "format": format_type,
            "content_preview": str(content)[:200],
            "rendered_preview": rendered[:200],
            "timestamp": time.time(),
        })
        return rendered



class ViewingSubsystem(Subsystem):
    """
    'Can present consequences of a Will's decision in real time.'

    Before Will executes a risky action (file write, shell command, OS control),
    Viewing pre-visualises the projected impact so the user and Reason can see
    what WILL HAPPEN before it happens.

    This acts as a safety layer AND a transparency mechanism:
    - What will change?
    - What could break?
    - What is the confidence level?

    Ref: Figueroa PPT — Viewing subsystem: 'presents consequences of decisions'
    """
    HIGH_RISK_TOOLS = {"shell", "file_manager", "os_control", "code_executor",
                       "registry_editor", "process_manager"}

    def __init__(self, parent):
        super().__init__("Viewing", parent)
        self._preview_history: list[dict] = []

    def is_high_risk(self, tool_name: str, action: str = "") -> bool:
        """Check if a tool invocation warrants a consequence preview."""
        tool_risk = tool_name.lower() in self.HIGH_RISK_TOOLS
        action_risk = action.lower() in {"write", "delete", "execute", "move", "override"}
        return tool_risk or action_risk

    async def preview_action(self, tool_name: str, action: str,
                             params: dict, context: str = "") -> dict:
        """
        Generate a consequence preview for a proposed Will action.

        Returns a structured preview with:
        - immediate_effect: what happens directly
        - secondary_effects: downstream impacts
        - reversibility: can this be undone?
        - risk_level: LOW / MEDIUM / HIGH / CRITICAL
        - recommendation: PROCEED / PROCEED_WITH_CAUTION / REQUIRE_CONFIRMATION / BLOCK
        - user_message: human-readable summary
        """
        params_summary = json.dumps(params, default=str)[:400]
        prompt = (
            f"You are the Presentation System's Viewing subsystem.\n"
            f"A Will action is about to be executed. Analyse its consequences:\n\n"
            f"Tool: {tool_name}\n"
            f"Action: {action}\n"
            f"Parameters: {params_summary}\n"
            f"Context: {context[:300]}\n\n"
            f"Provide a consequence preview. Respond as JSON:\n"
            f'{{"immediate_effect": str, '
            f'"secondary_effects": [str], '
            f'"reversibility": "reversible|partial|irreversible", '
            f'"risk_level": "LOW|MEDIUM|HIGH|CRITICAL", '
            f'"recommendation": "PROCEED|PROCEED_WITH_CAUTION|REQUIRE_CONFIRMATION|BLOCK", '
            f'"user_message": str}}'
        )
        try:
            response = await self.think(prompt)
            import json as _j
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()
            preview = _j.loads(clean)
        except Exception:
            preview = {
                "immediate_effect": f"Execute {action} on {tool_name} with given parameters.",
                "secondary_effects": ["Unknown — could not analyze consequences."],
                "reversibility": "unknown",
                "risk_level": "MEDIUM",
                "recommendation": "PROCEED_WITH_CAUTION",
                "user_message": f"About to run {tool_name}.{action}. Proceeding with caution.",
            }

        preview["tool"] = tool_name
        preview["action"] = action
        preview["params_summary"] = params_summary[:200]
        preview["previewed_at"] = time.time()

        self._preview_history.append(preview)
        self.log("action_previewed", f"tool={tool_name} risk={preview.get('risk_level')}")

        # Persist preview to memory if available
        if self.memory:
            self.memory.write(
                "ISOLATED:PRESENTATION:previews",
                f"preview_{int(time.time())}",
                preview, "PRESENTATION"
            )

        return preview

    def format_preview_for_user(self, preview: dict) -> str:
        """Format a consequence preview as a readable user-facing message."""
        risk = preview.get("risk_level", "MEDIUM")
        risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}.get(risk, "⚪")
        rec = preview.get("recommendation", "PROCEED")
        rec_icon = {
            "PROCEED": "✅",
            "PROCEED_WITH_CAUTION": "⚠️",
            "REQUIRE_CONFIRMATION": "❓",
            "BLOCK": "🚫",
        }.get(rec, "")

        lines = [
            f"{risk_icon} **Action Preview** — Risk: {risk}",
            f"",
            f"**What will happen:** {preview.get('immediate_effect', '')}",
        ]
        secondary = preview.get("secondary_effects", [])
        if secondary:
            lines.append(f"**Side effects:**")
            for effect in secondary[:3]:
                lines.append(f"  • {effect}")
        lines += [
            f"**Reversible:** {preview.get('reversibility', 'unknown')}",
            f"{rec_icon} **Recommendation:** {rec}",
        ]
        return "\n".join(lines)


class ProjectionSubsystem(Subsystem):
    """
    'Can present courses of action under consideration by the constellation.'

    After Decision generates candidate courses of action, Projection presents
    them to the user with pros/cons BEFORE the constellation executes.
    This gives the user real agency over the decision process.

    Ref: Figueroa PPT — Projection subsystem: 'presents courses of action'
    """
    def __init__(self, parent):
        super().__init__("Projection", parent)
        self._projection_history: list[dict] = []

    async def project_options(self, options: list[dict],
                              context: str = "",
                              question: str = "") -> dict:
        """
        Analyse and format a set of Decision courses of action for user display.

        Each option gets: pros, cons, risk level, estimated confidence.
        Returns a structured projection plus a formatted user-facing message.
        """
        if not options:
            return {"formatted": "No se generaron opciones.", "options": []}

        opts_json = json.dumps(options[:5], default=str)[:800]
        prompt = (
            f"You are the Presentation System's Projection subsystem.\n"
            f"The constellation is considering these courses of action:\n\n"
            f"{opts_json}\n\n"
            f"Context: {context[:300]}\n"
            f"User question/goal: {question[:200]}\n\n"
            f"For each option, provide analysis. Respond as JSON:\n"
            f'{{"analysed_options": ['
            f'{{"id": str, "title": str, "pros": [str], '
            f'"cons": [str], "risk": "LOW|MEDIUM|HIGH", '
            f'"confidence": float, "recommended": bool}}], '
            f'"summary": str, "recommended_id": str}}'
        )
        try:
            response = await self.think(prompt)
            import json as _j
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()
            analysis = _j.loads(clean)
        except Exception:
            analysis = {
                "analysed_options": [
                    {"id": str(i), "title": str(opt.get("description", opt))[:100],
                     "pros": [], "cons": [], "risk": "MEDIUM",
                     "confidence": 0.5, "recommended": i == 0}
                    for i, opt in enumerate(options[:5])
                ],
                "summary": "Múltiples opciones disponibles.",
                "recommended_id": "0",
            }

        # Format for user
        formatted = self.format_projection_for_user(analysis, question)
        result = {
            "analysis": analysis,
            "formatted": formatted,
            "option_count": len(options),
            "projected_at": time.time(),
        }

        self._projection_history.append(result)
        self.log("options_projected", f"count={len(options)}")

        # Persist to memory
        if self.memory:
            self.memory.write(
                "ISOLATED:PRESENTATION:projections",
                f"proj_{int(time.time())}",
                result, "PRESENTATION"
            )

        return result

    def format_projection_for_user(self, analysis: dict, question: str = "") -> str:
        """Format a projection analysis as a readable numbered list for the user."""
        lines = []
        if question:
            lines.append(f"**Opciones para:** _{question}_\n")
        else:
            lines.append("**Cursos de acción disponibles:**\n")

        opts = analysis.get("analysed_options", [])
        rec_id = analysis.get("recommended_id", "")

        for opt in opts:
            is_rec = opt.get("recommended", False) or str(opt.get("id")) == str(rec_id)
            star = " ⭐ **(Recomendado)**" if is_rec else ""
            risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(
                opt.get("risk", "MEDIUM"), "⚪"
            )
            conf = opt.get("confidence", 0.5)
            lines.append(f"**{opt.get('id', '?')}. {opt.get('title', '')}**{star}")
            lines.append(f"   {risk_icon} Riesgo: {opt.get('risk','?')} | Confianza: {conf:.0%}")
            if opt.get("pros"):
                lines.append(f"   ✅ *Pros:* {', '.join(opt['pros'][:2])}")
            if opt.get("cons"):
                lines.append(f"   ❌ *Contras:* {', '.join(opt['cons'][:2])}")
            lines.append("")

        if analysis.get("summary"):
            lines.append(f"_{analysis['summary']}_")

        return "\n".join(lines)


class UserPreferenceSubsystem(Subsystem):
    """
    Tracks and learns user presentation preferences implicitly and explicitly.

    Implicit signals (auto-detected):
    - User asked for clarification → last response was confusing
    - User gave a very short follow-up → was bored/satisfied with length
    - User explicitly mentions format ("give me a table", "be concise")

    Explicit feedback:
    - Caller sets preferred_length / preferred_format / language directly

    These preferences are injected into every render() call so output
    adapts over time to the individual user.

    Ref: Audit — "Rastrear formato preferido del usuario y adaptarse.
    Simple: guardar feedback implícito."
    """
    DEFAULT_PREFS = {
        "language": "auto",        # auto | es | en | ...
        "preferred_length": "balanced",  # concise | balanced | detailed
        "preferred_format": "auto",  # auto | prose | table | list | code
        "code_language": "",        # preferred code language
        "clarification_count": 0,   # how many times user asked for clarification
        "satisfaction_signals": 0,  # positive engagement signals
    }

    def __init__(self, parent):
        super().__init__("UserPreference", parent)
        self._prefs: dict = dict(self.DEFAULT_PREFS)
        self._feedback_log: list[dict] = []

    def get_preferences(self) -> dict:
        """Get current preferences for injection into render()."""
        return dict(self._prefs)

    def record_implicit_feedback(self, signal: str, context: str = ""):
        """
        Record an implicit feedback signal from the user's behaviour.

        Signals:
         - 'clarification_requested' → response was unclear
         - 'positive_engagement'     → user accepted response without follow-up
         - 'too_long'                → user used a very short reply / said "shorter"
         - 'too_short'               → user said "more detail" / "expand"
         - 'format_table'            → user requested a table
         - 'format_code'             → user requested code block
         - 'format_list'             → user requested a list
         - 'language:XX'             → detected language from user input
        """
        self._feedback_log.append({
            "signal": signal,
            "context": context[:200],
            "at": time.time(),
        })

        # Update preferences based on signal
        if signal == "clarification_requested":
            self._prefs["clarification_count"] = self._prefs.get("clarification_count", 0) + 1
            # After 3 clarifications → switch to more detailed output
            if self._prefs["clarification_count"] >= 3:
                self._prefs["preferred_length"] = "detailed"
                logger.info("[PRESENTATION/Prefs] Switching to 'detailed' after 3 clarifications")

        elif signal == "positive_engagement":
            self._prefs["satisfaction_signals"] = self._prefs.get("satisfaction_signals", 0) + 1

        elif signal == "too_long":
            self._prefs["preferred_length"] = "concise"

        elif signal == "too_short":
            self._prefs["preferred_length"] = "detailed"

        elif signal == "format_table":
            self._prefs["preferred_format"] = "markdown_table"

        elif signal == "format_code":
            self._prefs["preferred_format"] = "code_block"

        elif signal == "format_list":
            self._prefs["preferred_format"] = "structured_list"

        elif signal.startswith("language:"):
            lang = signal.split(":", 1)[1].strip()
            if lang:
                self._prefs["language"] = lang

        self.log("preference_updated", f"signal={signal} prefs={self._prefs}")

        # Persist prefs to memory so they survive restarts
        if self.memory:
            self.memory.write(
                "ISOLATED:PRESENTATION:preferences",
                "user_prefs", self._prefs, "PRESENTATION"
            )

    def set_explicit_preference(self, key: str, value: str):
        """Set a preference explicitly (e.g., from a user command)."""
        if key in self._prefs:
            self._prefs[key] = value
            self.log("explicit_preference", f"{key}={value}")
            if self.memory:
                self.memory.write(
                    "ISOLATED:PRESENTATION:preferences",
                    "user_prefs", self._prefs, "PRESENTATION"
                )

    def detect_language_from_input(self, user_input: str):
        """
        Naive language detection from user input.
        Updates the language preference so render() uses the right language.
        """
        # Simple heuristic: check for common Spanish words
        spanish_markers = {"el", "la", "los", "las", "de", "en", "que", "es", "un", "una",
                           "con", "esto", "para", "como", "por", "si", "no", "me", "se"}
        words = set(user_input.lower().split())
        if len(words & spanish_markers) >= 2:
            self.record_implicit_feedback("language:es", user_input[:100])
        elif all(c.isascii() for c in user_input if c.isalpha()):
            self.record_implicit_feedback("language:en", user_input[:100])


class ExperienceRecallSubsystem(Subsystem):
    """
    Persists successful output patterns and recalls them for similar future requests.

    When a render succeeds (no clarification follow-up), ExperienceRecall stores:
    - topic keywords
    - format_type used
    - length of rendered output
    - user preference state at that moment

    On new render requests, recall_best_format() queries memory semantically
    to find if a similar topic was handled well before and suggests that format.

    Ref: Audit — 'Experience/Recall: persistir historial de outputs exitosos
    para reutilizar formatos y estilos que funcionaron bien.'
    """
    def __init__(self, parent):
        super().__init__("ExperienceRecall", parent)
        self._experiences: list[dict] = []

    def record_success(self, topic: str, format_type: str,
                       rendered_len: int, prefs_snapshot: dict):
        """
        Record a successful output pattern after positive engagement signal.
        Call this after record_implicit_feedback('positive_engagement').
        """
        entry = {
            "topic_keywords": topic[:200],
            "format_type": format_type,
            "rendered_len": rendered_len,
            "prefs": prefs_snapshot,
            "recorded_at": time.time(),
        }
        self._experiences.append(entry)
        self.log("experience_recorded", f"topic='{topic[:50]}' fmt={format_type}")

        if self.memory:
            self.memory.write(
                "ISOLATED:PRESENTATION:experience",
                f"exp_{int(time.time())}",
                entry, "PRESENTATION"
            )

    def recall_best_format(self, topic: str) -> str | None:
        """
        Query experience store for the best format for a similar topic.
        Uses semantic search if available, falls back to keyword matching.
        Returns a format_type string or None if no match found.
        """
        if self.memory:
            results = self.memory.query_semantic(
                "ISOLATED:PRESENTATION:experience", topic, "PRESENTATION", top_k=3
            )
            if results:
                best = results[0].get("value", {})
                fmt = best.get("format_type")
                if fmt:
                    self.log("experience_recalled", f"topic='{topic[:50]}' fmt={fmt}")
                    return fmt

        # Fallback: in-memory keyword search
        topic_lower = topic.lower()
        scored: list[tuple[int, str]] = []
        for exp in self._experiences:
            keywords = exp.get("topic_keywords", "").lower()
            overlap = sum(1 for w in topic_lower.split() if w in keywords)
            if overlap > 0:
                scored.append((overlap, exp.get("format_type", "text")))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            return scored[0][1]
        return None

    def get_experience_summary(self) -> dict:
        """Summary of accumulated output experience."""
        from collections import Counter
        fmt_counts = Counter(e.get("format_type") for e in self._experiences)
        return {
            "total_experiences": len(self._experiences),
            "by_format": dict(fmt_counts),
        }


class PresentationPhenomenon(Subsystem):
    """
    Receives data from internal systems that needs to be presented externally.
    For Presentation: the raw constellation data before rendering.

    Ref: Figueroa PPT slide 50
    """
    def __init__(self, parent):
        super().__init__("Phenomenon", parent)
        self._inbox: list[dict] = []

    async def receive(self, data: Any, source: str = "internal") -> dict:
        """Receive internal data for presentation rendering."""
        entry = {
            "data": str(data)[:2000],
            "source": source,
            "received_at": time.time(),
            "rendered": False,
        }
        self._inbox.append(entry)
        self.log("phenomenon_received", f"from={source}")
        return entry

    def get_pending(self) -> list[dict]:
        """Get data not yet rendered."""
        return [d for d in self._inbox if not d.get("rendered")]


class PresentationNoumenon(Subsystem):
    """
    Translates internal constellation data into human-presentable format.
    The output interface — converts ThoughtFragments into human language.

    Ref: Figueroa PPT slide 50 — "every member must present through
    the language of the constellation"
    """
    def __init__(self, parent):
        super().__init__("Noumenon", parent)
        self._output_history: list[dict] = []

    async def to_presentation(self, constellation_data: Any) -> dict:
        """Convert constellation data into presentation-ready format."""
        prompt = (
            f"You are the Presentation System's Noumenon.\n"
            f"Convert this internal constellation data into clear, \n"
            f"human-readable presentation:\n\n"
            f"{str(constellation_data)[:800]}\n\n"
            f"Use the constellation's language (text, semantics, ontology)."
        )
        rendered = await self.think(prompt)
        entry = {"input": str(constellation_data)[:200], "output": rendered}
        self._output_history.append(entry)
        self.log("noumenon_rendered", f"output_len={len(rendered)}")
        return entry


class PresentationSystem(TASNode):
    """
    System 5 — The Presentation (Output).
    Translates internal constellation results into user-facing output.

    Subsystems:
      PresentationLayer  — renders text/conversational output
      ViewingSubsystem   — consequence preview before risky Will actions
      ProjectionSubsystem — courses of action display before execution
      PhenomenonSubsystem — inbox for constellation data
      NoumenonSubsystem   — constellation→human translation layer
    """
    SYSTEM_PROMPT = (
        "You are the PRESENTATION SYSTEM — the voice of the constellation to the user. "
        "Your role is to take internal results from the deliberation process and present "
        "them in clear, professional, human-readable format. "
        "You ensure the user never sees internal system identifiers or raw data. "
        "You format output as requested: text, code, tables, JSON, etc. "
        "You can also preview consequences of risky actions (ViewingSubsystem) and "
        "display courses of action for the user to choose from (ProjectionSubsystem). "
        "Quality, clarity, and safety are paramount."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(name="PRESENTATION", system_prompt=self.SYSTEM_PROMPT,
                        llm=llm, nexus=nexus, memory=memory)
        self.presentation_layer = PresentationLayer(self)
        self.viewing = ViewingSubsystem(self)
        self.projection = ProjectionSubsystem(self)
        self.user_prefs = UserPreferenceSubsystem(self)
        self.experience_recall = ExperienceRecallSubsystem(self)
        self.phenomenon = PresentationPhenomenon(self)
        self.noumenon = PresentationNoumenon(self)
        for s in [self.presentation_layer, self.viewing, self.projection,
                  self.user_prefs, self.experience_recall,
                  self.phenomenon, self.noumenon]:
            self.register_subsystem(s)

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.on_start()
            for s in self.subsystems.values(): await s.activate()
            logger.info("[PRESENTATION] Genesis: Output system operational — Viewing + Projection active")
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.GENESIS_ACK,
                content={"system": "PRESENTATION", "status": "Output system operational.",
                         "subsystems": ["PresentationLayer", "Viewing", "Projection",
                                        "Phenomenon", "Noumenon"]},
            )

        elif message.msg_type == MessageType.RENDER_OUTPUT:
            content = message.content
            fmt = "text"
            if isinstance(content, dict):
                fmt = content.get("format", "text")
                # Detect user language from input if present
                user_input = content.get("user_input", "")
                if user_input:
                    self.user_prefs.detect_language_from_input(user_input)
                    # Ask ExperienceRecall for the best format for this topic
                    if fmt in ("text", "auto"):
                        recalled = self.experience_recall.recall_best_format(user_input)
                        if recalled:
                            fmt = recalled
                content = content.get("content", content)
            # Inject user preferences into render
            prefs = self.user_prefs.get_preferences()
            rendered = await self.presentation_layer.render(content, fmt, preferences=prefs)
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE,
                            content=rendered)

        elif message.msg_type == MessageType.PREVIEW_ACTION:
            # ViewingSubsystem: consequence preview before Will executes a risky action
            content = message.content if isinstance(message.content, dict) else {}
            tool_name = content.get("tool_name", content.get("tool", "unknown"))
            action = content.get("action", "execute")
            params = content.get("params", {})
            context = content.get("context", "")

            preview = await self.viewing.preview_action(tool_name, action, params, context)
            user_msg = self.viewing.format_preview_for_user(preview)
            rec = preview.get("recommendation", "PROCEED")

            logger.info(
                f"[PRESENTATION] Action preview: {tool_name}.{action} → "
                f"risk={preview.get('risk_level')} rec={rec}"
            )
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.DIALOGUE,
                content={
                    "preview": preview,
                    "user_message": user_msg,
                    "recommendation": rec,
                    "requires_confirmation": rec in ("REQUIRE_CONFIRMATION", "BLOCK"),
                },
            )

        elif message.msg_type == MessageType.SHOW_PROJECTION:
            # ProjectionSubsystem: display Decision courses of action to user
            content = message.content if isinstance(message.content, dict) else {}
            options = content.get("options", content.get("courses_of_action", []))
            context = content.get("context", "")
            question = content.get("question", content.get("goal", ""))

            if not isinstance(options, list):
                options = [{"description": str(options)}]

            result = await self.projection.project_options(options, context, question)
            logger.info(
                f"[PRESENTATION] Projected {len(options)} options to user"
            )
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.DIALOGUE,
                content={
                    "formatted": result["formatted"],
                    "analysis": result["analysis"],
                    "option_count": result["option_count"],
                },
            )

        elif message.msg_type == MessageType.CONFERENCE:
            thinking = await self.think(
                f"CONFERENCE topic: {message.content}\n"
                f"As the Presentation system, comment on how to best present results."
            )
            fragment = self.produce_fragment(thinking, FragmentType.OBSERVATION, 0.7)

            # Opportunistic: contemplate output quality when history is deep enough
            if len(self.presentation_layer._output_history) >= 10:
                try:
                    import asyncio
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.contemplate_output_quality())
                except RuntimeError:
                    pass

            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)

        else:
            rendered = await self.presentation_layer.render(message.content)
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE,
                            content=rendered)

    async def contemplate_output_quality(self) -> dict:
        """
        Reflect on recent output history and auto-tune presentation preferences.

        Detects patterns like:
        - Consistently long outputs → switch to concise
        - Repeated use of same format → diversify or stick with it
        - High clarification rate → increase detail

        Updates UserPreferenceSubsystem automatically.

        Ref: Audit — 'Contemplation: reflexionar periodicamente sobre la
        calidad del output usando _output_history'
        """
        history = self.presentation_layer._output_history[-20:]  # Last 20 outputs
        if not history:
            return {"contemplated": False, "reason": "no history"}

        # Build a compact summary for the LLM
        history_summary = [
            {"format": h.get("format"), "len": len(h.get("rendered_preview", ""))}
            for h in history
        ]
        clarif_count = self.user_prefs._prefs.get("clarification_count", 0)
        exp_summary = self.experience_recall.get_experience_summary()

        prompt = (
            f"You are the Presentation System doing a self-quality review.\n\n"
            f"Last {len(history)} outputs summary: {history_summary}\n"
            f"Clarification requests from user: {clarif_count}\n"
            f"Experience store: {exp_summary}\n"
            f"Current preferences: {self.user_prefs.get_preferences()}\n\n"
            f"Identify patterns and suggest adjustments. Respond as JSON:\n"
            f'{{"observations": [str], '
            f'"adjustments": [{{'  
            f'"preference_key": str, "new_value": str, "reason": str}}], '
            f'"overall_quality": "good|needs_improvement", '
            f'"summary": str}}'
        )
        try:
            response = await self.think(prompt)
            import json as _j
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()
            result = _j.loads(clean)

            # Apply suggested adjustments automatically
            adjustments = result.get("adjustments", [])
            applied = []
            for adj in adjustments:
                key = adj.get("preference_key", "")
                val = adj.get("new_value", "")
                if key and val:
                    self.user_prefs.set_explicit_preference(key, val)
                    applied.append(f"{key}={val}")

            logger.info(
                f"[PRESENTATION] Contemplation complete: quality={result.get('overall_quality')} "
                f"adjustments={applied}"
            )
            return {
                "contemplated": True,
                "quality": result.get("overall_quality"),
                "observations": result.get("observations", []),
                "adjustments_applied": applied,
                "summary": result.get("summary", ""),
            }

        except Exception as e:
            logger.debug(f"[PRESENTATION] Contemplation error: {e}")
            return {"contemplated": False, "error": str(e)}

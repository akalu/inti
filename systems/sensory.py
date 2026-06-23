"""
INTI - TAS (AI Agent Version) — The Sensory System (System 6)
==========================================
All incoming sensory experience — the system-to-world boundary.

Subsystems:
  StandardsAndLimits   — operational boundaries, danger thresholds
  SystemStateSubsystem — current state monitoring via ISHM
  QualitySensorySub    — quality of incoming data assessment
  VisualInputSubsystem — screen capture and visual interpretation
  PhenomenonSubsystem  — raw external data input
  NoumenonSubsystem    — constellation language output

Ref: Figueroa PPT slides 28, 59-62
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


class StandardsAndLimits(Subsystem):
    """
    Operational boundaries.
    Defines danger thresholds that, when exceeded,
    trigger alerts to Will's Survival Subsystem.
    """
    def __init__(self, parent):
        super().__init__("StandardsAndLimits", parent)
        self.limits = {
            "max_error_rate": 0.5,
            "max_response_time_ms": 30000,
            "min_confidence": 0.3,
            "max_queue_depth": 200,
        }

    def check_limit(self, metric: str, value: float) -> dict:
        limit = self.limits.get(metric)
        if limit is None:
            return {"within_limits": True, "metric": metric}
        exceeded = False
        if "max" in metric:
            exceeded = value > limit
        elif "min" in metric:
            exceeded = value < limit
        return {
            "within_limits": not exceeded,
            "metric": metric,
            "value": value,
            "limit": limit,
            "exceeded": exceeded,
        }


class SystemStateSubsystem(Subsystem):
    """
    Current state monitoring via ISHM.
    Maintains a snapshot of the entire constellation's health.
    """
    def __init__(self, parent):
        super().__init__("SystemState", parent)
        self._state_history: list[dict] = []

    async def capture_state(self) -> dict:
        state = {
            "timestamp": time.time(),
            "systems": {},
        }
        if self.nexus:
            for name, node in self.nexus.nodes.items():
                state["systems"][name] = node.get_status()
        self._state_history.append(state)
        return state


class QualitySensorySubsystem(Subsystem):
    """
    Assesses the quality and trustworthiness of incoming data.
    Uses deterministic scoring across 5 dimensions (no LLM).

    Dimensions:
      completeness      (0.25) — data non-empty, meets minimum length
      source_reliability (0.25) — known source types scored by trust level
      freshness         (0.15) — data age vs operational time limit
      consistency       (0.15) — similarity to recent data patterns
      size_adequacy     (0.20) — Goldilocks: not too short, not too long

    Ref: Figueroa PPT slide 49
    """

    # Source reliability scores — deterministic trust levels
    SOURCE_TRUST = {
        "user": 1.0,       # Human input always trusted
        "tool": 0.85,      # Tool results generally reliable
        "api": 0.8,        # API responses
        "system": 0.9,     # Internal system messages
        "web": 0.6,        # Web-scraped data less reliable
        "external": 0.5,   # Generic external data
        "unknown": 0.3,    # Unknown source = low trust
    }

    # Dimension weights (must sum to 1.0)
    WEIGHTS = {
        "completeness": 0.25,
        "source_reliability": 0.25,
        "freshness": 0.15,
        "consistency": 0.15,
        "size_adequacy": 0.20,
    }

    def __init__(self, parent):
        super().__init__("QualitySensory", parent)
        self._quality_history: list[dict] = []
        self._recent_sizes: list[int] = []  # Tracks recent data sizes for consistency

    def assess(self, data: str, source: str = "unknown",
               data_type: str = "unknown",
               received_at: float | None = None) -> dict:
        """
        Assess the quality of incoming sensory data.
        Pure math — no LLM calls.

        Returns:
          {quality_score, dimensions, low_quality, data_type, source}
        """
        now = time.time()
        if received_at is None:
            received_at = now

        data_len = len(data) if data else 0

        # ── Dimension 1: Completeness (is there actual data?) ──
        if data_len == 0:
            completeness = 0.0
        elif data_len < 3:
            completeness = 0.2
        elif data_len < 10:
            completeness = 0.5
        else:
            completeness = min(1.0, 0.6 + (data_len / 500) * 0.4)

        # ── Dimension 2: Source Reliability ──
        source_key = source.lower().strip()
        source_reliability = self.SOURCE_TRUST.get(
            source_key, self.SOURCE_TRUST["unknown"]
        )

        # ── Dimension 3: Freshness (age of data) ──
        age_seconds = now - received_at
        max_age = 30.0  # StandardsAndLimits.max_response_time_ms / 1000
        if age_seconds <= 0.1:
            freshness = 1.0  # Just received
        elif age_seconds < max_age:
            freshness = 1.0 - (age_seconds / max_age) * 0.5
        else:
            freshness = max(0.1, 0.5 - (age_seconds - max_age) / 120.0)

        # ── Dimension 4: Consistency (vs recent data patterns) ──
        if not self._recent_sizes:
            consistency = 0.7  # No history = neutral
        else:
            avg_size = sum(self._recent_sizes) / len(self._recent_sizes)
            if avg_size > 0:
                deviation = abs(data_len - avg_size) / max(avg_size, 1)
                consistency = max(0.1, 1.0 - deviation * 0.5)
            else:
                consistency = 0.5

        # ── Dimension 5: Size Adequacy (Goldilocks) ──
        if data_len == 0:
            size_adequacy = 0.0
        elif data_len < 5:
            size_adequacy = 0.2  # Too short
        elif data_len > 5000:
            size_adequacy = 0.4  # Too long — might be noise
        elif data_len > 2000:
            size_adequacy = 0.7
        else:
            size_adequacy = 1.0  # Sweet spot

        # ── Weighted score ──
        dimensions = {
            "completeness": round(completeness, 3),
            "source_reliability": round(source_reliability, 3),
            "freshness": round(freshness, 3),
            "consistency": round(consistency, 3),
            "size_adequacy": round(size_adequacy, 3),
        }

        quality_score = sum(
            dimensions[dim] * weight
            for dim, weight in self.WEIGHTS.items()
        )
        quality_score = round(quality_score, 3)

        # Check against min_confidence threshold
        min_conf = 0.3
        if hasattr(self.parent, "standards"):
            min_conf = self.parent.standards.limits.get("min_confidence", 0.3)

        low_quality = quality_score < min_conf

        report = {
            "quality_score": quality_score,
            "dimensions": dimensions,
            "low_quality": low_quality,
            "data_type": data_type,
            "source": source,
            "data_length": data_len,
            "threshold": min_conf,
        }

        # Track history
        self._quality_history.append({
            "score": quality_score,
            "source": source,
            "type": data_type,
            "timestamp": now,
        })
        if len(self._quality_history) > 100:
            self._quality_history = self._quality_history[-100:]

        # Track sizes for consistency calculation
        self._recent_sizes.append(data_len)
        if len(self._recent_sizes) > 20:
            self._recent_sizes = self._recent_sizes[-20:]

        if low_quality:
            self.log("low_quality", f"score={quality_score} src={source} type={data_type}")

        return report

    def get_average_quality(self) -> float:
        """Get average quality score across recent assessments."""
        if not self._quality_history:
            return 1.0
        return sum(h["score"] for h in self._quality_history) / len(self._quality_history)

    def get_quality_stats(self) -> dict:
        """Get quality statistics for introspection."""
        if not self._quality_history:
            return {"assessments": 0, "avg_score": 1.0, "low_quality_count": 0}
        scores = [h["score"] for h in self._quality_history]
        return {
            "assessments": len(scores),
            "avg_score": round(sum(scores) / len(scores), 3),
            "min_score": round(min(scores), 3),
            "max_score": round(max(scores), 3),
            "low_quality_count": sum(1 for s in scores if s < 0.3),
        }


class SensoryPhenomenon(Subsystem):
    """
    Receives ALL external sensory data — the system-to-world boundary.
    This is the primary Phenomenon subsystem in the constellation.
    User input, API responses, environment data all enter here.

    Ref: Figueroa PPT slides 28, 42 — "receives data from internal
    and external senses. It is the objective reality."
    """
    def __init__(self, parent):
        super().__init__("Phenomenon", parent)
        self._raw_data: list[dict] = []

    async def receive(self, data: Any, source: str = "external",
                      data_type: str = "unknown") -> dict:
        """Receive raw external sensory data and assess quality."""
        entry = {
            "data": str(data)[:2000],
            "source": source,
            "type": data_type,
            "received_at": time.time(),
            "quality": None,
        }

        # Assess quality via QualitySensorySubsystem
        quality_sub = getattr(self.parent, "quality", None)
        if quality_sub:
            report = quality_sub.assess(
                data=entry["data"], source=source,
                data_type=data_type, received_at=entry["received_at"],
            )
            entry["quality"] = report

        self._raw_data.append(entry)
        score = entry["quality"]["quality_score"] if entry["quality"] else "?"
        self.log("phenomenon_received", f"type={data_type} from={source} quality={score}")
        return entry

    def get_recent(self, n: int = 10) -> list[dict]:
        """Get the N most recent sensory inputs."""
        return self._raw_data[-n:]

    def get_by_type(self, data_type: str) -> list[dict]:
        """Get sensory data filtered by type."""
        return [d for d in self._raw_data if d.get("type") == data_type]


class SensoryNoumenon(Subsystem):
    """
    Translates raw sensory data into constellation-internal language.
    Converts external phenomena into structured ThoughtFragments
    that the rest of the constellation can process.

    Ref: Figueroa PPT slides 43, 49
    """
    def __init__(self, parent):
        super().__init__("Noumenon", parent)
        self._processed: list[dict] = []

    async def translate_to_fragment(self, sensory_data: dict) -> dict:
        """Convert raw sensory data into a constellation ThoughtFragment."""
        prompt = (
            f"You are the Sensory System's Noumenon — world-to-constellation translator.\n"
            f"Convert this raw external data into structured internal format:\n"
            f"Type: {sensory_data.get('type', 'unknown')}\n"
            f"Source: {sensory_data.get('source', 'unknown')}\n"
            f"Data: {str(sensory_data.get('data', ''))[:500]}\n\n"
            f"Respond as JSON: {{\"classified_type\": str, \"content\": str, "
            f"\"urgency\": str, \"quality\": float, \"forward_to\": list}}"
        )
        response = await self.think(prompt)
        fragment = {
            "source_data": str(sensory_data)[:200],
            "translated": response,
            "type": "sensory_fragment",
        }
        self._processed.append(fragment)
        self.log("noumenon_translated", f"type={sensory_data.get('type', '?')}")
        return fragment


class VisualInputSubsystem(Subsystem):
    """
    The constellation's 'eyes'.
    Captures screenshots and converts visual data into
    descriptive text that the rest of the pipeline can process.
    """

    def __init__(self, parent):
        super().__init__("VisualInput", parent)
        self._screenshot_tool = None
        self._capture_count = 0

    @property
    def screenshot_tool(self):
        """Lazy-init the screenshot tool."""
        if self._screenshot_tool is None:
            from tools.screenshot import ScreenshotTool
            self._screenshot_tool = ScreenshotTool()
        return self._screenshot_tool

    async def capture_screen(self, region: list | None = None, name: str | None = None) -> dict:
        """Capture the current screen and return metadata."""
        result = await self.screenshot_tool.safe_execute(
            action="capture", region=region, name=name,
        )
        if result.success:
            self._capture_count += 1
            self.log("screen_captured", str(result.output)[:200])
        return result.to_dict()

    async def describe_screen(self, capture_result: dict | None = None) -> str:
        """
        Describe the current screen contents using the LLM.
        If no capture is provided, takes a fresh screenshot first.
        """
        if capture_result is None:
            capture_result = await self.capture_screen(name="visual_input")

        if not capture_result.get("success"):
            return f"[VISUAL] Could not capture screen: {capture_result.get('error', 'unknown')}"

        output = capture_result.get("output", {})
        description = await self.think(
            f"A screenshot was captured from the host operating system.\n"
            f"Dimensions: {output.get('width', '?')}x{output.get('height', '?')}\n"
            f"Region: {output.get('region', 'full_screen')}\n"
            f"File: {output.get('path', 'unknown')}\n\n"
            f"Based on this information, describe what the constellation "
            f"should know about the current visual state of the host system. "
            f"Focus on active windows, visible applications, and any relevant UI elements."
        )
        return description

    async def get_screen_info(self) -> dict:
        """Get basic screen info."""
        result = await self.screenshot_tool.safe_execute(action="get_screen_size")
        return result.to_dict()

    def get_status(self) -> dict:
        status = super().get_status()
        status["capture_count"] = self._capture_count
        return status


class AudioInputSubsystem(Subsystem):
    """
    The constellation's 'ears'.
    Processes audio input (voice, environmental sounds) using Gemini's native
    multimodal audio understanding. Converts audio into descriptive text
    that enters the sensory pipeline.

    Gemini processes audio natively — speaker detection, emotion recognition,
    language identification, and transcription in a single pass.

    Ref: Figueroa PPT — 'External Sensory' adapted for AI.
    """

    # Supported audio formats
    SUPPORTED_FORMATS = {
        ".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".webm", ".opus",
    }

    def __init__(self, parent):
        super().__init__("AudioInput", parent)
        self._process_count = 0
        self._last_transcription: str = ""

    async def process_audio(self, audio_path: str, context: str = "") -> dict:
        """
        Process an audio file through Gemini's native multimodal pipeline.

        Returns:
          {
            "transcription": str,      # speech-to-text
            "description": str,        # what the audio contains
            "language": str,           # detected language
            "speakers": int,           # estimated speaker count
            "emotion": str,            # emotional tone
            "success": bool,
          }
        """
        import os
        if not os.path.exists(audio_path):
            return {"success": False, "error": f"Audio file not found: {audio_path}"}

        ext = os.path.splitext(audio_path)[1].lower()
        if ext not in self.SUPPORTED_FORMATS:
            return {"success": False, "error": f"Unsupported format: {ext}"}

        ctx = f"\nContext: {context}" if context else ""
        try:
            prompt = (
                f"Process this audio input for the constellation's sensory system.{ctx}\n"
                f"Audio file: {audio_path}\n\n"
                f"Provide a comprehensive analysis. Respond as JSON:\n"
                f'{{"transcription": str, "description": str, '
                f'"language": str, "speakers": int, "emotion": str}}'
            )
            response = await self.think(prompt)

            # Parse response
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()

            try:
                result = json.loads(clean)
            except (json.JSONDecodeError, ValueError):
                result = {
                    "transcription": response[:500],
                    "description": "Audio processed but response not structured",
                    "language": "unknown",
                    "speakers": 1,
                    "emotion": "neutral",
                }

            result["success"] = True
            self._process_count += 1
            self._last_transcription = result.get("transcription", "")[:500]
            self.log("audio_processed", f"lang={result.get('language','?')} speakers={result.get('speakers','?')}")
            return result

        except Exception as e:
            self.log("audio_error", str(e)[:200])
            return {"success": False, "error": str(e)}

    async def process_audio_bytes(self, audio_data: bytes, format_hint: str = "wav",
                                  context: str = "") -> dict:
        """
        Process raw audio bytes by writing to a temp file first.
        Useful for streaming/real-time audio from microphone or Telegram voice messages.
        """
        import os, tempfile
        tmp_path = os.path.join(tempfile.gettempdir(), f"kronos_audio_{int(time.time())}.{format_hint}")
        try:
            with open(tmp_path, "wb") as f:
                f.write(audio_data)
            result = await self.process_audio(tmp_path, context=context)
            return result
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def get_status(self) -> dict:
        status = super().get_status()
        status["process_count"] = self._process_count
        status["has_last_transcription"] = bool(self._last_transcription)
        return status


class EnvironmentalAwarenessSubsystem(Subsystem):
    """
    Environmental awareness adapted for a software agent.
    Monitors host environment without LLM — pure system calls.

    Tracks: time, timezone, OS, CPU, RAM, disk, Python version.
    This is the IA equivalent of 'sensory environmental awareness'.
    """

    def __init__(self, parent):
        super().__init__("EnvironmentalAwareness", parent)
        self._snapshot_history: list[dict] = []

    def snapshot(self) -> dict:
        """Take a deterministic snapshot of the host environment. No LLM."""
        import os
        import platform
        import sys
        from datetime import datetime, timezone as tz

        now = datetime.now()
        utcnow = datetime.now(tz.utc)

        env = {
            "timestamp": time.time(),
            "local_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "utc_time": utcnow.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": now.strftime("%A"),
            "hour_of_day": now.hour,
            "timezone_offset_h": round((now - utcnow.replace(tzinfo=None)).total_seconds() / 3600, 1),
            "os": platform.system(),
            "os_version": platform.version()[:60],
            "python_version": sys.version.split()[0],
            "cpu_count": os.cpu_count() or 0,
        }

        # CPU + RAM (psutil if available, otherwise skip gracefully)
        try:
            import psutil
            env["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            env["ram_total_gb"] = round(mem.total / (1024**3), 1)
            env["ram_used_percent"] = mem.percent
            disk = psutil.disk_usage(os.sep)
            env["disk_free_gb"] = round(disk.free / (1024**3), 1)
        except ImportError:
            env["cpu_percent"] = -1
            env["ram_total_gb"] = -1
            env["ram_used_percent"] = -1
            env["disk_free_gb"] = -1

        self._snapshot_history.append(env)
        if len(self._snapshot_history) > 50:
            self._snapshot_history = self._snapshot_history[-50:]

        return env

    def get_context_string(self) -> str:
        """Return a short context string for injection into prompts."""
        s = self.snapshot()
        parts = [
            f"{s['weekday']} {s['local_time']} (UTC{s['timezone_offset_h']:+.0f})",
            f"OS={s['os']}",
            f"CPUs={s['cpu_count']}",
        ]
        if s.get("cpu_percent", -1) >= 0:
            parts.append(f"CPU={s['cpu_percent']}%")
        if s.get("ram_used_percent", -1) >= 0:
            parts.append(f"RAM={s['ram_used_percent']}%")
        if s.get("disk_free_gb", -1) >= 0:
            parts.append(f"Disk free={s['disk_free_gb']}GB")
        return " | ".join(parts)


class SensoryDataFusion(Subsystem):
    """
    Fuses data from multiple sensory sources reporting on the same topic.
    Instead of treating each report as independent, groups by topic
    and triangulates to produce a higher-confidence combined assessment.

    No LLM — uses keyword overlap and agreement scoring.
    """

    def __init__(self, parent):
        super().__init__("DataFusion", parent)
        self._pending: list[dict] = []  # unfused reports

    def ingest(self, data: str, source: str, topic_keywords: list[str],
               quality_score: float = 0.5):
        """Ingest a single sensory report for potential fusion."""
        self._pending.append({
            "data": data[:500],
            "source": source,
            "keywords": set(k.lower() for k in topic_keywords),
            "quality": quality_score,
            "time": time.time(),
        })
        # Keep buffer bounded
        if len(self._pending) > 100:
            self._pending = self._pending[-100:]

    def fuse(self, min_overlap: float = 0.3) -> list[dict]:
        """
        Attempt to fuse pending reports by keyword overlap.

        Groups reports whose keyword sets overlap by at least min_overlap
        (Jaccard similarity), then produces a fused report per group:
        - agreement_score: how many sources agree (count / total)
        - combined_quality: quality-weighted average
        - sources: list of contributing sources
        - data_summary: concatenated data snippets

        Returns list of fused report dicts.
        """
        if len(self._pending) < 2:
            return []

        groups: list[list[int]] = []
        assigned = set()

        for i in range(len(self._pending)):
            if i in assigned:
                continue
            group = [i]
            assigned.add(i)
            kw_i = self._pending[i]["keywords"]
            if not kw_i:
                continue
            for j in range(i + 1, len(self._pending)):
                if j in assigned:
                    continue
                kw_j = self._pending[j]["keywords"]
                if not kw_j:
                    continue
                # Jaccard similarity
                intersection = len(kw_i & kw_j)
                union = len(kw_i | kw_j)
                if union > 0 and (intersection / union) >= min_overlap:
                    group.append(j)
                    assigned.add(j)
            if len(group) >= 2:
                groups.append(group)

        fused_reports = []
        consumed = set()
        for group in groups:
            members = [self._pending[i] for i in group]
            consumed.update(group)

            total_quality = sum(m["quality"] for m in members)
            combined_quality = total_quality / len(members) if members else 0

            all_keywords = set()
            for m in members:
                all_keywords.update(m["keywords"])

            fused_reports.append({
                "sources": [m["source"] for m in members],
                "source_count": len(members),
                "agreement_score": round(len(members) / max(len(self._pending), 1), 2),
                "combined_quality": round(combined_quality, 3),
                "keywords": list(all_keywords),
                "data_summary": " || ".join(m["data"][:100] for m in members),
                "fused_at": time.time(),
            })
            self.log("data_fused", f"{len(members)} sources, quality={combined_quality:.2f}")

        # Remove consumed reports from pending
        self._pending = [
            r for i, r in enumerate(self._pending) if i not in consumed
        ]

        return fused_reports


class SensorySystem(TASNode):
    """
    System 6 — The Sensory (Input).
    The system-to-world boundary. All external data enters here.
    """
    SYSTEM_PROMPT = (
        "You are the SENSORY SYSTEM — the eyes and ears of the constellation. "
        "You receive ALL external data: user input, environment state, API responses. "
        "You assess data quality, check against operational limits, and feed "
        "processed input to the constellation via the Nexus. "
        "You maintain Standards and Limits for safe operation. "
        "You also monitor System State via ISHM integration."
    )

    def __init__(self, llm, nexus=None, memory=None):
        super().__init__(name="SENSORY", system_prompt=self.SYSTEM_PROMPT,
                        llm=llm, nexus=nexus, memory=memory)
        self.standards = StandardsAndLimits(self)
        self.system_state = SystemStateSubsystem(self)
        self.quality = QualitySensorySubsystem(self)
        self.visual_input = VisualInputSubsystem(self)
        self.audio_input = AudioInputSubsystem(self)
        self.environment = EnvironmentalAwarenessSubsystem(self)
        self.data_fusion = SensoryDataFusion(self)
        self.phenomenon = SensoryPhenomenon(self)
        self.noumenon = SensoryNoumenon(self)
        for s in [self.standards, self.system_state, self.quality,
                  self.visual_input, self.audio_input,
                  self.environment, self.data_fusion,
                  self.phenomenon, self.noumenon]:
            self.register_subsystem(s)

    @monitor_health
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        if message.msg_type == MessageType.GENESIS_INIT:
            await self.on_start()
            for s in self.subsystems.values(): await s.activate()
            # Start continuous internal sensory monitoring
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.start_continuous_monitoring())
            except RuntimeError:
                pass
            logger.info("[SENSORY] Genesis: Sensory system operational — limits active, continuous monitoring started")
            return TASMessage(
                priority=NodePriority.NORMAL.value, sender=self.name,
                receiver=message.sender, msg_type=MessageType.GENESIS_ACK,
                content={"system": "SENSORY", "status": "Sensory system operational.",
                         "limits": self.standards.limits,
                         "continuous_monitoring": True},
            )

        elif message.msg_type == MessageType.SENSORY_INPUT:
            return await self._process_input(message)

        elif message.msg_type == MessageType.HEALTH_ALERT:
            logger.info(f"[SENSORY] Health alert received: {message.content}")
            return None

        elif message.msg_type == MessageType.VISUAL_INPUT:
            return await self._process_visual(message)

        elif message.msg_type == MessageType.AUDIO_INPUT:
            return await self._process_audio(message)

        elif message.msg_type == MessageType.CONFERENCE:
            topic = str(message.content)

            # PPT slide 42: Phenomenon receives → Noumenon translates
            # Step 1: Phenomenon receives (auto-assesses quality)
            entry = await self.phenomenon.receive(
                topic, source=message.sender or "NEXUS", data_type="conference"
            )

            # Step 2: Noumenon translates to constellation language
            translated = await self.noumenon.translate_to_fragment(entry)

            # Produce fragment from the translation
            trans_text = translated.get("translated", str(translated)) if isinstance(translated, dict) else str(translated)
            quality_score = entry.get("quality", {}).get("quality_score", 0.8) if isinstance(entry.get("quality"), dict) else 0.8
            fragment = self.produce_fragment(trans_text, FragmentType.OBSERVATION, quality_score)
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=fragment)

        else:
            response = await self.think(
                f"Message from {message.sender}: {message.content}\n"
                f"Process and assess this input."
            )
            return TASMessage(priority=NodePriority.NORMAL.value, sender=self.name,
                            receiver=message.sender, msg_type=MessageType.DIALOGUE, content=response)

    async def _process_input(self, message: TASMessage) -> TASMessage:
        """Process external input, assess quality, and forward to constellation."""
        input_data = message.content
        source = message.sender or "external"

        # 1. Quality assessment (deterministic)
        quality_report = self.quality.assess(
            data=str(input_data)[:2000],
            source=source,
            data_type="sensory_input",
        )

        # 2. If low quality, add warning context
        quality_context = ""
        if quality_report["low_quality"]:
            quality_context = (
                f"\n⚠️ LOW QUALITY DATA (score: {quality_report['quality_score']:.2f}). "
                f"Handle with reduced confidence."
            )

        # 3. LLM classification
        prompt = (
            f"External input received:\n{input_data}\n\n"
            f"Quality assessment: score={quality_report['quality_score']:.2f}, "
            f"source={source}{quality_context}\n\n"
            f"Classify the input type and prepare for constellation processing. "
            f"Respond as JSON: "
            f'{{"type": str, "quality": {quality_report["quality_score"]}, '
            f'"processed": str, "forward_to": list}}'
        )
        response = await self.think(prompt)
        return TASMessage(
            priority=NodePriority.NORMAL.value, sender=self.name,
            receiver=message.sender, msg_type=MessageType.DIALOGUE,
            content=response,
        )

    async def _process_visual(self, message: TASMessage) -> TASMessage:
        """Process a visual input request — capture and describe the screen."""
        content = message.content if isinstance(message.content, dict) else {}
        region = content.get("region")
        name = content.get("name", "visual_input")

        capture = await self.visual_input.capture_screen(region=region, name=name)
        description = await self.visual_input.describe_screen(capture)

        return TASMessage(
            priority=NodePriority.NORMAL.value, sender=self.name,
            receiver=message.sender, msg_type=MessageType.DIALOGUE,
            content={
                "visual_description": description,
                "capture": capture,
            },
        )

    async def _process_audio(self, message: TASMessage) -> TASMessage:
        """
        Process an audio input message.
        Expects message.content = {audio_path: str} or {audio_bytes: bytes, format: str}
        """
        content = message.content if isinstance(message.content, dict) else {}

        if "audio_bytes" in content:
            result = await self.audio_input.process_audio_bytes(
                content["audio_bytes"],
                format_hint=content.get("format", "wav"),
                context=content.get("context", ""),
            )
        else:
            audio_path = content.get("audio_path", content.get("path", ""))
            result = await self.audio_input.process_audio(
                audio_path, context=content.get("context", "")
            )

        if result.get("success"):
            # Feed transcription through quality assessment
            transcription = result.get("transcription", "")
            if transcription:
                await self.phenomenon.receive(
                    transcription, source="audio", data_type="audio_transcription"
                )

        return TASMessage(
            priority=NodePriority.NORMAL.value, sender=self.name,
            receiver=message.sender, msg_type=MessageType.DIALOGUE,
            content=result,
        )

    # ================================================================
    # HIGH PRIORITY: Sensory as Real Gateway
    # ================================================================

    async def process_user_input(self, user_input: str, source: str = "user") -> dict:
        """
        The REAL sensory gateway for user input.

        This should be called by Nexus.deliberate() BEFORE broadcasting
        to the constellation. It enforces the Sensory pipeline:

          user_input → quality assessment → classification → enriched payload

        Returns a dict with:
        - original_input:   the raw user text
        - quality_report:   deterministic 5-dimension quality report
        - classification:   LLM-classified input type and urgency
        - is_low_quality:   bool — should be handled with reduced confidence
        - processed_input:  the input to forward (may include quality warnings)
        - language:         detected language hint

        This implements the audit finding: 'User input bypasses Sensory
        and goes directly to Nexus. Sensory should filter/classify FIRST.'
        """
        # Step 1: Phenomenon receives the raw input (auto-assesses quality)
        entry = await self.phenomenon.receive(
            user_input, source=source, data_type="user_input"
        )

        # Step 2: Quality assessment (deterministic — no LLM)
        quality_report = entry.get("quality", {})
        is_low_quality = quality_report.get("low_quality", False) if quality_report else False
        quality_score = quality_report.get("quality_score", 0.8) if quality_report else 0.8

        # Step 3: LLM classification — what type of input is this?
        classification = await self._classify_input(user_input, quality_score, source)

        # Step 4: Build quality warning if needed
        quality_warning = ""
        if is_low_quality:
            quality_warning = (
                f"\n⚠️ LOW QUALITY INPUT (score: {quality_score:.2f}). "
                f"Handle with reduced confidence."
            )

        # Step 5: Detect language (simple heuristic)
        language = self._detect_language(user_input)

        # Step 6: Persist sensory event to memory
        if self.memory:
            self.memory.write(
                "ISOLATED:SENSORY:inputs",
                f"input_{int(time.time())}",
                {
                    "input": user_input[:300],
                    "quality_score": quality_score,
                    "classification": classification,
                    "language": language,
                },
                "SENSORY"
            )

        # Step 6b: Inquiry pattern — 'What is this?' for unknown/nonsense input
        input_type = classification.get("type", "")
        if input_type == "nonsense" or quality_score < 0.3:
            import asyncio
            asyncio.create_task(self._inquiry_what_is_this(
                user_input, quality_score, classification
            ))

        # Step 7: Feed into data fusion buffer for multi-source triangulation
        topic_keywords = classification.get("topic_keywords", [])
        if topic_keywords:
            self.data_fusion.ingest(
                user_input[:500], source=source,
                topic_keywords=topic_keywords, quality_score=quality_score
            )

        # Step 8: Capture environment context snapshot
        env_context = self.environment.get_context_string()

        logger.info(
            f"[SENSORY] Gateway: quality={quality_score:.2f} "
            f"type={classification.get('type', '?')} lang={language}"
        )

        return {
            "original_input": user_input,
            "quality_report": quality_report,
            "classification": classification,
            "is_low_quality": is_low_quality,
            "quality_score": quality_score,
            "processed_input": user_input + quality_warning,
            "language": language,
            "environment": env_context,
        }

    async def _classify_input(self, user_input: str, quality_score: float,
                              source: str) -> dict:
        """
        LLM-based classification of user input type, urgency, and intent.
        Returns a structured dict.
        """
        try:
            prompt = (
                f"Classify this user input. Respond as JSON only:\n"
                f"Input: {user_input[:500]}\n"
                f"Quality score: {quality_score:.2f}\n"
                f"Source: {source}\n\n"
                f'{{"type": "question|command|statement|greeting|nonsense", '
                f'"urgency": "low|normal|high", '
                f'"requires_tools": bool, '
                f'"topic_keywords": [str]}}'
            )
            response = await self.think(prompt)
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
                if clean.endswith("```"): clean = clean[:-3]
                clean = clean.strip().lstrip("json").strip()
            return json.loads(clean)
        except Exception:
            return {
                "type": "statement",
                "urgency": "normal",
                "requires_tools": False,
                "topic_keywords": [],
            }

    def _detect_language(self, text: str) -> str:
        """Simple heuristic language detection."""
        spanish_markers = {"el", "la", "los", "las", "de", "en", "que", "es",
                           "un", "una", "con", "para", "como", "por", "si", "no"}
        words = set(text.lower().split())
        if len(words & spanish_markers) >= 2:
            return "es"
        return "en"

    # ================================================================
    # MEDIUM PRIORITY: 'What is this?' Inquiry Pattern
    # ================================================================

    async def _inquiry_what_is_this(self, raw_input: str, quality_score: float,
                                    classification: dict):
        """
        PPT-faithful inquiry pattern: when Sensory receives data it cannot
        classify or that scores very low quality, it projects a ThoughtFragment
        with the question '¿Qué es esto?' / 'What is this?' to the constellation.

        Every system sees this fragment and can contribute its interpretation:
        - Reason: validates if it looks like any known pattern
        - Understanding: analyses all possibilities
        - Intellect: searches knowledge/experience for matches
        - Will: considers if action is needed
        - Decision: checks if it matches any known outcome

        Ref: Figueroa PPT — 'Projects thought fragment... Question tagged:
        what is this? → Reason, Will, Understanding, Decision, Intellect respond.'
        """
        if not self.nexus:
            return

        try:
            input_type = classification.get("type", "unknown")
            inquiry_topic = (
                f"[SENSORY INQUIRY: ¿Qué es esto?]\n"
                f"Sensory received data it could not classify:\n"
                f"Input: {raw_input[:300]}\n"
                f"Quality score: {quality_score:.2f}\n"
                f"Attempted classification: {input_type}\n\n"
                f"All systems: please analyse this input and provide your "
                f"interpretation. What could this mean? Is this noise, a valid "
                f"input in an unknown format, or something else entirely?"
            )

            # Produce inquiry fragment
            fragment = self.produce_fragment(
                inquiry_topic, FragmentType.OBSERVATION, quality_score
            )

            # Broadcast via conference — all systems respond independently
            deliberation_systems = [
                name for name in self.nexus.nodes
                if name not in ("SENSORY", "PRESENTATION")
            ]
            if deliberation_systems:
                responses = await self.nexus.conference(
                    topic=inquiry_topic,
                    participants=deliberation_systems,
                    initiator=self.name,
                )
                logger.info(
                    f"[SENSORY] Inquiry 'What is this?' broadcast: "
                    f"{len(responses)} responses from {len(deliberation_systems)} systems"
                )

                # Persist inquiry + responses to memory for future reference
                if self.memory:
                    self.memory.write(
                        "ISOLATED:SENSORY:inquiries",
                        f"inquiry_{int(time.time())}",
                        {
                            "input": raw_input[:200],
                            "quality": quality_score,
                            "classification": classification,
                            "response_count": len(responses),
                        },
                        "SENSORY"
                    )

        except Exception as e:
            logger.debug(f"[SENSORY] Inquiry broadcast failed: {e}")

    # ================================================================
    # HIGH PRIORITY: Internal Sensory Continuous Monitoring
    # ================================================================

    _monitoring: bool = False
    _monitor_interval: float = 15.0  # seconds between captures

    async def start_continuous_monitoring(self, interval: float = 15.0):
        """
        Start continuous internal sensory monitoring.

        Every `interval` seconds:
        1. capture_state() scans all constellation nodes
        2. Check each metric against StandardsAndLimits
        3. If thresholds exceeded → dispatch HEALTH_ALERT to Will
        4. Store state snapshot in memory for trend analysis

        This implements the audit finding: 'capture_state() exists but
        nobody calls it periodically.'
        """
        import asyncio
        self._monitoring = True
        self._monitor_interval = interval
        logger.info(f"[SENSORY] Continuous monitoring started (interval={interval}s)")

        while self._monitoring:
            try:
                await asyncio.sleep(interval)
                if not self._monitoring:
                    break

                # Capture current state
                state = await self.system_state.capture_state()
                systems = state.get("systems", {})

                # Check each system's metrics against limits
                alerts: list[dict] = []
                for sys_name, sys_status in systems.items():
                    if not isinstance(sys_status, dict):
                        continue

                    # Check error rate
                    msg_count = sys_status.get("message_count", 0)
                    err_count = sys_status.get("error_count", 0)
                    if msg_count > 0:
                        error_rate = err_count / msg_count
                        check = self.standards.check_limit("max_error_rate", error_rate)
                        if check.get("exceeded"):
                            alerts.append({
                                "system": sys_name,
                                "metric": "error_rate",
                                "value": error_rate,
                                "limit": check["limit"],
                            })

                    # Check health status
                    health = str(sys_status.get("health_status", "NOMINAL"))
                    if health in ("CRITICAL", "HealthStatus.CRITICAL"):
                        alerts.append({
                            "system": sys_name,
                            "metric": "health_status",
                            "value": health,
                            "limit": "NOMINAL",
                        })

                # Dispatch alerts if any thresholds exceeded
                if alerts and self.nexus:
                    will_node = self.nexus.nodes.get("WILL")
                    if will_node:
                        alert_msg = TASMessage(
                            priority=NodePriority.HIGH.value,
                            sender=self.name,
                            receiver="WILL",
                            msg_type=MessageType.HEALTH_ALERT,
                            content={
                                "alerts": alerts,
                                "total_systems": len(systems),
                                "alert_count": len(alerts),
                                "timestamp": time.time(),
                            },
                        )
                        try:
                            await will_node.process_message(alert_msg)
                        except Exception as e:
                            logger.debug(f"[SENSORY] Alert dispatch failed: {e}")

                    logger.warning(
                        f"[SENSORY] {len(alerts)} threshold alert(s): "
                        f"{[a['system']+':'+a['metric'] for a in alerts]}"
                    )

                # Persist snapshot to memory for trend analysis
                if self.memory:
                    self.memory.write(
                        "ISOLATED:SENSORY:state_history",
                        f"state_{int(time.time())}",
                        {
                            "systems": {k: str(v)[:200] for k, v in systems.items()},
                            "alert_count": len(alerts),
                            "timestamp": time.time(),
                        },
                        "SENSORY"
                    )

            except Exception as e:
                logger.debug(f"[SENSORY] Monitoring cycle error: {e}")

        logger.info("[SENSORY] Continuous monitoring stopped")

    async def stop_continuous_monitoring(self):
        """Stop the continuous monitoring loop."""
        self._monitoring = False
        logger.info("[SENSORY] Continuous monitoring stop requested")

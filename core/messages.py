"""
INTI - TAS (AI Agent Version) — Messages, Fragments, and Enums
===========================================
All data structures for inter-system communication.

TASMessage:       Unit of communication between constellation systems.
ThoughtFragment:  Standardized LLM output schema (from any system's Noumenon).
MemoryWrite:      Directive to persist data to a memory tier.

Ref: Figueroa PPT slides 21, 43-44, 67
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ============================================================
# Enums
# ============================================================

class MessageType(str, Enum):
    """Communication types in the constellation."""
    # Core 4 modes
    MONOLOGUE = "monologue"
    DIALOGUE = "dialogue"
    BROADCAST = "broadcast"
    CONFERENCE = "conference"

    # Task-specific types
    VALIDATE_ACTION = "validate_action"
    AUTHORIZE_REPAIR = "authorize_repair"
    HEALTH_ALERT = "health_alert"
    STORE_KNOWLEDGE = "store_knowledge"
    QUERY_KNOWLEDGE = "query_knowledge"
    ANALYZE_OPTIONS = "analyze_options"
    RENDER_OUTPUT = "render_output"
    USER_INPUT = "user_input"
    GENESIS_INIT = "genesis_init"
    GENESIS_ACK = "genesis_ack"
    CONTEMPLATION = "contemplation"
    SENSORY_BURST = "sensory_burst"
    SENSORY_INPUT = "sensory_input"
    DECIDE = "decide"
    VETO = "veto"

    # Tool system
    TOOL_INVOKE = "tool_invoke"
    TOOL_RESULT = "tool_result"

    # OS I/O
    VISUAL_INPUT = "visual_input"
    AUDIO_INPUT = "audio_input"            # AudioInputSubsystem: voice/audio processing

    # Ideas → Concepts pipeline
    IDEA_PROPOSED = "idea_proposed"

    # Rules evolution
    RULE_PROPOSAL = "rule_proposal"

    # Presentation system
    PREVIEW_ACTION = "preview_action"      # ViewingSubsystem: consequence preview before execution
    SHOW_PROJECTION = "show_projection"    # ProjectionSubsystem: show courses of action to user

    # Understanding system
    QUERY_UNDERSTANDING = "query_understanding"  # Query SHARED:UNDERSTANDING:insights store


class FragmentType(str, Enum):
    """Types of thought fragments produced by system Noumenon subsystems."""
    OBSERVATION = "observation"
    EVALUATION = "evaluation"
    RECOMMENDATION = "recommendation"
    VETO = "veto"
    VERDICT = "verdict"


class HealthStatus(str, Enum):
    """Health states of a constellation system."""
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    OFFLINE = "OFFLINE"
    REPAIRING = "REPAIRING"
    INITIALIZING = "INITIALIZING"


class NodePriority(int, Enum):
    """Message priority levels for the Nexus queue."""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class MemoryTier(str, Enum):
    """Memory tier types in the 4-tier architecture."""
    ISOLATED = "isolated"       # Single-system private
    SHARED = "shared"           # Defined system pairs/groups
    GLOBAL = "global"           # All systems r/w (consciousness buffer)
    TRANSIENT = "transient"     # Cleared after deliberation cycle


# ============================================================
# TASMessage — Inter-System Communication Unit
# ============================================================

@dataclass(order=True)
class TASMessage:
    """
    Unit of communication between constellation systems.
    Ordered by priority for the Nexus PriorityQueue.
    """
    priority: int = field(compare=True)
    sender: str = field(compare=False)
    receiver: str = field(compare=False)
    msg_type: MessageType = field(compare=False)
    content: Any = field(compare=False)
    timestamp: float = field(
        default_factory=time.time,
        compare=False,
    )
    message_id: str = field(
        default_factory=lambda: str(uuid.uuid4())[:8],
        compare=False,
    )
    conversation_id: str = field(default="", compare=False)
    metadata: dict = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "priority": self.priority,
            "sender": self.sender,
            "receiver": self.receiver,
            "msg_type": self.msg_type.value if isinstance(self.msg_type, Enum) else self.msg_type,
            "content": str(self.content)[:500],
            "timestamp": self.timestamp,
            "conversation_id": self.conversation_id,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ============================================================
# ThoughtFragment — Standardized LLM Output Schema
# ============================================================

@dataclass
class ThoughtFragment:
    """
    A thought fragment produced by a system's Noumenon subsystem.
    These are incomplete until the Nexus Cogitationis assembles them
    into a complete, coherent thought.

    Ref: Figueroa PPT slides 43-44
    """
    source_system: str
    fragment_type: FragmentType
    content: str                    # In human language
    confidence: float = 0.8        # 0.0–1.0
    memory_writes: list[dict] = field(default_factory=list)
    comm_mode: str = "dialogue"    # monologue|dialogue|broadcast|conference
    target_systems: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    fragment_id: str = field(
        default_factory=lambda: str(uuid.uuid4())[:8],
    )

    def to_dict(self) -> dict:
        return {
            "fragment_id": self.fragment_id,
            "source_system": self.source_system,
            "fragment_type": self.fragment_type.value,
            "content": self.content,
            "confidence": self.confidence,
            "comm_mode": self.comm_mode,
            "target_systems": self.target_systems,
            "timestamp": self.timestamp,
        }


# ============================================================
# MemoryWrite — Directive to Persist Data
# ============================================================

@dataclass
class MemoryWrite:
    """A directive from a system to persist data to a memory tier."""
    tier: MemoryTier
    owner: str              # System that owns this memory
    key: str                # Storage key
    value: Any              # Data to store
    access_list: list[str] = field(default_factory=list)  # Who can read (for SHARED tier)
    ttl: Optional[float] = None  # Time-to-live in seconds (None = permanent)
    timestamp: float = field(default_factory=time.time)

"""
INTI - TAS (AI Agent Version) — Base Classes
========================
Abstract base classes for all constellation systems and subsystems.

TASNode:    Base for all 8 cognitive systems.
Subsystem:  Lightweight base for subsystems within a system.
@monitor_health:  ISHM decorator for fault detection.

Ref: Figueroa PPT slides 16-20
"""

from __future__ import annotations

import asyncio
import functools
import logging
import traceback
import time
from abc import ABC, abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from core.messages import (
    TASMessage, ThoughtFragment, MessageType,
    NodePriority, HealthStatus, FragmentType,
)

if TYPE_CHECKING:
    from core.nexus import NexusCogitationis
    from mcp.adapter import MCPLLMClient
    from core.memory import MemoryManager

logger = logging.getLogger("taas")


# ============================================================
# Subsystem — Lightweight base for system components
# ============================================================

class Subsystem:
    """
    Base class for subsystems within a cognitive system.
    Subsystems are lightweight — they share their parent's LLM and Nexus.
    """

    def __init__(self, name: str, parent: "TASNode"):
        self.name = name
        self.parent = parent
        self.is_active = False
        self._log: list[dict] = []

    @property
    def llm(self):
        return self.parent.llm

    @property
    def nexus(self):
        return self.parent.nexus

    @property
    def memory(self):
        return self.parent.memory

    async def activate(self):
        """Activate this subsystem during genesis."""
        self.is_active = True
        self._log.append({"event": "activated", "time": time.time()})

    async def think(self, prompt: str) -> str:
        """Invoke the parent system's LLM."""
        return await self.parent.think(prompt)

    def log(self, event: str, details: str = ""):
        """Log a subsystem event."""
        self._log.append({
            "event": event,
            "details": details,
            "time": time.time(),
        })

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "active": self.is_active,
            "log_count": len(self._log),
        }


# ============================================================
# TASNode — Abstract Base for Cognitive Systems
# ============================================================

class TASNode(ABC):
    """
    Abstract base class for all 8 cognitive systems in the constellation.
    Each system has its own LLM client, memory partition, and Nexus connection.
    """

    def __init__(
        self,
        name: str,
        system_prompt: str,
        llm: "MCPLLMClient",
        nexus: Optional["NexusCogitationis"] = None,
        memory: Optional["MemoryManager"] = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.llm = llm
        self.nexus = nexus
        self.memory = memory

        # Health state
        self.health = HealthStatus.INITIALIZING
        self.error_count = 0
        self.last_error: str = ""
        self.message_count = 0
        self.start_time: float = 0.0

        # Subsystems registry
        self.subsystems: dict[str, Subsystem] = {}

    def set_nexus(self, nexus: "NexusCogitationis"):
        """Connect this system to the Nexus bus."""
        self.nexus = nexus

    def set_memory(self, memory: "MemoryManager"):
        """Connect this system to the memory manager."""
        self.memory = memory

    def register_subsystem(self, subsystem: Subsystem):
        """Register a subsystem."""
        self.subsystems[subsystem.name] = subsystem

    async def send(
        self,
        receiver: str,
        content: Any,
        msg_type: MessageType = MessageType.DIALOGUE,
        priority: NodePriority = NodePriority.NORMAL,
        metadata: dict | None = None,
    ):
        """Send a message to another system through the Nexus."""
        if self.nexus is None:
            logger.warning(f"[{self.name}] Cannot send — no Nexus connected")
            return
        msg = TASMessage(
            priority=priority.value,
            sender=self.name,
            receiver=receiver,
            msg_type=msg_type,
            content=content,
            metadata=metadata or {},
        )
        await self.nexus.enqueue(msg)

    async def think(self, prompt: str) -> str:
        """Invoke this system's own LLM."""
        if self.llm is None:
            return f"[{self.name}] No LLM configured"
        return await self.llm.generate(prompt, system_prompt=self.system_prompt)

    def produce_fragment(
        self,
        content: str,
        fragment_type: FragmentType = FragmentType.OBSERVATION,
        confidence: float = 0.8,
        targets: list[str] | None = None,
    ) -> ThoughtFragment:
        """Produce a thought fragment for the Nexus to assemble."""
        return ThoughtFragment(
            source_system=self.name,
            fragment_type=fragment_type,
            content=content,
            confidence=confidence,
            target_systems=targets or [],
        )

    @abstractmethod
    async def process_message(self, message: TASMessage) -> Optional[TASMessage]:
        """Process an incoming message. Must be implemented by each system."""
        ...

    async def on_start(self):
        """Hook called when the system is initialized during genesis."""
        self.start_time = time.time()
        self.health = HealthStatus.NOMINAL

    async def on_shutdown(self):
        """Hook called when the system is shutting down."""
        self.health = HealthStatus.OFFLINE

    def get_status(self) -> dict:
        """Return the current status of this system."""
        subsystem_status = {
            name: sub.get_status()
            for name, sub in self.subsystems.items()
        }
        return {
            "name": self.name,
            "health": self.health.value,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "subsystems": subsystem_status,
            "uptime": time.time() - self.start_time if self.start_time else 0,
        }


# ============================================================
# @monitor_health — ISHM Decorator
# ============================================================

def monitor_health(func):
    """
    ISHM decorator for process_message methods.
    On exception:
      1. Marks the system as DEGRADED
      2. Logs the error
      3. Sends a HEALTH_ALERT to the Sensory System via Nexus
    """

    @functools.wraps(func)
    async def wrapper(self: TASNode, message: TASMessage, *args, **kwargs):
        try:
            self.message_count += 1
            result = await func(self, message, *args, **kwargs)
            return result
        except Exception as e:
            self.error_count += 1
            self.last_error = str(e)
            self.health = HealthStatus.DEGRADED

            error_info = {
                "node": self.name,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "message_type": message.msg_type.value if hasattr(message.msg_type, "value") else str(message.msg_type),
                "sender": message.sender,
                "timestamp": time.time(),
            }

            logger.error(f"[ISHM] {self.name} DEGRADED: {e}")

            # Send health alert to Sensory System
            if self.nexus:
                try:
                    alert = TASMessage(
                        priority=NodePriority.CRITICAL.value,
                        sender="ISHM",
                        receiver="SENSORY",
                        msg_type=MessageType.HEALTH_ALERT,
                        content=error_info,
                    )
                    await self.nexus.enqueue(alert)
                except Exception:
                    pass  # Don't let ISHM alerting crash the system

            return None

    return wrapper

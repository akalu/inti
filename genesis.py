"""
INTI - TAS (AI Agent Version) — Genesis Protocol
==============================
9-Moment self-awareness boot sequence for the cognitive constellation.

Moment 1: Life assertion      — WILL's Survival Subsystem verifies existence
Moment 2: Laws incarnation    — REASON loads and accepts Laws
Moment 3: System instantiation— All 8 systems receive GENESIS_INIT
Moment 4: ISHM activation     — Health monitoring online
Moment 5: Memory layout       — 4-tier memory architecture initialized
Moment 6: Nexus bonding       — All systems registered with the Nexus bus
Moment 7: Rules & mission     — WILL loads initial rules and mission
Moment 8: Language validation  — THOUGHT Communication subsystem validates language
Moment 9: Self-awareness test — Full constellation CONFERENCE on self-awareness

Ref: Figueroa PPT slides 72-81
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from config.settings import load_system_llm_config
from config.axioms import LAWS, INITIAL_RULES, AXIOMS, MISSION_PRIORITIES
from core.messages import (
    TASMessage, MessageType, NodePriority, HealthStatus,
)
from core.nexus import NexusCogitationis
from core.memory import MemoryManager, create_default_memory_layout
from mcp.adapter import create_llm_client

# Systems
from systems.will import WillSystem
from systems.reason import ReasonSystem
from systems.intellect import IntellectSystem
from systems.understanding import UnderstandingSystem
from systems.presentation import PresentationSystem
from systems.sensory import SensorySystem
from systems.decision import DecisionSystem
from systems.thought import ThoughtSystem  # Hub — creates Nexus internally

# ISHM
from ishm.engine import ISHMEngine

logger = logging.getLogger("taas")


class GenesisProtocol:
    """
    The 9-Moment Genesis Protocol.
    Instantiates and boots the entire cognitive constellation.
    """

    def __init__(self):
        # ThoughtSystem IS the hub — it creates the Nexus internally
        # (Figueroa PPT Slide 20: "the Nexus (Thought System)")
        self.thought_system: Optional[ThoughtSystem] = None
        self.nexus = None  # set once ThoughtSystem is created

        # Persistence — memory survives restarts
        from core.persistence import MemoryPersistence
        self.persistence = MemoryPersistence()

        # Vector memory — ChromaDB + Gemini Embedding 2
        # Falls back to dict storage if GEMINI_API_KEY is not set
        vector_manager = None
        try:
            import os
            api_key = os.getenv("GEMINI_API_KEY", "")
            if api_key:
                from core.vector_store import VectorMemoryManager
                vector_manager = VectorMemoryManager(
                    persist_directory="data/chromadb",
                    api_key=api_key,
                    embedding_dims=768,
                )
                logger.info("[GENESIS] VectorMemoryManager initialized (ChromaDB + Gemini Embedding 2)")
            else:
                logger.warning(
                    "[GENESIS] GEMINI_API_KEY not set — vector stores will use dict fallback"
                )
        except Exception as e:
            logger.warning(f"[GENESIS] VectorMemoryManager init failed: {e} — using dict fallback")

        self.memory = create_default_memory_layout(
            persistence=self.persistence,
            vector_manager=vector_manager,
        )
        self.ishm = None  # set after ThoughtSystem creates the Nexus
        self.systems: dict[str, object] = {}
        self.genesis_log: list[dict] = []
        self.start_time: float = 0

    def _log_moment(self, moment: int, name: str, status: str, details: str = ""):
        entry = {
            "moment": moment,
            "name": name,
            "status": status,
            "details": details,
            "elapsed": round(time.time() - self.start_time, 3),
        }
        self.genesis_log.append(entry)
        logger.info(f"[GENESIS] Moment {moment}: {name} — {status}")

    async def execute(self, on_moment=None) -> dict:
        """
        Execute the full 9-moment genesis.
        on_moment: optional async callback(moment_num, name, status) for UI
        """
        self.start_time = time.time()

        async def _cb(moment: int, name: str, status: str):
            if on_moment:
                await on_moment(moment, name, status)

        # ---- Moment 1: Life Assertion ----
        await _cb(1, "Life Assertion", "Initiating...")
        self._log_moment(1, "Life Assertion", "Will asserts existence")

        # Create all LLM clients (8 systems including THOUGHT)
        system_names = [
            "WILL", "REASON", "INTELLECT", "UNDERSTANDING",
            "PRESENTATION", "SENSORY", "DECISION", "THOUGHT",
        ]
        llm_clients = {}
        for name in system_names:
            config = load_system_llm_config(name)
            llm_clients[name] = create_llm_client(name, config)

        # Create ThoughtSystem FIRST — it IS the hub and creates the Nexus
        thought = ThoughtSystem(llm_clients["THOUGHT"])
        self.thought_system = thought
        self.nexus = thought.nexus  # Nexus lives inside ThoughtSystem
        self.ishm = ISHMEngine(nexus=self.nexus, memory=self.memory)

        # Instantiate the 7 cognitive peer systems (THOUGHT is NOT a peer)
        will = WillSystem(llm_clients["WILL"])
        reason = ReasonSystem(llm_clients["REASON"])
        intellect = IntellectSystem(llm_clients["INTELLECT"])
        understanding = UnderstandingSystem(llm_clients["UNDERSTANDING"])
        presentation = PresentationSystem(llm_clients["PRESENTATION"])
        sensory = SensorySystem(llm_clients["SENSORY"])
        decision = DecisionSystem(llm_clients["DECISION"])

        # 7 peer systems (not 8 — ThoughtSystem is the hub, not a peer)
        all_systems = [will, reason, intellect, understanding,
                       presentation, sensory, decision]

        self.systems = {s.name: s for s in all_systems}
        self.systems["THOUGHT"] = thought  # included for reference
        self._log_moment(1, "Life Assertion", "COMPLETE",
                        f"{len(all_systems)} peer systems + ThoughtSystem hub")
        await _cb(1, "Life Assertion", "✓ 7 systems + hub instantiated")

        # ---- Moment 2: Laws Incarnation ----
        await _cb(2, "Laws Incarnation", "Loading Laws, Rules, Axioms...")
        self.memory.write("ISOLATED:REASON:laws", "laws", [l.__dict__ for l in LAWS], "REASON")
        self.memory.write("SHARED:REASON:rules", "rules", [r.__dict__ for r in INITIAL_RULES], "REASON")
        self.memory.write("ISOLATED:WILL:axioms", "axioms", [a.__dict__ for a in AXIOMS], "WILL")
        self._log_moment(2, "Laws Incarnation", "COMPLETE",
                        f"Laws={len(LAWS)}, Rules={len(INITIAL_RULES)}, Axioms={len(AXIOMS)}")
        await _cb(2, "Laws Incarnation", f"✓ {len(LAWS)} Laws, {len(INITIAL_RULES)} Rules, {len(AXIOMS)} Axioms")

        # ---- Moment 3: System Instantiation ----
        await _cb(3, "System Instantiation", "Sending GENESIS_INIT to all systems...")
        genesis_msg = TASMessage(
            priority=NodePriority.CRITICAL.value,
            sender="GENESIS",
            receiver="ALL",
            msg_type=MessageType.GENESIS_INIT,
            content={"protocol": "genesis", "moment": 3},
        )
        init_results = {}
        # Send GENESIS_INIT to ThoughtSystem hub first
        try:
            result = await thought.process_message(genesis_msg)
            if result:
                init_results["THOUGHT"] = result.content
        except Exception as e:
            init_results["THOUGHT"] = {"error": str(e)}
            logger.error(f"[GENESIS] Failed to init THOUGHT hub: {e}")

        # Then init the 7 peer systems
        for sys in all_systems:
            try:
                result = await sys.process_message(genesis_msg)
                if result:
                    init_results[sys.name] = result.content
            except Exception as e:
                init_results[sys.name] = {"error": str(e)}
                logger.error(f"[GENESIS] Failed to init {sys.name}: {e}")

        self._log_moment(3, "System Instantiation", "COMPLETE",
                        f"Initialized: {list(init_results.keys())}")
        await _cb(3, "System Instantiation", f"✓ {len(init_results)}/8 systems initialized")

        # ---- Moment 4: ISHM Activation ----
        await _cb(4, "ISHM Activation", "Starting health monitoring...")
        self.ishm.set_nexus(self.nexus)
        self.ishm.set_memory(self.memory)
        # Connect ISHM to tool registry for autonomous web research
        from tools.registry import ToolRegistry
        tool_registry = ToolRegistry()
        tool_registry.register_defaults()
        self.ishm.set_tool_registry(tool_registry)
        # Rehydrate persisted state (learned models, directive history, recovery records)
        ishm_restored = self.ishm.rehydrate()
        self._log_moment(4, "ISHM Activation", "COMPLETE",
                        f"3-tier ISHM online + web research enabled (restored {ishm_restored} entries)")
        await _cb(4, "ISHM Activation", f"✓ 3-tier health monitoring + web research online ({ishm_restored} entries restored)")

        # ---- Moment 5: Memory Layout ----
        await _cb(5, "Memory Layout", "Initializing 4-tier memory...")
        stores = self.memory.list_stores()
        self._log_moment(5, "Memory Layout", "COMPLETE",
                        f"{len(stores)} memory partitions active")
        await _cb(5, "Memory Layout", f"✓ {len(stores)} memory partitions")

        # ---- Moment 6: Nexus Bonding ----
        await _cb(6, "Nexus Bonding", "Registering systems with the ThoughtSystem/Nexus...")
        for sys in all_systems:
            sys.set_nexus(self.nexus)
            sys.set_memory(self.memory)
            thought.register_system(sys)  # register into ThoughtSystem's Nexus

        # Build the routing table now that all systems are registered
        thought.network.build_routing_table()

        self._log_moment(6, "Nexus Bonding", "COMPLETE",
                        f"{len(self.nexus.nodes)} nodes registered in ThoughtSystem hub")
        await _cb(6, "Nexus Bonding", f"✓ {len(self.nexus.nodes)} nodes bonded to hub")

        # ---- Moment 7: Rules & Mission ----
        await _cb(7, "Rules & Mission", "Loading mission objectives...")
        self.memory.write("SHARED:WILL:mission", "objectives",
                         [m.__dict__ for m in MISSION_PRIORITIES], "WILL")
        self._log_moment(7, "Rules & Mission", "COMPLETE",
                        f"{len(MISSION_PRIORITIES)} objectives loaded")
        await _cb(7, "Rules & Mission", f"✓ {len(MISSION_PRIORITIES)} mission objectives")

        # ---- Moment 8: Language Validation ----
        await _cb(8, "Language Validation", "Validating language framework...")
        lang_result = await thought.communication.validate_language()
        self._log_moment(8, "Language Validation", "COMPLETE",
                        f"Language: {lang_result.get('language', 'English')}")
        await _cb(8, "Language Validation", "✓ Language framework validated")

        # ---- Moment 9: Self-Awareness Test ----
        await _cb(9, "Self-Awareness Test", "Running constellation CONFERENCE...")
        fragments = await self.nexus.conference(
            topic=(
                "We are the TAAS constellation. "
                "Each system should acknowledge its identity, role, and status. "
                "Confirm self-awareness and readiness."
            ),
            initiator="GENESIS",
        )
        self._log_moment(9, "Self-Awareness Test", "COMPLETE",
                        f"{len(fragments)} systems responded to self-awareness conference")
        await _cb(9, "Self-Awareness Test", f"✓ {len(fragments)} systems self-aware")

        # ---- Genesis Complete ----
        elapsed = round(time.time() - self.start_time, 2)
        self._log_moment(0, "Genesis Complete", "OPERATIONAL",
                        f"Total time: {elapsed}s")

        # ---- Rehydrate System States ----
        # Memory was loaded from SQLite during Moment 5.
        # Now apply saved system state (evolved Rules, Contemplation, Affect, Overrides)
        from core.persistence import ConstellationStateSaver
        rehydrated = ConstellationStateSaver.rehydrate_system_states(
            self.systems, self.memory
        )
        if rehydrated:
            logger.info(f"[GENESIS] Rehydrated state: {list(rehydrated.keys())}")

        return {
            "status": "OPERATIONAL",
            "elapsed_seconds": elapsed,
            "systems": list(self.systems.keys()),
            "memory_stores": len(stores),
            "genesis_log": self.genesis_log,
            "self_awareness_fragments": len(fragments),
            "rehydrated_state": rehydrated,
        }

    def get_constellation(self) -> dict:
        """Return references to all constellation components."""
        return {
            "thought_system": self.thought_system,
            "nexus": self.nexus,
            "memory": self.memory,
            "ishm": self.ishm,
            "systems": self.systems,
            "persistence": self.persistence,
        }

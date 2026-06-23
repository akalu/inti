"""
INTI - TAS (AI Agent Version) — Hybrid Memory Architecture
=======================================
Implements the constellation's 3-layer hybrid memory system.

Layer 1 — Working Memory:   dict in RAM (TRANSIENT stores, cleared each cycle)
Layer 2 — Semantic Memory:  ChromaDB + Gemini Embedding 2 (knowledge, experience,
                            abstract, ideas, concepts, consciousness)
Layer 3 — Structured Memory: dict + SQLite (axioms, laws, rules, missions,
                             affect, health — small, key-based)

Tiers:
  ISOLATED   — Single-system private (Will axioms, Reason laws)
  SHARED     — Defined system-pairs (Knowledge→all, Mission→Will↔Decision)
  GLOBAL     — All systems r/w (consciousness buffer in Nexus)
  TRANSIENT  — Cleared after each deliberation cycle (Noumena, scratchpads)

Ref: Figueroa architecture — memory types per system
Ref: Phase 27 — Hybrid Memory System
"""

from __future__ import annotations

import logging
import time
import threading
from typing import Any, Optional, TYPE_CHECKING
from dataclasses import dataclass, field

from core.messages import MemoryTier, MemoryWrite

if TYPE_CHECKING:
    from core.vector_store import VectorMemoryStore, VectorMemoryManager

logger = logging.getLogger("taas")


# ============================================================
# Individual Memory Store
# ============================================================

class MemoryStore:
    """A single memory partition with access control."""

    def __init__(self, tier: MemoryTier, owner: str, access_list: list[str] | None = None):
        self.tier = tier
        self.owner = owner
        self.access_list = access_list or []  # Empty = owner-only (ISOLATED)
        self._data: dict[str, Any] = {}
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()

    def _check_access(self, requester: str, write: bool = False) -> bool:
        """Enforce access control rules."""
        if self.tier == MemoryTier.ISOLATED:
            return requester == self.owner
        elif self.tier == MemoryTier.SHARED:
            if write:
                return requester == self.owner
            return requester == self.owner or requester in self.access_list
        elif self.tier == MemoryTier.GLOBAL:
            return True  # All systems can read/write
        elif self.tier == MemoryTier.TRANSIENT:
            return requester == self.owner
        return False

    def write(self, key: str, value: Any, requester: str) -> bool:
        """Write data to memory. Returns True if successful."""
        if not self._check_access(requester, write=True):
            return False
        with self._lock:
            self._data[key] = value
            self._timestamps[key] = time.time()
        return True

    def read(self, key: str, requester: str) -> tuple[bool, Any]:
        """Read data from memory. Returns (success, value)."""
        if not self._check_access(requester, write=False):
            return False, None
        with self._lock:
            if key in self._data:
                return True, self._data[key]
        return False, None

    def read_all(self, requester: str) -> tuple[bool, dict[str, Any]]:
        """Read all data from memory. Returns (success, data_dict)."""
        if not self._check_access(requester, write=False):
            return False, {}
        with self._lock:
            return True, dict(self._data)

    def delete(self, key: str, requester: str) -> bool:
        """Delete a key. Returns True if successful."""
        if not self._check_access(requester, write=True):
            return False
        with self._lock:
            self._data.pop(key, None)
            self._timestamps.pop(key, None)
        return True

    def clear(self, requester: str) -> bool:
        """Clear all data. Returns True if successful."""
        if not self._check_access(requester, write=True):
            return False
        with self._lock:
            self._data.clear()
            self._timestamps.clear()
        return True

    def size(self) -> int:
        return len(self._data)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._data.keys())


# ============================================================
# Memory Manager — Central Memory Controller
# ============================================================

class MemoryManager:
    """
    Manages all memory partitions in the constellation.
    Enforces the 4-tier access control model.
    Supports hybrid storage: dict-based stores + vector-backed stores.
    Optionally backed by SQLite persistence for survival across restarts.
    """

    def __init__(self, persistence=None, vector_manager: Optional["VectorMemoryManager"] = None):
        self._stores: dict[str, Any] = {}  # MemoryStore | VectorMemoryStore
        self._vector_stores: set[str] = set()  # Track which stores are vector-backed
        self._vector_manager = vector_manager
        self._global_store = MemoryStore(
            tier=MemoryTier.GLOBAL,
            owner="NEXUS",
            access_list=["*"],
        )
        self._stores["GLOBAL:consciousness_buffer"] = self._global_store
        self._persistence = persistence  # Optional MemoryPersistence

    def register_memory(
        self,
        name: str,
        tier: MemoryTier,
        owner: str,
        access_list: list[str] | None = None,
    ) -> MemoryStore:
        """Register a new dict-based memory partition."""
        store = MemoryStore(tier=tier, owner=owner, access_list=access_list)
        self._stores[name] = store
        return store

    def register_vector_memory(
        self,
        name: str,
        tier: MemoryTier,
        owner: str,
        access_list: list[str] | None = None,
    ) -> "VectorMemoryStore":
        """
        Register a vector-backed memory partition (ChromaDB + embeddings).
        Falls back to a regular dict store if no vector_manager is available.
        """
        if self._vector_manager is None:
            logger.warning(
                f"[MEMORY] No VectorMemoryManager — {name} will use dict storage"
            )
            return self.register_memory(name, tier, owner, access_list)

        # Create a clean collection name from the store name
        collection_name = name.replace(":", "_").lower()
        store = self._vector_manager.create_store(
            collection_name=collection_name,
            tier=tier,
            owner=owner,
            access_list=access_list,
        )
        self._stores[name] = store
        self._vector_stores.add(name)
        logger.info(f"[MEMORY] Registered vector store: {name} → {collection_name}")
        return store

    def get_store(self, name: str) -> Optional[MemoryStore]:
        """Get a memory store by name."""
        return self._stores.get(name)

    def write(self, store_name: str, key: str, value: Any, requester: str) -> bool:
        """Write to a named memory store (auto-persists if persistence attached)."""
        store = self._stores.get(store_name)
        if store is None:
            return False
        ok = store.write(key, value, requester)
        # Vector stores handle their own persistence via ChromaDB
        if ok and self._persistence and store.tier != MemoryTier.TRANSIENT:
            if store_name not in self._vector_stores:
                self._persistence.save_entry(
                    store_name, key, value,
                    store.tier.value, store.owner, store.access_list,
                )
        return ok

    def query_semantic(
        self,
        store_name: str,
        query: str,
        requester: str,
        top_k: int = 5,
        min_score: float = 0.0,
        media_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic search across a vector-backed memory store.
        Returns list of dicts with: key, value, score, document, media_type, timestamp.

        Args:
            media_filter: optional, filter by media type ('text', 'image', 'audio', 'video', 'pdf')

        Falls back to keyword search if the store is dict-based.
        """
        store = self._stores.get(store_name)
        if store is None:
            return []

        # If it's a vector store, use semantic search
        if store_name in self._vector_stores:
            # Pass media_filter as MediaType enum if provided
            mf = None
            if media_filter:
                from core.vector_store import MediaType
                try:
                    mf = MediaType(media_filter)
                except ValueError:
                    pass
            return store.query_semantic(query, requester, top_k, min_score, media_filter=mf)

        # Fallback: keyword search for dict-based stores
        if isinstance(store, MemoryStore):
            ok, data = store.read_all(requester)
            if not ok or not data:
                return []
            results = []
            query_lower = query.lower()
            for key, value in data.items():
                text = f"{key} {str(value)}".lower()
                if query_lower in text:
                    results.append({
                        "key": key,
                        "value": value,
                        "score": 0.5,  # Keyword match = medium confidence
                        "document": text[:200],
                        "media_type": "text",
                        "timestamp": 0,
                    })
            return results[:top_k]

        return []

    # --- Multimodal Memory Operations ---

    def write_media(
        self,
        store_name: str,
        key: str,
        file_path: str,
        requester: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> bool:
        """
        Store a media file (image, audio, video, PDF) in a vector-backed store.
        
        The file's embedding is computed and stored for cross-modal search.
        The file itself is NOT copied — only a reference (path) is kept.
        
        Works with any vector-backed store (ISOLATED, SHARED, GLOBAL).
        Returns False if the store is dict-based (media requires vectors).
        """
        store = self._stores.get(store_name)
        if store is None:
            return False

        if store_name not in self._vector_stores:
            logger.warning(
                f"[MEMORY] write_media requires vector store, "
                f"but {store_name} is dict-based"
            )
            return False

        return store.write_media(key, file_path, requester, description, tags)

    def query_by_image(
        self,
        store_name: str,
        image_path: str,
        requester: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Search a memory store using an image as the query.
        Finds semantically similar content across ALL modalities in that store.
        """
        store = self._stores.get(store_name)
        if store is None or store_name not in self._vector_stores:
            return []
        return store.query_by_image(image_path, requester, top_k, min_score)

    def query_by_audio(
        self,
        store_name: str,
        audio_path: str,
        requester: str,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Search a memory store using audio as the query.
        Finds semantically similar content across ALL modalities in that store.
        """
        store = self._stores.get(store_name)
        if store is None or store_name not in self._vector_stores:
            return []
        return store.query_by_audio(audio_path, requester, top_k, min_score)

    def read(self, store_name: str, key: str, requester: str) -> tuple[bool, Any]:
        """Read from a named memory store."""
        store = self._stores.get(store_name)
        if store is None:
            return False, None
        return store.read(key, requester)

    # --- Global Consciousness Buffer shortcuts ---

    def write_global(self, key: str, value: Any, requester: str) -> bool:
        """Write to the global consciousness buffer."""
        ok = self._global_store.write(key, value, requester)
        if ok and self._persistence:
            self._persistence.save_entry(
                "GLOBAL:consciousness_buffer", key, value,
                self._global_store.tier.value, "NEXUS", ["*"],
            )
        return ok

    def read_global(self, key: str, requester: str) -> tuple[bool, Any]:
        """Read from the global consciousness buffer."""
        return self._global_store.read(key, requester)

    def get_consciousness_snapshot(self, requester: str) -> dict[str, Any]:
        """Get a snapshot of the global consciousness buffer."""
        ok, data = self._global_store.read_all(requester)
        return data if ok else {}

    # --- Transient Memory Management ---

    def clear_transient(self, owner: str) -> int:
        """Clear all transient memory for a system. Returns count cleared."""
        count = 0
        for name, store in self._stores.items():
            if store.tier == MemoryTier.TRANSIENT and store.owner == owner:
                store.clear(owner)
                count += 1
        return count

    def clear_all_transient(self) -> int:
        """Clear ALL transient memory stores (end of deliberation cycle)."""
        count = 0
        for name, store in self._stores.items():
            if store.tier == MemoryTier.TRANSIENT:
                store.clear(store.owner)
                count += 1
        return count

    # --- Introspection ---

    def list_stores(self) -> dict[str, dict]:
        """List all memory stores with metadata."""
        result = {}
        for name, store in self._stores.items():
            result[name] = {
                "tier": store.tier.value,
                "owner": store.owner,
                "access_list": store.access_list,
                "size": store.size,
            }
        return result

    def process_memory_write(self, mw: MemoryWrite) -> bool:
        """Process a MemoryWrite directive from a system."""
        if mw.tier == MemoryTier.GLOBAL:
            return self.write_global(mw.key, mw.value, mw.owner)

        store_name = f"{mw.tier.value}:{mw.owner}:{mw.key}"
        store = self._stores.get(store_name)
        if store is None:
            store = self.register_memory(
                name=store_name,
                tier=mw.tier,
                owner=mw.owner,
                access_list=mw.access_list,
            )
        return store.write(mw.key, mw.value, mw.owner)

    # --- Export / Import (for Digital Twin migration) ---

    def export_state(self, requester: str) -> dict[str, dict]:
        """
        Export all non-ISOLATED memory stores for twin migration.
        Returns a serializable dict of {store_name: {key: value, ...}}.
        """
        export = {}
        for name, store in self._stores.items():
            if store.tier == MemoryTier.ISOLATED:
                continue  # Private data stays private
            ok, data = store.read_all(requester)
            if ok and data:
                export[name] = {
                    "tier": store.tier.value,
                    "owner": store.owner,
                    "access_list": store.access_list,
                    "data": data,
                }
        return export

    def import_state(self, state: dict[str, dict], requester: str) -> int:
        """
        Import memory state from a twin.
        Returns the number of stores updated.
        """
        count = 0
        for name, meta in state.items():
            store = self._stores.get(name)
            if store is None:
                store = self.register_memory(
                    name=name,
                    tier=MemoryTier(meta["tier"]),
                    owner=meta["owner"],
                    access_list=meta.get("access_list", []),
                )
            data = meta.get("data", {})
            for key, value in data.items():
                store.write(key, value, requester)
            count += 1
        return count


def create_default_memory_layout(
    persistence=None,
    vector_manager: Optional["VectorMemoryManager"] = None,
) -> MemoryManager:
    """
    Create the default 3-layer hybrid memory layout for the constellation.
    Called during genesis to initialize all memory partitions.

    Layer 1 (Working):    TRANSIENT stores → dict in RAM
    Layer 2 (Semantic):   6 stores → VectorMemoryStore (ChromaDB + Gemini Embedding 2)
    Layer 3 (Structured): 6 stores → MemoryStore (dict + SQLite)
    """
    mm = MemoryManager(persistence=persistence, vector_manager=vector_manager)

    # ================================================================
    # Layer 3: Structured Memory (dict + SQLite) — small, key-based
    # ================================================================

    # Isolated: Will axioms and survival rules
    mm.register_memory("ISOLATED:WILL:axioms", MemoryTier.ISOLATED, "WILL")
    mm.register_memory("ISOLATED:WILL:survival", MemoryTier.ISOLATED, "WILL")

    # Isolated: Reason laws (read-only by design)
    mm.register_memory("ISOLATED:REASON:laws", MemoryTier.ISOLATED, "REASON")

    # Shared: Mission memory → Will ↔ Decision
    mm.register_memory(
        "SHARED:WILL:mission", MemoryTier.SHARED, "WILL",
        access_list=["DECISION", "SENSORY"],
    )

    # Shared: Reason rules ↔ Intellect
    mm.register_memory(
        "SHARED:REASON:rules", MemoryTier.SHARED, "REASON",
        access_list=["INTELLECT"],
    )

    # Shared: ISHM health state → all read
    mm.register_memory(
        "SHARED:ISHM:health", MemoryTier.SHARED, "ISHM",
        access_list=["WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                     "DECISION", "PRESENTATION", "SENSORY", "THOUGHT"],
    )

    # Shared: Thought Affect → all read (emotional signals, small, overwritten)
    mm.register_memory(
        "SHARED:THOUGHT:affect", MemoryTier.SHARED, "THOUGHT",
        access_list=["WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                     "DECISION", "PRESENTATION", "SENSORY"],
    )

    # ================================================================
    # Layer 2: Semantic Memory (ChromaDB + Gemini Embedding 2)
    # These stores grow unbounded and benefit from semantic search.
    # Falls back to dict if no vector_manager is provided.
    # ================================================================

    # Intellect: abstract data, experience, and knowledge
    mm.register_vector_memory(
        "ISOLATED:INTELLECT:abstract", MemoryTier.ISOLATED, "INTELLECT",
    )
    mm.register_vector_memory(
        "ISOLATED:INTELLECT:experience", MemoryTier.ISOLATED, "INTELLECT",
    )
    mm.register_vector_memory(
        "SHARED:INTELLECT:knowledge", MemoryTier.SHARED, "INTELLECT",
        access_list=["WILL", "REASON", "UNDERSTANDING", "DECISION",
                     "PRESENTATION", "SENSORY", "THOUGHT"],
    )

    # Thought: Ideas and Concepts from contemplation
    mm.register_vector_memory(
        "SHARED:THOUGHT:ideas", MemoryTier.SHARED, "THOUGHT",
        access_list=["WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                     "DECISION", "PRESENTATION", "SENSORY"],
    )
    mm.register_vector_memory(
        "SHARED:THOUGHT:concepts", MemoryTier.SHARED, "THOUGHT",
        access_list=["WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                     "DECISION", "PRESENTATION", "SENSORY"],
    )

    # Global: Consciousness buffer → semantic search across all history
    mm.register_vector_memory(
        "GLOBAL:consciousness_buffer", MemoryTier.GLOBAL, "NEXUS",
        access_list=["*"],
    )

    # ================================================================
    # Layer 1: Working Memory (dict in RAM) — cleared each cycle
    # ================================================================

    # Transient: Noumenon stores (one per system)
    for system in ["WILL", "REASON", "INTELLECT", "UNDERSTANDING",
                   "PRESENTATION", "SENSORY", "DECISION", "THOUGHT"]:
        mm.register_memory(
            f"TRANSIENT:{system}:noumena", MemoryTier.TRANSIENT, system,
        )

    # Transient: Decision processing scratchpad
    mm.register_memory("TRANSIENT:DECISION:scratchpad", MemoryTier.TRANSIENT, "DECISION")

    # Transient: Understanding synthesis scratchpad
    mm.register_memory("TRANSIENT:UNDERSTANDING:scratchpad", MemoryTier.TRANSIENT, "UNDERSTANDING")

    # Restore persisted state for dict-based stores (if any)
    if persistence:
        try:
            restored = persistence.load_all(mm)
            if restored > 0:
                logger.info(
                    f"[MEMORY] Restored {restored} dict entries from previous session"
                )
        except Exception as e:
            logger.warning(f"[MEMORY] Restore failed: {e}")

    vector_count = len(mm._vector_stores)
    dict_count = len(mm._stores) - vector_count
    logger.info(
        f"[MEMORY] Hybrid layout ready: {vector_count} vector stores + "
        f"{dict_count} dict stores"
    )

    return mm

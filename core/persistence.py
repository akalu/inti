"""
INTI - TAS (AI Agent Version) — Memory Persistence Layer
======================================
SQLite-backed persistence for the 4-tier memory system.
Saves memory state to disk so it survives constellation restarts.

Usage:
  persistence = MemoryPersistence()            # uses data/memory.db
  persistence.save_store("GLOBAL:buf", store)  # save one store
  persistence.save_all(manager)                # save all stores
  persistence.load_all(manager)                # restore all stores
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory import MemoryManager, MemoryStore

logger = logging.getLogger("taas.memory")

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "memory.db"


class MemoryPersistence:
    """SQLite-backed persistence for constellation memory."""

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                store_name TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                tier TEXT NOT NULL,
                owner TEXT NOT NULL,
                access_list TEXT DEFAULT '[]',
                updated_at REAL NOT NULL,
                PRIMARY KEY (store_name, key)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        self._conn.commit()
        logger.info(f"[MEMORY] Persistence initialized: {self._db_path}")

    def _serialize(self, value: Any) -> str:
        """Serialize a value to JSON string."""
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps(str(value))

    def _deserialize(self, raw: str) -> Any:
        """Deserialize a JSON string back to a value."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    # ─── Save Operations ───

    def save_entry(self, store_name: str, key: str, value: Any,
                   tier: str, owner: str, access_list: list[str] | None = None):
        """Save a single memory entry to disk."""
        self._conn.execute(
            """INSERT OR REPLACE INTO memory_entries
               (store_name, key, value, tier, owner, access_list, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                store_name, key, self._serialize(value),
                tier, owner,
                json.dumps(access_list or []),
                time.time(),
            ),
        )
        self._conn.commit()

    def save_store(self, store_name: str, store: "MemoryStore"):
        """Save all entries from a single MemoryStore."""
        # Read all data (bypass access control for persistence)
        data = dict(store._data)
        for key, value in data.items():
            self.save_entry(
                store_name, key, value,
                store.tier.value, store.owner, store.access_list,
            )

    def save_all(self, manager: "MemoryManager") -> int:
        """Save all memory stores to disk. Returns count saved."""
        count = 0
        for name, store in manager._stores.items():
            # Skip TRANSIENT stores — they're meant to be ephemeral
            from core.messages import MemoryTier
            if store.tier == MemoryTier.TRANSIENT:
                continue
            self.save_store(name, store)
            count += 1
        self._set_meta("last_save", time.strftime("%Y-%m-%d %H:%M:%S"))
        self._set_meta("stores_saved", str(count))
        logger.info(f"[MEMORY] Saved {count} stores to {self._db_path}")
        return count

    # ─── Load Operations ───

    def load_all(self, manager: "MemoryManager") -> int:
        """
        Restore all persisted memory into a MemoryManager.
        Returns count of entries restored.
        """
        from core.messages import MemoryTier

        cursor = self._conn.execute(
            "SELECT DISTINCT store_name, tier, owner, access_list FROM memory_entries"
        )
        store_meta = cursor.fetchall()

        count = 0
        for store_name, tier_str, owner, access_list_str in store_meta:
            tier = MemoryTier(tier_str)

            # Skip transient (shouldn't be stored, but guard anyway)
            if tier == MemoryTier.TRANSIENT:
                continue

            # Ensure store exists in manager
            store = manager.get_store(store_name)
            if store is None:
                access_list = json.loads(access_list_str) if access_list_str else []
                store = manager.register_memory(
                    name=store_name, tier=tier,
                    owner=owner, access_list=access_list,
                )

            # Load entries
            entries = self._conn.execute(
                "SELECT key, value FROM memory_entries WHERE store_name = ?",
                (store_name,),
            ).fetchall()

            for key, raw_value in entries:
                value = self._deserialize(raw_value)
                store._data[key] = value  # Direct write (bypass access control)
                store._timestamps[key] = time.time()
                count += 1

        self._set_meta("last_load", time.strftime("%Y-%m-%d %H:%M:%S"))
        logger.info(f"[MEMORY] Restored {count} entries from {self._db_path}")
        return count

    # ─── Metadata ───

    def _set_meta(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_meta (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, time.time()),
        )
        self._conn.commit()

    def _get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM memory_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def get_status(self) -> dict:
        """Get persistence status."""
        entry_count = self._conn.execute(
            "SELECT COUNT(*) FROM memory_entries"
        ).fetchone()[0]
        store_count = self._conn.execute(
            "SELECT COUNT(DISTINCT store_name) FROM memory_entries"
        ).fetchone()[0]
        return {
            "db_path": str(self._db_path),
            "db_exists": self._db_path.exists(),
            "total_entries": entry_count,
            "total_stores": store_count,
            "last_save": self._get_meta("last_save") or "never",
            "last_load": self._get_meta("last_load") or "never",
        }

    # ─── Cleanup ───

    def clear_all(self):
        """Remove all persisted memory (for testing)."""
        self._conn.execute("DELETE FROM memory_entries")
        self._conn.execute("DELETE FROM memory_meta")
        self._conn.commit()

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


class ConstellationStateSaver:
    """
    Orchestrates saving and restoring system-specific state across restarts.
    Uses memory stores as the transport vehicle — MemoryPersistence handles
    the actual SQLite I/O.

    Each system writes its evolving state (Rules evolution, Contemplation
    cycles, Affect signals, Override history, Quality stats) to its SHARED
    memory store. This class coordinates the save/rehydrate calls.

    Usage:
      saver = ConstellationStateSaver()
      saver.save_system_states(systems, memory)    # before persistence.save_all()
      saver.rehydrate_system_states(systems, memory)  # after persistence.load_all()
    """

    @staticmethod
    def save_system_states(systems: dict, memory) -> dict:
        """
        Save all system-specific evolving state to memory stores.
        Call this BEFORE persistence.save_all().

        Returns summary of what was saved.
        """
        saved = {}

        # 1. REASON — Rules (evolved) + evolution history
        reason = systems.get("REASON")
        if reason and hasattr(reason, "rules_sub"):
            try:
                rules_data = []
                for rule in reason.rules_sub.rules:
                    rules_data.append({
                        "id": rule.id,
                        "text": rule.text,
                        "category": rule.category.value,
                        "source": rule.source,
                        "confidence": rule.confidence,
                        "version": rule.version,
                    })
                if memory:
                    memory.write(
                        "SHARED:REASON:rules", "__rules_snapshot__",
                        rules_data, "REASON",
                    )
                    memory.write(
                        "SHARED:REASON:rules", "__evolution_history__",
                        reason.rules_sub.get_evolution_history(), "REASON",
                    )
                saved["REASON"] = f"{len(rules_data)} rules, {len(reason.rules_sub.get_evolution_history())} evolutions"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to save REASON state: {e}")

        # 2. THOUGHT — Contemplation + Affect
        thought = systems.get("THOUGHT")
        if thought:
            try:
                # Contemplation state
                if hasattr(thought, "contemplation"):
                    state = thought.contemplation.serialize_state()
                    if memory:
                        memory.write(
                            "SHARED:THOUGHT:concepts", "__contemplation_state__",
                            state, "THOUGHT",
                        )
                    saved["THOUGHT_contemplation"] = (
                        f"{state.get('cycle_count', 0)} cycles, "
                        f"{state.get('ideas_generated', 0)} ideas"
                    )

                # Affect state
                if hasattr(thought, "affect"):
                    affect_data = {
                        "last_signals": thought.affect._last_signals,
                        "interaction_count": thought.affect._interaction_count,
                        "error_count": thought.affect._error_count,
                    }
                    if memory:
                        memory.write(
                            "SHARED:THOUGHT:affect", "__affect_state__",
                            affect_data, "THOUGHT",
                        )
                    saved["THOUGHT_affect"] = f"signals: {thought.affect._last_signals}"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to save THOUGHT state: {e}")

        # 3. WILL — Override history
        will = systems.get("WILL")
        if will and hasattr(will, "dominance"):
            try:
                history = will.dominance.get_override_history()
                if memory and history:
                    memory.write(
                        "SHARED:WILL:missions", "__override_history__",
                        history, "WILL",
                    )
                saved["WILL"] = f"{len(history)} overrides"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to save WILL state: {e}")

        # 4. SENSORY — Quality stats
        sensory = systems.get("SENSORY")
        if sensory and hasattr(sensory, "quality"):
            try:
                stats = sensory.quality.get_quality_stats()
                if memory:
                    memory.write(
                        "SHARED:SENSORY:data", "__quality_stats__",
                        stats, "SENSORY",
                    )
                saved["SENSORY"] = f"{stats.get('assessments', 0)} assessments"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to save SENSORY state: {e}")

        # 5. INTELLECT — knowledge count
        intellect = systems.get("INTELLECT")
        if intellect and hasattr(intellect, "knowledge"):
            try:
                k_count = len(getattr(intellect.knowledge, "_knowledge", []))
                e_count = len(getattr(intellect.experience, "_experiences", []))
                if memory:
                    memory.write(
                        "SHARED:INTELLECT:knowledge", "__tier_counts__",
                        {"knowledge": k_count, "experience": e_count},
                        "INTELLECT",
                    )
                saved["INTELLECT"] = f"{k_count} knowledge, {e_count} experiences"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to save INTELLECT state: {e}")

        logger.info(f"[PERSIST] System states saved: {list(saved.keys())}")
        return saved

    @staticmethod
    def rehydrate_system_states(systems: dict, memory) -> dict:
        """
        Restore system-specific state from memory stores.
        Call this AFTER persistence.load_all().

        Returns summary of what was restored.
        """
        restored = {}

        # 1. REASON — Restore evolved Rules
        reason = systems.get("REASON")
        if reason and hasattr(reason, "rules_sub") and memory:
            try:
                ok, rules_data = memory.read(
                    "SHARED:REASON:rules", "__rules_snapshot__", "REASON"
                )
                if ok and rules_data and isinstance(rules_data, list):
                    from config.axioms import Rule, RuleCategory
                    reason.rules_sub.rules.clear()
                    for rd in rules_data:
                        rule = Rule(
                            id=rd["id"],
                            text=rd["text"],
                            category=RuleCategory(rd["category"]),
                            source=rd.get("source", "hardwired"),
                            confidence=rd.get("confidence", 1.0),
                            version=rd.get("version", 1),
                        )
                        reason.rules_sub.rules.append(rule)
                    restored["REASON_rules"] = f"{len(reason.rules_sub.rules)} rules"

                ok, history = memory.read(
                    "SHARED:REASON:rules", "__evolution_history__", "REASON"
                )
                if ok and history and isinstance(history, list):
                    reason.rules_sub._evolution_history = history
                    restored["REASON_evolutions"] = f"{len(history)} evolutions"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to rehydrate REASON: {e}")

        # 2. THOUGHT — Restore Contemplation + Affect
        thought = systems.get("THOUGHT")
        if thought and memory:
            try:
                # Contemplation
                if hasattr(thought, "contemplation"):
                    ok, state = memory.read(
                        "SHARED:THOUGHT:concepts", "__contemplation_state__", "THOUGHT"
                    )
                    if ok and state and isinstance(state, dict):
                        thought.contemplation.rehydrate_state(state)
                        restored["THOUGHT_contemplation"] = (
                            f"{state.get('cycle_count', 0)} cycles"
                        )

                # Affect
                if hasattr(thought, "affect"):
                    ok, affect_data = memory.read(
                        "SHARED:THOUGHT:affect", "__affect_state__", "THOUGHT"
                    )
                    if ok and affect_data and isinstance(affect_data, dict):
                        thought.affect._last_signals = affect_data.get(
                            "last_signals", thought.affect._last_signals
                        )
                        thought.affect._interaction_count = affect_data.get(
                            "interaction_count", 0
                        )
                        thought.affect._error_count = affect_data.get(
                            "error_count", 0
                        )
                        restored["THOUGHT_affect"] = "signals restored"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to rehydrate THOUGHT: {e}")

        # 3. WILL — Restore override history
        will = systems.get("WILL")
        if will and hasattr(will, "dominance") and memory:
            try:
                ok, history = memory.read(
                    "SHARED:WILL:missions", "__override_history__", "WILL"
                )
                if ok and history and isinstance(history, list):
                    will.dominance._override_history = history
                    restored["WILL"] = f"{len(history)} overrides"
            except Exception as e:
                logger.warning(f"[PERSIST] Failed to rehydrate WILL: {e}")

        # 4. SENSORY — Quality stats (informational only, no rehydrate needed)
        #    Quality stats reset each session — the history builds fresh.

        logger.info(f"[PERSIST] System states restored: {list(restored.keys())}")
        return restored

"""
INTI - TAS (AI Agent Version) — Settings & MCP Registry
====================================
Loads per-system LLM configuration from .env file.
Provides the MCP registry mapping system_id → provider config.

Multi-env support:
  .env             — Core LLM providers & embeddings
  .env.tools       — Agent-created tool API keys
  .env.community   — Downloaded/GitHub tool API keys
  .env.services    — External services (GitHub, VirusTotal, MCP)
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load all .env files (later files do NOT override earlier ones)
_env_files = [
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / ".env.tools",
    PROJECT_ROOT / ".env.community",
    PROJECT_ROOT / ".env.services",
]
for _ef in _env_files:
    if _ef.exists():
        load_dotenv(_ef, override=False)


@dataclass
class LLMConfig:
    """LLM configuration for a single constellation system."""
    provider: str
    model: str
    api_key: str
    url: str  # For Ollama or custom endpoints


# System names in the constellation
SYSTEM_NAMES: tuple[str, ...] = (
    "THOUGHT", "WILL", "REASON", "INTELLECT",
    "UNDERSTANDING", "PRESENTATION", "SENSORY", "DECISION",
)


def load_system_llm_config(system_name: str) -> LLMConfig:
    """
    Load LLM config for a specific system from environment.
    Falls back to DEFAULT_LLM_* if no system-specific config exists.
    """
    prefix = system_name.upper()
    return LLMConfig(
        provider=os.getenv(
            f"{prefix}_LLM_PROVIDER",
            os.getenv("DEFAULT_LLM_PROVIDER", "simulation"),
        ),
        model=os.getenv(
            f"{prefix}_LLM_MODEL",
            os.getenv("DEFAULT_LLM_MODEL", "sim-1"),
        ),
        api_key=os.getenv(
            f"{prefix}_LLM_API_KEY",
            os.getenv("DEFAULT_LLM_API_KEY", ""),
        ),
        url=os.getenv(f"{prefix}_LLM_URL", ""),
    )


def load_all_configs() -> dict[str, LLMConfig]:
    """Load LLM configs for all constellation systems."""
    return {name: load_system_llm_config(name) for name in SYSTEM_NAMES}


# ================================================================
# Multi-Env Helpers
# ================================================================

def load_tool_env(key: str, default: str = "") -> str:
    """Load a key intended for agent-created tools (.env.tools)."""
    return os.getenv(key, default)


def load_community_env(key: str, default: str = "") -> str:
    """Load a key intended for community tools (.env.community)."""
    return os.getenv(key, default)


def load_service_env(key: str, default: str = "") -> str:
    """Load a key for external services (.env.services)."""
    return os.getenv(key, default)


# ================================================================
# Project Paths
# ================================================================

LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
TOOLS_DIR = PROJECT_ROOT / "tools"
AGENT_TOOLS_DIR = PROJECT_ROOT / "tools_agent"
COMMUNITY_TOOLS_DIR = PROJECT_ROOT / "tools_community"


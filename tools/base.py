"""
INTI - TAS (AI Agent Version) — Tool Base Classes
================================
Abstract tool interface and supporting types.

Every tool the constellation can invoke inherits from `Tool` and declares:
  - name, description, category
  - risk_level  (LOW → CRITICAL)
  - parameter schema (for LLM context injection)
  - execute(**kwargs) → ToolResult
"""

from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("taas")


# ============================================================
# Risk Levels
# ============================================================

class RiskLevel(str, Enum):
    """
    Determines how much validation is required before execution.

    LOW      — Executive runs directly (read-only operations)
    MEDIUM   — Reason auto-validates against Laws
    HIGH     — Reason validates + logs to ConsciousnessStream
    CRITICAL — Reason validates + requires user confirmation
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolCategory(str, Enum):
    """Broad category for tool grouping."""
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    SYSTEM = "system"
    BROWSER = "browser"
    OS_INPUT = "os_input"
    UTILITY = "utility"


class ToolOrigin(str, Enum):
    """Where a tool came from — determines trust level and env file."""
    BUILTIN = "builtin"        # tools/ directory (shipped with KRONOS)
    AGENT = "agent"            # created by KRONOS at runtime
    COMMUNITY = "community"    # downloaded from GitHub



# ============================================================
# Tool Result
# ============================================================

@dataclass
class ToolResult:
    """Standardised result from every tool invocation."""
    success: bool
    output: Any = ""
    error: str = ""
    tool_name: str = ""
    elapsed_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output if isinstance(self.output, (str, int, float, bool, list, dict)) else str(self.output),
            "error": self.error,
            "tool_name": self.tool_name,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "metadata": self.metadata,
        }


# ============================================================
# Parameter Schema
# ============================================================

@dataclass
class ToolParam:
    """Schema for a single tool parameter."""
    name: str
    description: str
    param_type: str = "string"          # string, int, float, bool, list, dict
    required: bool = True
    default: Any = None


# ============================================================
# Abstract Tool
# ============================================================

class Tool(ABC):
    """
    Abstract base for all constellation tools.
    Every concrete tool must define name, description, risk_level,
    parameters, and the execute() coroutine.
    """

    name: str = "unnamed_tool"
    description: str = ""
    category: ToolCategory = ToolCategory.UTILITY
    risk_level: RiskLevel = RiskLevel.MEDIUM
    origin: ToolOrigin = ToolOrigin.BUILTIN
    parameters: list[ToolParam] = []
    env_keys: list[str] = []  # API keys this tool needs

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given keyword arguments."""
        ...

    def get_schema(self) -> dict:
        """
        Return a JSON-serialisable schema for this tool.
        Used by the LLM to understand available tools and their params.
        """
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "risk_level": self.risk_level.value,
            "origin": self.origin.value,
            "parameters": [
                {
                    "name": p.name,
                    "description": p.description,
                    "type": p.param_type,
                    "required": p.required,
                    "default": p.default,
                }
                for p in self.parameters
            ],
        }

    async def safe_execute(self, **kwargs) -> ToolResult:
        """Wrapper that measures time and catches exceptions."""
        start = time.time()
        try:
            result = await self.execute(**kwargs)
            result.tool_name = self.name
            result.elapsed_ms = (time.time() - start) * 1000
            logger.info(
                f"[TOOL:{self.name}] {'✓' if result.success else '✗'} "
                f"({result.elapsed_ms:.0f}ms)"
            )
            return result
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            logger.error(f"[TOOL:{self.name}] Exception: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                tool_name=self.name,
                elapsed_ms=elapsed,
            )

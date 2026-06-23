"""
INTI - TAS (AI Agent Version) — Tool Registry
============================
Central registry for discovering, listing, and invoking tools.
The Will's Executive queries this registry to find available capabilities.

Supports 3 tool origins:
  BUILTIN    — tools/ directory (shipped with KRONOS)
  AGENT      — tools_agent/ (created by KRONOS at runtime)
  COMMUNITY  — tools_community/ (downloaded from GitHub)
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from typing import Optional

from tools.base import Tool, ToolResult, RiskLevel, ToolOrigin

logger = logging.getLogger("taas")


class ToolRegistry:
    """
    Discovers and manages all available tools.
    Provides schemas for LLM context injection and execution routing.
    Tracks tool origin (builtin / agent / community).
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._execution_log: list[dict] = []

    # ---- Registration ----

    def register(self, tool: Tool):
        """Register a single tool instance."""
        self._tools[tool.name] = tool
        logger.info(
            f"[REGISTRY] Registered tool: {tool.name} "
            f"(risk={tool.risk_level.value}, origin={tool.origin.value})"
        )

    def unregister(self, name: str) -> bool:
        """Remove a tool from the registry. Returns True if found."""
        if name in self._tools:
            del self._tools[name]
            logger.info(f"[REGISTRY] Unregistered tool: {name}")
            return True
        return False

    def register_defaults(self):
        """Auto-register all built-in tools."""
        from tools.file_manager import FileManagerTool
        from tools.shell import ShellTool
        from tools.api_caller import APICallerTool
        from tools.web_browser import WebBrowserTool
        from tools.web_crawler import WebCrawlerTool
        from tools.mouse_keyboard import MouseKeyboardTool
        from tools.screenshot import ScreenshotTool
        from tools.web_search import WebSearchTool
        from tools.voice import VoiceTool
        from tools.github_mcp import GitHubMCPTool
        from tools.tool_scanner import ToolScannerTool
        from tools.media_embedder import MediaEmbedderTool

        for tool_cls in [FileManagerTool, ShellTool, APICallerTool, WebBrowserTool,
                         MouseKeyboardTool, ScreenshotTool, WebSearchTool,
                         VoiceTool, GitHubMCPTool, ToolScannerTool, MediaEmbedderTool]:
            self.register(tool_cls())

        # WebCrawlerTool needs a vector store factory for crawl_embed (RAG)
        try:
            from core.vector_store import VectorMemoryStore
            from core.messages import MemoryTier
            self.register(WebCrawlerTool(
                vector_store_factory=lambda name: VectorMemoryStore(
                    collection_name=name,
                    tier=MemoryTier.SHARED,
                    owner="INTELLECT",
                )
            ))
        except Exception as e:
            logger.warning(f"[REGISTRY] WebCrawlerTool RAG unavailable: {e}")
            self.register(WebCrawlerTool())

    def register_community_tools(self):
        """
        Auto-discover and register tools from tools_community/.
        Each sub-directory should have a tool.py with a class inheriting from Tool.
        Community tools are forced to MEDIUM risk minimum.
        """
        from config.settings import COMMUNITY_TOOLS_DIR
        if not COMMUNITY_TOOLS_DIR.exists():
            return

        for tool_dir in COMMUNITY_TOOLS_DIR.iterdir():
            if not tool_dir.is_dir() or tool_dir.name.startswith("_"):
                continue
            tool_file = tool_dir / "tool.py"
            if not tool_file.exists():
                continue

            try:
                # Add to sys.path temporarily and import
                module_name = f"tools_community.{tool_dir.name}.tool"
                spec = importlib.util.spec_from_file_location(module_name, tool_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)

                    # Find Tool subclasses in the module
                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (isinstance(attr, type) and
                                issubclass(attr, Tool) and
                                attr is not Tool):
                            instance = attr()
                            # Force community origin and minimum risk
                            instance.origin = ToolOrigin.COMMUNITY
                            if instance.risk_level == RiskLevel.LOW:
                                instance.risk_level = RiskLevel.MEDIUM
                            self.register(instance)
                            logger.info(
                                f"[REGISTRY] Community tool loaded: {instance.name} "
                                f"from {tool_dir.name}"
                            )
            except Exception as e:
                logger.warning(
                    f"[REGISTRY] Failed to load community tool from {tool_dir.name}: {e}"
                )

    def register_agent_tools(self):
        """
        Auto-discover and register tools from tools_agent/.
        Same pattern as community but with AGENT origin.
        """
        from config.settings import AGENT_TOOLS_DIR
        if not AGENT_TOOLS_DIR.exists():
            return

        for tool_file in AGENT_TOOLS_DIR.glob("*.py"):
            if tool_file.name.startswith("_"):
                continue
            try:
                module_name = f"tools_agent.{tool_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, tool_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = mod
                    spec.loader.exec_module(mod)

                    for attr_name in dir(mod):
                        attr = getattr(mod, attr_name)
                        if (isinstance(attr, type) and
                                issubclass(attr, Tool) and
                                attr is not Tool):
                            instance = attr()
                            instance.origin = ToolOrigin.AGENT
                            self.register(instance)
            except Exception as e:
                logger.warning(
                    f"[REGISTRY] Failed to load agent tool from {tool_file.name}: {e}"
                )

    # ---- Discovery ----

    def get(self, name: str) -> Optional[Tool]:
        """Look up a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """Return schemas of all registered tools (for LLM injection)."""
        return [tool.get_schema() for tool in self._tools.values()]

    def list_names(self) -> list[str]:
        """Return just the tool names."""
        return list(self._tools.keys())

    def list_by_origin(self, origin: ToolOrigin) -> list[dict]:
        """Return tools filtered by origin."""
        return [
            t.get_schema()
            for t in self._tools.values()
            if t.origin == origin
        ]

    def get_by_risk(self, max_risk: RiskLevel) -> list[dict]:
        """Return tools at or below a given risk level."""
        risk_order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        max_idx = risk_order.index(max_risk)
        return [
            t.get_schema()
            for t in self._tools.values()
            if risk_order.index(t.risk_level) <= max_idx
        ]

    # ---- Execution ----

    async def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"Tool '{name}' not found. Available: {self.list_names()}",
                tool_name=name,
            )

        result = await tool.safe_execute(**kwargs)

        # Log execution
        self._execution_log.append({
            "tool": name,
            "risk": tool.risk_level.value,
            "origin": tool.origin.value,
            "success": result.success,
            "elapsed_ms": result.elapsed_ms,
        })

        return result

    # ---- Introspection ----

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def execution_count(self) -> int:
        return len(self._execution_log)

    def get_status(self) -> dict:
        origins = {}
        for t in self._tools.values():
            origins[t.origin.value] = origins.get(t.origin.value, 0) + 1
        return {
            "registered_tools": self.tool_count,
            "total_executions": self.execution_count,
            "tools": self.list_names(),
            "by_origin": origins,
        }


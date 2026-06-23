"""
INTI - TAS (AI Agent Version) — Screenshot Tool
==============================
Capture screen contents via Pillow for visual processing.
The constellation's "eyes" — feeds into Sensory's VisualInput subsystem.

Risk: LOW — read-only observation of the screen.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Default save directory
_SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "screenshots"


class ScreenshotTool(Tool):
    """Capture screenshots of the screen or specific regions."""

    name = "screenshot"
    description = (
        "Capture the screen or a specific region as a PNG image. "
        "Actions: capture (full/region), get_screen_size, list_captures. "
        "Images saved to data/screenshots/."
    )
    category = ToolCategory.OS_INPUT
    risk_level = RiskLevel.LOW
    parameters = [
        ToolParam("action", "One of: capture, get_screen_size, list_captures", "string", True),
        ToolParam("region", "Optional region as [x, y, width, height]", "list", False),
        ToolParam("save_path", "Optional custom save path (relative to screenshots dir)", "string", False),
        ToolParam("name", "Optional name for the screenshot file", "string", False),
    ]

    def __init__(self, save_dir: Optional[Path] = None):
        self._save_dir = save_dir or _SCREENSHOT_DIR
        self._pil = None

    def _get_pil(self):
        """Lazy import PIL — fails gracefully if not installed."""
        if self._pil is None:
            try:
                from PIL import ImageGrab, Image
                self._pil = {"ImageGrab": ImageGrab, "Image": Image}
            except ImportError:
                raise ImportError(
                    "Pillow is not installed. Run: pip install Pillow"
                )
        return self._pil

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if not action:
            return ToolResult(success=False, error="Missing 'action' parameter")

        try:
            if action == "capture":
                return await self._capture(
                    region=kwargs.get("region"),
                    save_path=kwargs.get("save_path"),
                    name=kwargs.get("name"),
                )
            elif action == "get_screen_size":
                return await self._get_screen_size()
            elif action == "list_captures":
                return await self._list_captures()
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}. Use: capture, get_screen_size, list_captures",
                )
        except ImportError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"Screenshot error: {e}")

    async def _capture(
        self,
        region: Optional[list] = None,
        save_path: Optional[str] = None,
        name: Optional[str] = None,
    ) -> ToolResult:
        """Capture the screen or a region."""
        pil = self._get_pil()
        ImageGrab = pil["ImageGrab"]

        # Ensure save directory exists
        self._save_dir.mkdir(parents=True, exist_ok=True)

        # Capture
        bbox = tuple(region) if region and len(region) == 4 else None
        screenshot = ImageGrab.grab(bbox=bbox)

        # Generate filename
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        if name:
            filename = f"{name}_{timestamp}.png"
        else:
            prefix = "region" if bbox else "full"
            filename = f"screen_{prefix}_{timestamp}.png"

        if save_path:
            filepath = self._save_dir / save_path
        else:
            filepath = self._save_dir / filename

        filepath.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(str(filepath), "PNG")

        width, height = screenshot.size
        file_size_kb = filepath.stat().st_size / 1024

        return ToolResult(
            success=True,
            output={
                "path": str(filepath),
                "width": width,
                "height": height,
                "size_kb": round(file_size_kb, 1),
                "region": list(bbox) if bbox else "full_screen",
            },
            metadata={
                "path": str(filepath),
                "dimensions": f"{width}x{height}",
            },
        )

    async def _get_screen_size(self) -> ToolResult:
        """Get the screen dimensions."""
        pil = self._get_pil()
        ImageGrab = pil["ImageGrab"]

        # Grab a tiny screenshot to get screen size
        screen = ImageGrab.grab()
        width, height = screen.size

        return ToolResult(
            success=True,
            output={"width": width, "height": height},
        )

    async def _list_captures(self) -> ToolResult:
        """List all saved screenshots."""
        if not self._save_dir.exists():
            return ToolResult(success=True, output=[])

        captures = []
        for f in sorted(self._save_dir.glob("*.png"), reverse=True)[:20]:
            captures.append({
                "name": f.name,
                "path": str(f),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(f.stat().st_mtime),
                ),
            })

        return ToolResult(
            success=True,
            output=captures,
            metadata={"count": len(captures), "directory": str(self._save_dir)},
        )

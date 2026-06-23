"""
INTI - TAS (AI Agent Version) — Mouse & Keyboard Control Tool
============================================
Full OS input control — dual mode:

Mode 1 (default): pyautogui — direct coordinate-based control (local, free)
Mode 2 (optional): Gemini Computer Use — AI-driven screen understanding (API)

With Gemini Computer Use, the agent can describe what to do in natural
language (e.g. "click the Send button") and the model figures out WHERE
on screen to click by analyzing a screenshot.

Risk: CRITICAL — direct manipulation of the operating system.
Every invocation requires Reason validation + consciousness logging.

Actions:
  move, click, type_text, hotkey, scroll, drag, get_position  (pyautogui)
  smart_action  (Gemini Computer Use — screenshot→reason→act)

Config:
  Set COMPUTER_USE_MODE=gemini in .env to use Gemini by default.
  Otherwise, use action=smart_action to invoke Gemini on-demand.
"""

from __future__ import annotations

import logging
import os
import time

from tools.base import Tool, ToolResult, ToolParam, RiskLevel, ToolCategory

logger = logging.getLogger("taas")

# Gemini Computer Use model — configurable via .env
# Options: gemini-2.5-computer-use-preview-10-2025, or any newer CU model
GEMINI_CU_MODEL = os.environ.get(
    "COMPUTER_USE_MODEL", "gemini-2.5-computer-use-preview-10-2025"
).strip() or "gemini-2.5-computer-use-preview-10-2025"


class MouseKeyboardTool(Tool):
    """
    Control mouse and keyboard — dual mode.

    Default: pyautogui (coordinate-based, local, free)
    Optional: Gemini Computer Use (AI-driven, screenshots, API key required)
    """

    name = "mouse_keyboard"
    description = (
        "Control the mouse and keyboard on the host operating system. "
        "Actions: move, click, type_text, hotkey, scroll, drag, get_position "
        "(direct pyautogui), smart_action (Gemini Computer Use — describe what "
        "you want in natural language, AI analyzes screen and acts). "
        "CRITICAL risk — requires Reason authorization."
    )
    category = ToolCategory.OS_INPUT
    risk_level = RiskLevel.CRITICAL
    parameters = [
        ToolParam("action", "One of: move, click, type_text, hotkey, scroll, drag, get_position, smart_action", "string", True),
        ToolParam("x", "X coordinate for move/click/drag", "int", False),
        ToolParam("y", "Y coordinate for move/click/drag", "int", False),
        ToolParam("text", "Text to type (type_text) or goal description (smart_action)", "string", False),
        ToolParam("keys", "Key names for hotkey, e.g. ['ctrl', 'c']", "list", False),
        ToolParam("button", "Mouse button: left, right, middle (default: left)", "string", False, "left"),
        ToolParam("clicks", "Number of clicks (default: 1)", "int", False, 1),
        ToolParam("interval", "Delay between keystrokes in seconds (default: 0.05)", "float", False, 0.05),
        ToolParam("amount", "Scroll amount (positive=up, negative=down)", "int", False),
        ToolParam("duration", "Duration for move/drag animation in seconds (default: 0.3)", "float", False, 0.3),
        ToolParam("max_steps", "Max action steps for smart_action (default: 5)", "int", False, 5),
    ]

    def __init__(self):
        self._pyautogui = None
        self._gemini_client = None

    def _get_pyautogui(self):
        """Lazy import pyautogui — fails gracefully if not installed."""
        if self._pyautogui is None:
            try:
                import pyautogui
                pyautogui.FAILSAFE = True  # Move mouse to corner to abort
                pyautogui.PAUSE = 0.1      # Small pause between actions
                self._pyautogui = pyautogui
            except ImportError:
                raise ImportError(
                    "pyautogui is not installed. Run: pip install pyautogui"
                )
        return self._pyautogui

    def _get_gemini_client(self):
        """Lazy init Gemini client for Computer Use.
        
        Uses COMPUTER_USE_API_KEY if set (e.g. AI Studio key with separate quota),
        otherwise falls back to GEMINI_API_KEY.
        """
        if self._gemini_client is None:
            try:
                from google import genai
                # Prefer dedicated CU key (AI Studio) over main key (Google Cloud)
                api_key = (
                    os.environ.get("COMPUTER_USE_API_KEY")
                    or os.environ.get("GEMINI_API_KEY")
                    or os.environ.get("DEFAULT_LLM_API_KEY")
                )
                if not api_key:
                    raise ValueError("No API key found for Computer Use. Set COMPUTER_USE_API_KEY or GEMINI_API_KEY in .env")
                source = "COMPUTER_USE_API_KEY" if os.environ.get("COMPUTER_USE_API_KEY") else "GEMINI_API_KEY"
                self._gemini_client = genai.Client(api_key=api_key)
                logger.info(f"[MOUSE] Gemini Computer Use client initialized (key source: {source})")
            except ImportError:
                raise ImportError("google-genai not installed. Run: pip install google-genai")
        return self._gemini_client

    async def execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action", "").lower()

        if not action:
            return ToolResult(success=False, error="Missing 'action' parameter")

        try:
            pag = self._get_pyautogui()

            if action == "get_position":
                pos = pag.position()
                screen = pag.size()
                return ToolResult(
                    success=True,
                    output={"x": pos.x, "y": pos.y,
                            "screen_width": screen.width,
                            "screen_height": screen.height},
                )

            elif action == "move":
                x = kwargs.get("x", 0)
                y = kwargs.get("y", 0)
                duration = kwargs.get("duration", 0.3)
                pag.moveTo(x, y, duration=duration)
                return ToolResult(
                    success=True,
                    output=f"Moved mouse to ({x}, {y})",
                    metadata={"x": x, "y": y},
                )

            elif action == "click":
                x = kwargs.get("x")
                y = kwargs.get("y")
                button = kwargs.get("button", "left")
                clicks = kwargs.get("clicks", 1)
                if x is not None and y is not None:
                    pag.click(x=x, y=y, button=button, clicks=clicks)
                else:
                    pag.click(button=button, clicks=clicks)
                pos = pag.position()
                return ToolResult(
                    success=True,
                    output=f"Clicked {button} ({clicks}x) at ({pos.x}, {pos.y})",
                    metadata={"x": pos.x, "y": pos.y, "button": button, "clicks": clicks},
                )

            elif action == "type_text":
                text = kwargs.get("text", "")
                interval = kwargs.get("interval", 0.05)
                if not text:
                    return ToolResult(success=False, error="Missing 'text' parameter")
                pag.typewrite(text, interval=interval)
                return ToolResult(
                    success=True,
                    output=f"Typed {len(text)} characters",
                    metadata={"chars": len(text)},
                )

            elif action == "hotkey":
                keys = kwargs.get("keys", [])
                if not keys:
                    return ToolResult(success=False, error="Missing 'keys' parameter")
                pag.hotkey(*keys)
                return ToolResult(
                    success=True,
                    output=f"Pressed hotkey: {'+'.join(keys)}",
                    metadata={"keys": keys},
                )

            elif action == "scroll":
                amount = kwargs.get("amount", 0)
                x = kwargs.get("x")
                y = kwargs.get("y")
                pag.scroll(amount, x=x, y=y)
                return ToolResult(
                    success=True,
                    output=f"Scrolled {'up' if amount > 0 else 'down'} by {abs(amount)}",
                    metadata={"amount": amount},
                )

            elif action == "drag":
                x = kwargs.get("x", 0)
                y = kwargs.get("y", 0)
                duration = kwargs.get("duration", 0.3)
                button = kwargs.get("button", "left")
                pag.dragTo(x, y, duration=duration, button=button)
                return ToolResult(
                    success=True,
                    output=f"Dragged to ({x}, {y})",
                    metadata={"x": x, "y": y, "button": button},
                )

            elif action == "smart_action":
                return await self._smart_action(kwargs)

            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown action: {action}. "
                          f"Use: move, click, type_text, hotkey, scroll, drag, get_position, smart_action",
                )

        except ImportError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"OS I/O error: {e}")

    # ----------------------------------------------------------------
    # smart_action — Gemini Computer Use (AI-driven screen control)
    # ----------------------------------------------------------------

    def _take_screenshot(self) -> bytes:
        """Take a screenshot and return as PNG bytes."""
        pag = self._get_pyautogui()
        import io
        screenshot = pag.screenshot()
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        return buf.getvalue()

    def _denormalize_coords(self, x: int, y: int) -> tuple[int, int]:
        """
        Convert Gemini's normalized coordinates (0-999) to screen pixels.
        Gemini Computer Use outputs coords in 0-999 range regardless of resolution.
        """
        pag = self._get_pyautogui()
        screen = pag.size()
        actual_x = int(x / 1000 * screen.width)
        actual_y = int(y / 1000 * screen.height)
        return actual_x, actual_y

    def _execute_gemini_action(self, function_call) -> dict:
        """
        Execute a single Gemini Computer Use function call via pyautogui.
        Maps Gemini's normalized actions to pyautogui calls.
        """
        pag = self._get_pyautogui()
        fname = function_call.name
        args = function_call.args or {}

        try:
            if fname == "click_at":
                ax, ay = self._denormalize_coords(args.get("x", 500), args.get("y", 500))
                pag.click(x=ax, y=ay)
                return {"action": fname, "x": ax, "y": ay, "status": "ok"}

            elif fname == "type_text_at":
                ax, ay = self._denormalize_coords(args.get("x", 500), args.get("y", 500))
                text = args.get("text", "")
                press_enter = args.get("press_enter", False)
                clear = args.get("clear_before_typing", False)

                pag.click(x=ax, y=ay)
                time.sleep(0.1)
                if clear:
                    pag.hotkey("ctrl", "a")
                    pag.press("backspace")
                    time.sleep(0.05)
                pag.typewrite(text, interval=0.03)
                if press_enter:
                    pag.press("enter")
                return {"action": fname, "x": ax, "y": ay, "text": text, "status": "ok"}

            elif fname == "hover_at":
                ax, ay = self._denormalize_coords(args.get("x", 500), args.get("y", 500))
                pag.moveTo(ax, ay, duration=0.2)
                return {"action": fname, "x": ax, "y": ay, "status": "ok"}

            elif fname == "key_combination":
                keys_str = args.get("keys", "")
                keys = [k.strip() for k in keys_str.split("+")]
                pag.hotkey(*keys)
                return {"action": fname, "keys": keys, "status": "ok"}

            elif fname == "scroll_document" or fname == "scroll_at":
                direction = args.get("direction", "down")
                magnitude = args.get("magnitude", 300)
                scroll_amount = magnitude if direction == "up" else -magnitude
                x = args.get("x")
                y = args.get("y")
                if x is not None and y is not None:
                    ax, ay = self._denormalize_coords(x, y)
                    pag.scroll(scroll_amount // 100, x=ax, y=ay)
                else:
                    pag.scroll(scroll_amount // 100)
                return {"action": fname, "direction": direction, "status": "ok"}

            elif fname == "drag_and_drop":
                sx, sy = self._denormalize_coords(args.get("x", 0), args.get("y", 0))
                dx, dy = self._denormalize_coords(
                    args.get("destination_x", 0), args.get("destination_y", 0)
                )
                pag.moveTo(sx, sy, duration=0.1)
                pag.dragTo(dx, dy, duration=0.3)
                return {"action": fname, "from": (sx, sy), "to": (dx, dy), "status": "ok"}

            elif fname in ("open_web_browser", "wait_5_seconds"):
                if fname == "wait_5_seconds":
                    time.sleep(5)
                return {"action": fname, "status": "ok"}

            elif fname == "navigate":
                url = args.get("url", "")
                # Open URL in default browser
                import webbrowser
                webbrowser.open(url)
                time.sleep(2)
                return {"action": fname, "url": url, "status": "ok"}

            elif fname == "go_back":
                pag.hotkey("alt", "left")
                return {"action": fname, "status": "ok"}

            elif fname == "go_forward":
                pag.hotkey("alt", "right")
                return {"action": fname, "status": "ok"}

            else:
                return {"action": fname, "status": "unimplemented", "error": f"Unknown: {fname}"}

        except Exception as e:
            return {"action": fname, "status": "error", "error": str(e)}

    async def _smart_action(self, kwargs: dict) -> ToolResult:
        """
        AI-driven Computer Use: describe a goal in natural language,
        the AI analyzes the screen and performs the actions.

        Supports multiple providers via COMPUTER_USE_PROVIDER env var:
          - "gemini"    (default) — Gemini Computer Use model
          - "anthropic" — Claude Computer Use (Sonnet)

        Config in .env:
          COMPUTER_USE_PROVIDER=anthropic
          COMPUTER_USE_API_KEY=sk-ant-...
          COMPUTER_USE_MODEL=claude-sonnet-4-20250514
        """
        goal = kwargs.get("text", "").strip()
        if not goal:
            return ToolResult(success=False, error="Missing 'text' — describe what you want to do")

        max_steps = min(kwargs.get("max_steps", 5), 10)

        provider = os.environ.get("COMPUTER_USE_PROVIDER", "gemini").lower().strip()

        if provider == "anthropic":
            return await self._smart_action_anthropic(goal, max_steps)
        else:
            return await self._smart_action_gemini(goal, max_steps)

    # ================================================================
    # GEMINI Computer Use
    # ================================================================

    async def _smart_action_gemini(self, goal: str, max_steps: int) -> ToolResult:
        """Gemini Computer Use agent loop."""
        try:
            from google.genai import types
            from google.genai.types import Content, Part

            client = self._get_gemini_client()

            config = types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        computer_use=types.ComputerUse(
                            environment=types.Environment.ENVIRONMENT_BROWSER,
                        ),
                    ),
                ],
            )

            screenshot_bytes = self._take_screenshot()
            contents = [
                Content(role="user", parts=[
                    Part(text=goal),
                    Part.from_bytes(data=screenshot_bytes, mime_type="image/png"),
                ]),
            ]

            actions_log = []
            current_url = ""

            for step in range(max_steps):
                logger.info(f"[MOUSE] Gemini CU step {step + 1}/{max_steps}")

                response = None
                for retry in range(3):
                    try:
                        response = client.models.generate_content(
                            model=GEMINI_CU_MODEL,
                            contents=contents,
                            config=config,
                        )
                        break
                    except Exception as e:
                        if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                            wait = 10 * (2 ** retry)
                            logger.warning(f"[MOUSE] Rate limited, waiting {wait}s (retry {retry+1}/3)")
                            time.sleep(wait)
                        else:
                            raise

                if response is None:
                    return ToolResult(success=False, error="Rate limited after 3 retries")

                candidate = response.candidates[0]
                contents.append(candidate.content)

                function_calls = [
                    part.function_call for part in candidate.content.parts
                    if part.function_call
                ]

                if not function_calls:
                    text_parts = [p.text for p in candidate.content.parts if p.text]
                    final_text = " ".join(text_parts) if text_parts else "Task completed"
                    break

                for fc in function_calls:
                    result = self._execute_gemini_action(fc)
                    actions_log.append(result)
                    logger.info(f"[MOUSE] Executed: {result}")
                    if fc.name == "navigate" and fc.args:
                        current_url = fc.args.get("url", current_url)
                    elif fc.name == "open_web_browser":
                        current_url = "about:blank"
                    time.sleep(0.5)

                time.sleep(10)

                screenshot_bytes = self._take_screenshot()
                function_responses = []
                for fc in function_calls:
                    function_responses.append(
                        Part(function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"status": "ok", "current_url": current_url or "about:blank"},
                        ))
                    )
                function_responses.append(
                    Part.from_bytes(data=screenshot_bytes, mime_type="image/png"),
                )
                contents.append(Content(role="user", parts=function_responses))

            else:
                final_text = f"Reached max steps ({max_steps})"

            return ToolResult(
                success=True,
                output={"goal": goal, "steps_taken": len(actions_log),
                        "actions": actions_log, "result": final_text,
                        "engine": "gemini-computer-use"},
                metadata={"model": GEMINI_CU_MODEL, "max_steps": max_steps},
            )

        except ImportError as e:
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"[MOUSE] Gemini CU error: {e}")
            return ToolResult(success=False, error=f"Gemini CU error: {e}")

    # ================================================================
    # ANTHROPIC Claude Computer Use
    # ================================================================

    async def _smart_action_anthropic(self, goal: str, max_steps: int) -> ToolResult:
        """Anthropic Claude Computer Use agent loop."""
        try:
            import anthropic
            import base64
        except ImportError:
            return ToolResult(
                success=False,
                error="anthropic not installed. Run: pip install anthropic",
            )

        try:
            pag = self._get_pyautogui()
            screen = pag.size()

            api_key = (
                os.environ.get("COMPUTER_USE_API_KEY")
                or os.environ.get("ANTHROPIC_API_KEY")
            )
            if not api_key:
                return ToolResult(
                    success=False,
                    error="No Anthropic key. Set COMPUTER_USE_API_KEY in .env",
                )

            model = os.environ.get("COMPUTER_USE_MODEL", "claude-sonnet-4-20250514")
            client = anthropic.Anthropic(api_key=api_key)
            logger.info(f"[MOUSE] Anthropic CU initialized (model={model})")

            # Initial screenshot
            screenshot_b64 = base64.standard_b64encode(
                self._take_screenshot()
            ).decode("utf-8")

            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": goal},
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/png",
                        "data": screenshot_b64,
                    }},
                ],
            }]

            tools = [{
                "type": "computer_20250124",
                "name": "computer",
                "display_width_px": screen.width,
                "display_height_px": screen.height,
            }]

            actions_log = []

            for step in range(max_steps):
                logger.info(f"[MOUSE] Anthropic CU step {step + 1}/{max_steps}")

                response = client.beta.messages.create(
                    model=model,
                    max_tokens=1024,
                    tools=tools,
                    messages=messages,
                )

                # Check if model is done
                if response.stop_reason == "end_turn":
                    text_parts = [b.text for b in response.content if hasattr(b, "text")]
                    final_text = " ".join(text_parts) if text_parts else "Task completed"
                    break

                # Get tool use blocks
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if not tool_uses:
                    text_parts = [b.text for b in response.content if hasattr(b, "text")]
                    final_text = " ".join(text_parts) if text_parts else "Task completed"
                    break

                # Add assistant message
                messages.append({"role": "assistant", "content": response.content})

                # Execute actions and send results back
                tool_results_content = []
                for tu in tool_uses:
                    action_input = tu.input
                    action_type = action_input.get("action", "")
                    result = self._execute_anthropic_action(action_type, action_input)
                    actions_log.append(result)
                    logger.info(f"[MOUSE] Executed: {result}")
                    time.sleep(0.5)

                    # Screenshot after action
                    new_b64 = base64.standard_b64encode(
                        self._take_screenshot()
                    ).decode("utf-8")

                    tool_results_content.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": [{
                            "type": "image",
                            "source": {
                                "type": "base64", "media_type": "image/png",
                                "data": new_b64,
                            },
                        }],
                    })

                messages.append({"role": "user", "content": tool_results_content})
                time.sleep(1)

            else:
                final_text = f"Reached max steps ({max_steps})"

            return ToolResult(
                success=True,
                output={"goal": goal, "steps_taken": len(actions_log),
                        "actions": actions_log, "result": final_text,
                        "engine": "anthropic-computer-use"},
                metadata={"model": model, "max_steps": max_steps},
            )

        except Exception as e:
            logger.error(f"[MOUSE] Anthropic CU error: {e}")
            return ToolResult(success=False, error=f"Anthropic CU error: {e}")

    def _execute_anthropic_action(self, action: str, params: dict) -> dict:
        """Execute a single Anthropic Computer Use action via pyautogui."""
        pag = self._get_pyautogui()

        try:
            coord = params.get("coordinate", [0, 0])
            x = coord[0] if coord else 0
            y = coord[1] if len(coord) > 1 else 0

            if action in ("left_click", "click"):
                pag.click(x=x, y=y, button="left")
                return {"action": action, "x": x, "y": y, "status": "ok"}

            elif action == "right_click":
                pag.click(x=x, y=y, button="right")
                return {"action": action, "x": x, "y": y, "status": "ok"}

            elif action == "double_click":
                pag.doubleClick(x=x, y=y)
                return {"action": action, "x": x, "y": y, "status": "ok"}

            elif action == "triple_click":
                pag.tripleClick(x=x, y=y)
                return {"action": action, "x": x, "y": y, "status": "ok"}

            elif action == "mouse_move":
                pag.moveTo(x, y, duration=0.2)
                return {"action": action, "x": x, "y": y, "status": "ok"}

            elif action == "left_click_drag":
                end = params.get("end_coordinate", [x, y])
                pag.moveTo(x, y, duration=0.1)
                pag.dragTo(end[0], end[1], duration=0.3)
                return {"action": action, "from": [x, y], "to": end, "status": "ok"}

            elif action == "type":
                text = params.get("text", "")
                pag.typewrite(text, interval=0.03)
                return {"action": action, "text": text, "status": "ok"}

            elif action == "key":
                key = params.get("text", "")
                key_map = {
                    "Return": "enter", "Enter": "enter",
                    "Backspace": "backspace", "Delete": "delete",
                    "Tab": "tab", "Escape": "escape", "space": "space",
                    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
                }
                if "+" in key:
                    keys = [key_map.get(k.strip(), k.strip().lower()) for k in key.split("+")]
                    pag.hotkey(*keys)
                else:
                    pag.press(key_map.get(key, key.lower()))
                return {"action": action, "key": key, "status": "ok"}

            elif action == "screenshot":
                return {"action": action, "status": "ok"}

            elif action == "scroll":
                amount = params.get("amount", -3)
                pag.scroll(amount, x=x, y=y)
                return {"action": action, "amount": amount, "status": "ok"}

            elif action == "wait":
                time.sleep(params.get("duration", 2))
                return {"action": action, "status": "ok"}

            else:
                return {"action": action, "status": "unimplemented"}

        except Exception as e:
            return {"action": action, "status": "error", "error": str(e)}


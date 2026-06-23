"""
INTI — TAS (AI Agent Version) — Rich Terminal Interface
====================================
Visual interface for observing and interacting with the constellation.
"""

from __future__ import annotations

import asyncio
import json
import logging

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich.layout import Layout
from rich.columns import Columns
from rich.markdown import Markdown
from rich.prompt import Prompt

from core.messages import (
    TASMessage, MessageType, NodePriority, HealthStatus,
)

logger = logging.getLogger("taas")
console = Console()


# ============================================================
# Genesis Display
# ============================================================

MOMENT_NAMES = {
    1: "Life Assertion",
    2: "Laws Incarnation",
    3: "System Instantiation",
    4: "ISHM Activation",
    5: "Memory Layout",
    6: "Nexus Bonding",
    7: "Rules & Mission",
    8: "Language Validation",
    9: "Self-Awareness Test",
}


async def display_genesis_moment(moment: int, name: str, status: str):
    """Callback for genesis protocol — displays each moment."""
    color = "green" if "✓" in status else "yellow"
    emoji = "✅" if "✓" in status else "⏳"
    console.print(
        f"  {emoji}  [bold]Moment {moment}[/bold]: "
        f"[cyan]{name}[/cyan] — [{color}]{status}[/{color}]"
    )


def show_genesis_complete(result: dict):
    """Display genesis completion summary."""
    table = Table(title="📊 Genesis Summary", show_lines=True)
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Value", style="green")

    table.add_row("Status", result.get("status", "UNKNOWN"))
    table.add_row("Elapsed", f"{result.get('elapsed_seconds', 0)}s")
    table.add_row("Systems Online", str(len(result.get("systems", []))))
    table.add_row("Memory Stores", str(result.get("memory_stores", 0)))
    table.add_row("Self-Awareness Fragments", str(result.get("self_awareness_fragments", 0)))

    console.print()
    console.print(table)
    console.print()


# ============================================================
# Helpers
# ============================================================

def _extract_summary(content) -> str:
    """Extract a short one-line summary from a system's output for the thinking trace."""
    text = str(content) if not isinstance(content, str) else content
    # Clean up dict-like strings
    if isinstance(content, dict):
        # Try to find a meaningful key
        for key in ("summary", "content", "analysis", "verdict", "action", "plan"):
            if key in content:
                text = str(content[key])
                break
    # Truncate to one readable line
    text = text.replace("\n", " ").replace("\r", "").strip()
    if len(text) > 120:
        text = text[:117] + "..."
    return text


# ============================================================
# Main Interaction Loop
# ============================================================

async def interaction_loop(constellation: dict):
    """Main user interaction loop."""
    nexus = constellation["nexus"]
    memory = constellation["memory"]
    ishm = constellation["ishm"]
    systems = constellation["systems"]
    thought_system = constellation.get("thought_system")

    # Wire up human confirmation callback for CRITICAL tools
    will = systems.get("WILL")
    if will and hasattr(will, "executive"):
        async def confirm_callback(tool_name, action, params):
            console.print()
            console.print(
                Panel(
                    f"[bold yellow]⚠️  CONFIRMATION REQUIRED[/bold yellow]\n\n"
                    f"Tool: [cyan]{tool_name}[/cyan]\n"
                    f"Action: [cyan]{action}[/cyan]\n"
                    f"Params: {json.dumps(params, indent=2)[:300]}",
                    title="🔒 Security",
                    border_style="yellow",
                )
            )
            answer = Prompt.ask("Approve?", choices=["y", "n"], default="n")
            return answer.lower() == "y"

        will.executive.set_confirm_callback(confirm_callback)

    console.print(
        Panel(
            "[bold green]Constellation OPERATIONAL[/bold green]\n"
            "Type your message to interact with the constellation.\n"
            "Commands: /status, /health, /memory, /consciousness, /tools, "
            "/tool, /journal, /undo, /security, /twin, /conference, "
            "/contemplate, /insights, /quit",
            title="🌞 INTI",
            border_style="bright_blue",
        )
    )

    # Start autonomous contemplation loop (controlled by .env toggle)
    import os
    contemplation_enabled = os.getenv("CONTEMPLATION_ENABLED", "false").lower() in ("true", "1", "yes")
    if thought_system and contemplation_enabled:
        thought_system.start_contemplation_loop(interval_s=60.0)
        console.print("[dim]💭 Autonomous contemplation loop started (60s intervals)[/dim]")
    elif thought_system:
        console.print("[dim]💭 Contemplation loop disabled (set CONTEMPLATION_ENABLED=true in .env to enable)[/dim]")

    # Helper: find WILL system reliably
    def _find_will():
        """Find WILL system from constellation — tries multiple paths."""
        # Path 1: nexus.nodes (most reliable)
        nexus = constellation.get("nexus")
        if nexus and hasattr(nexus, "nodes"):
            w = nexus.nodes.get("WILL")
            if w:
                return w
        # Path 2: systems dict
        w = constellation.get("systems", {}).get("WILL")
        if w:
            return w
        # Path 3: thought_system → nexus
        ts = constellation.get("thought_system")
        if ts and hasattr(ts, "nexus"):
            w = ts.nexus.nodes.get("WILL")
            if w:
                return w
        return None

    while True:
        # Show pending repair patches (if any)
        try:
            will_system = _find_will()
            if will_system and hasattr(will_system, "repair"):
                pending = will_system.repair.get_pending_patches()
                if pending:
                    console.print(
                        f"\n[bold yellow]⚠️  ISHM: {len(pending)} patch(es) awaiting approval. "
                        f"Type 'approve' to review and apply.[/bold yellow]"
                    )
                    for p in pending[:3]:
                        console.print(f"[yellow]   → {p.get('id', '?')}: {p.get('file_path', '?')} — {p.get('description', '?')[:60]}[/yellow]")
        except Exception:
            pass

        try:
            # Use run_in_executor so input doesn't block the event loop
            # This allows ISHM background monitoring to run while waiting for input
            import asyncio as _asyncio
            loop = _asyncio.get_event_loop()
            user_input = await loop.run_in_executor(
                None, lambda: Prompt.ask("\n[bold cyan]You[/bold cyan]")
            )
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input.strip():
            continue

        # --- Repair Approve Command ---
        if user_input.strip().lower() in ("approve", "/approve"):
            will_system = _find_will()
            if will_system and hasattr(will_system, "repair"):
                pending = will_system.repair.get_pending_patches()
                if pending:
                    for patch in pending:
                        console.print(f"\n[bold yellow]🔧 Approving patch: {patch['id']}[/bold yellow]")
                        console.print(f"[dim]   File: {patch.get('file_path', '?')}[/dim]")
                        console.print(f"[dim]   Description: {patch.get('description', '?')[:100]}[/dim]")
                        if patch.get("diff_preview"):
                            console.print(Panel(
                                patch["diff_preview"][:1000],
                                title="📝 Diff Preview",
                                border_style="yellow",
                                expand=False,
                            ))
                        result = await will_system.repair.approve_patch(patch["id"])
                        if result.get("success"):
                            console.print(f"[bold green]✅ Patch {patch['id']} applied successfully![/bold green]")
                        else:
                            console.print(f"[bold red]❌ Patch failed: {result.get('error', 'unknown')}[/bold red]")
                else:
                    console.print("[dim]No pending patches.[/dim]")
            else:
                console.print(f"[dim]Repair system not found. Keys: {list(constellation.keys())}[/dim]")
            continue

        # --- Commands ---
        if user_input.startswith("/"):
            await handle_command(user_input, constellation)
            continue

        # --- Parallel Constellation Deliberation ---
        # Ref: Figueroa PPT slide 64 — "not sequential, nor hierarchical"
        # All systems process independently and in parallel via Nexus conference
        console.print("[dim]⏳ Constellation deliberating in parallel...[/dim]")
        nexus = constellation["nexus"]

        # Track this interaction for the contemplation loop
        if thought_system:
            thought_system.record_interaction()

        # One call: broadcasts to all 7 systems, collects fragments, executes tools
        assembled = await nexus.deliberate(user_input)

        # --- Build Thinking Trace from fragments ---
        deliberation_trace = []
        system_icons = {
            "SENSORY": "👁️", "UNDERSTANDING": "🔍", "DECISION": "⚖️",
            "REASON": "🧭", "WILL": "⚡", "INTELLECT": "💡",
            "THOUGHT": "🧠",
        }
        for frag in assembled.get("fragments", []):
            sys_name = frag.get("source_system", "?")
            icon = system_icons.get(sys_name, "•")
            content = str(frag.get("content", ""))[:500]
            ftype = frag.get("fragment_type", "")
            conf = frag.get("confidence", 0)
            deliberation_trace.append(
                f"  {icon} [cyan]{sys_name}[/cyan] [{ftype}|{conf:.0%}]: [dim]{content}[/dim]"
            )

        # Show tool execution results
        tool_results_data = assembled.get("tool_results", [])
        for tr in tool_results_data:
            result = tr.get("result", {})
            if hasattr(result, "__dict__"):
                result = {"success": result.success, "output": result.output, "error": result.error}
            success = result.get("success", False)
            tool_icon = "✅" if success else "❌"
            tool_name = tr.get("tool", "?")
            output_preview = str(result.get("output", ""))[:300]
            error_info = str(result.get("error", ""))[:200] if not success else ""
            trace_line = f"  🔧 [cyan]TOOL[/cyan]: {tool_icon} {tool_name}: [dim]{output_preview}[/dim]"
            if error_info:
                trace_line += f"\n     [red]ERROR: {error_info}[/red]"
            deliberation_trace.append(trace_line)

        # Show vetoes if any
        if assembled.get("vetoed"):
            for veto in assembled.get("vetoes", []):
                deliberation_trace.append(
                    f"  🚫 [red]VETO[/red]: [dim]{str(veto)[:300]}[/dim]"
                )

        # Show override if Will Dominance overrode a veto
        if assembled.get("override_active"):
            deliberation_trace.append(
                f"  ⚡ [yellow bold]OVERRIDE[/yellow bold]: "
                f"[dim]{assembled.get('override_justification', 'Survival override')[:120]}[/dim]"
            )

        # Display trace
        if deliberation_trace:
            console.print(
                Panel(
                    "\n".join(deliberation_trace),
                    title=f"🔍 Constellation Deliberation ({assembled.get('fragment_count', 0)} fragments from {len(assembled.get('sources', []))} systems)",
                    border_style="dim",
                    padding=(0, 1),
                )
            )

        # --- Presentation renders final conversational response ---
        presentation = systems.get("PRESENTATION")
        if presentation and assembled.get("content"):
            # Smart tool output display:
            #   shell → full output (user-facing execution)
            #   everything else → compact status line (internal operations)
            has_tool_output = False
            for tr in tool_results_data:
                result = tr.get("result", {})
                output = str(getattr(result, "output", result) if hasattr(result, "output") else result.get("output", ""))
                success = getattr(result, "success", True) if hasattr(result, "success") else result.get("success", True) if isinstance(result, dict) else True
                icon = "✅" if success else "❌"
                tool_name = tr.get("tool", "?")
                error = str(getattr(result, "error", result) if hasattr(result, "error") else result.get("error", "")) if not success else ""
                display_text = output.strip() or error.strip()
                if not display_text:
                    continue
                has_tool_output = True
                if tool_name == "shell":
                    # Shell = user-facing execution → show full output
                    border = "cyan" if success else "red"
                    console.print(
                        Panel(
                            display_text[:5000],
                            title=f"{icon} {tool_name}",
                            border_style=border,
                        )
                    )
                else:
                    # Internal tools → compact 1-line status
                    preview = display_text.replace("\n", " ")[:120]
                    console.print(f"  {icon} [bold]{tool_name}[/bold]: {preview}...")

            # Ask user if they want AI interpretation of tool results
            interpret_results = False
            if has_tool_output:
                try:
                    answer = Prompt.ask(
                        "[dim]Interpret results with AI?[/dim]",
                        choices=["y", "n"], default="n"
                    )
                    interpret_results = answer.lower() == "y"
                except (EOFError, KeyboardInterrupt):
                    pass

            # Build tool summary — only if user wants interpretation
            tool_summary = ""
            if interpret_results:
                tool_summary = "\n".join(
                    f"- {tr['tool']}: {'SUCCESS' if (tr.get('result',{}).get('success') if isinstance(tr.get('result'), dict) else getattr(tr.get('result'), 'success', False)) else 'FAILED'} "
                    f"— {str((tr.get('result',{}).get('output','') if isinstance(tr.get('result'), dict) else getattr(tr.get('result'), 'output', '')))[:2000]}"
                    for tr in tool_results_data
                )
            elif has_tool_output:
                # Build concise status summary (no full output — saves tokens)
                statuses = []
                shell_succeeded = False
                for tr in tool_results_data:
                    r = tr.get("result", {})
                    s = r.get("success", getattr(r, "success", False)) if isinstance(r, dict) else getattr(r, "success", False)
                    statuses.append(f"{tr.get('tool','?')}: {'OK' if s else 'FAIL'}")
                    if tr.get("tool") == "shell" and s:
                        shell_succeeded = True
                status_line = ", ".join(statuses)
                completion = " — TASK COMPLETE, output already shown to user." if shell_succeeded else ""
                tool_summary = f"Tools executed: {status_line}{completion}"

            delib_context = {
                "user_input": user_input,
                "constellation_thought": assembled.get("content", "")[:2000],
                "tool_results": tool_summary or "No tools were used",
                "available_tools": ", ".join(will.executive.registry._tools.keys()) if will and hasattr(will, "executive") and hasattr(will.executive, "registry") else "shell, web_search, file_manager, media_embedder, github_mcp, voice, mouse_keyboard",
                "sources": ", ".join(assembled.get("sources", [])),
                "avg_confidence": assembled.get("avg_confidence", 0),
                "vetoed": assembled.get("vetoed", False),
                "override_active": assembled.get("override_active", False),
            }
            render_msg = TASMessage(
                priority=NodePriority.NORMAL.value,
                sender="NEXUS",
                receiver="PRESENTATION",
                msg_type=MessageType.RENDER_OUTPUT,
                content={
                    "format": "conversational",
                    "content": delib_context,
                },
            )
            final = await presentation.process_message(render_msg)
            final_text = str(final.content) if final else ""
            if final:
                console.print(
                    Panel(
                        final_text,
                        title="🌞 INTI",
                        border_style="bright_green",
                    )
                )

            # Save conversation history AFTER Presentation renders
            # so it includes what the user actually saw
            tool_names = ", ".join(tr.get("tool", "?") for tr in tool_results_data) if tool_results_data else ""
            nexus._conversation_history.append({
                "user": user_input[:500],
                "response": final_text[:500],  # What Presentation actually said
                "tools": tool_names,
            })
            if len(nexus._conversation_history) > nexus._MAX_HISTORY:
                nexus._conversation_history = nexus._conversation_history[-nexus._MAX_HISTORY:]

        else:
            # Fallback: show raw assembled content
            fallback_text = assembled.get("content", "No response generated")
            console.print(
                Panel(
                    fallback_text,
                    title="🌞 INTI",
                    border_style="green",
                )
            )
            # Save fallback response to history too
            nexus._conversation_history.append({
                "user": user_input[:500],
                "response": str(fallback_text)[:500],
                "tools": "",
            })
            if len(nexus._conversation_history) > nexus._MAX_HISTORY:
                nexus._conversation_history = nexus._conversation_history[-nexus._MAX_HISTORY:]


async def handle_command(command: str, constellation: dict):
    """Handle CLI commands."""
    nexus = constellation["nexus"]
    memory = constellation["memory"]
    ishm = constellation["ishm"]
    systems = constellation["systems"]
    persistence = constellation.get("persistence")
    thought_system = constellation.get("thought_system")

    if command == "/quit":
        # Stop contemplation loop
        if thought_system:
            thought_system.stop_contemplation_loop()
        # Save system states + memory before shutdown
        if persistence:
            from core.persistence import ConstellationStateSaver
            state_saved = ConstellationStateSaver.save_system_states(systems, memory)
            saved = persistence.save_all(memory)
            console.print(f"[dim]💾 Memory saved ({saved} stores, states: {', '.join(state_saved.keys()) or 'none'})[/dim]")
        console.print("[yellow]Shutting down constellation...[/yellow]")
        raise SystemExit(0)

    elif command == "/status":
        table = Table(title="🔧 System Status", show_lines=True)
        table.add_column("System", style="cyan", width=15)
        table.add_column("Health", width=12)
        table.add_column("Messages", width=10)
        table.add_column("Errors", width=10)
        table.add_column("Subsystems", width=8)

        for name, system in systems.items():
            status = system.get_status()
            health = status["health"]
            h_color = {"NOMINAL": "green", "DEGRADED": "yellow",
                       "CRITICAL": "red", "OFFLINE": "red"}.get(health, "white")
            table.add_row(
                name,
                f"[{h_color}]{health}[/{h_color}]",
                str(status["message_count"]),
                str(status["error_count"]),
                str(len(status.get("subsystems", {}))),
            )
        console.print(table)

    elif command == "/health":
        result = await ishm.run_cycle()
        table = Table(title="💊 ISHM Health Report", show_lines=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        for k, v in result.items():
            table.add_row(str(k), str(v))
        console.print(table)

    elif command == "/memory":
        stores = memory.list_stores()
        table = Table(title="🧠 Memory Stores", show_lines=True)
        table.add_column("Store", style="cyan", width=35)
        table.add_column("Tier", width=12)
        table.add_column("Owner", width=15)
        table.add_column("Size", width=8)
        for name, info in stores.items():
            table.add_row(name, info["tier"], info["owner"], str(info["size"]))
        console.print(table)

    elif command == "/consciousness":
        entries = nexus.consciousness.get_recent(15)
        if not entries:
            console.print("[dim]No consciousness entries yet.[/dim]")
            return
        table = Table(title="💭 Consciousness Stream (Recent)", show_lines=True)
        table.add_column("Source", style="cyan", width=12)
        table.add_column("Event", width=18)
        table.add_column("Content", width=50)
        for e in entries:
            table.add_row(
                e["source"],
                e["event_type"],
                e["content"][:80],
            )
        console.print(table)

    elif command.startswith("/conference "):
        topic = command[12:].strip()
        if not topic:
            console.print("[red]Usage: /conference <topic>[/red]")
            return
        console.print(f"[dim]⏳ Starting constellation conference on: {topic}[/dim]")
        fragments = await nexus.conference(topic=topic, initiator="USER")
        console.print(f"\n[bold]📋 Conference Results[/bold] ({len(fragments)} fragments):")
        for f in fragments:
            console.print(
                f"  [{f.source_system}] "
                f"({f.fragment_type.value}, conf={f.confidence:.2f}): "
                f"{f.content[:120]}"
            )

    elif command == "/tools":
        will = systems.get("WILL")
        if will and hasattr(will, "executive"):
            tools_list = will.executive.list_tools()
            table = Table(title="🔧 Available Tools", show_lines=True)
            table.add_column("Name", style="cyan", width=15)
            table.add_column("Category", width=12)
            table.add_column("Risk", width=10)
            table.add_column("Description", width=45)
            for t in tools_list:
                risk_color = {"low": "green", "medium": "yellow",
                              "high": "red", "critical": "bold red"}.get(t["risk_level"], "white")
                table.add_row(
                    t["name"],
                    t["category"],
                    f"[{risk_color}]{t['risk_level'].upper()}[/{risk_color}]",
                    t["description"][:60],
                )
            console.print(table)
        else:
            console.print("[red]Will system not available.[/red]")

    elif command.startswith("/tool "):
        # /tool <name> <json_params>
        parts = command[6:].strip().split(" ", 1)
        tool_name = parts[0]
        try:
            params = json.loads(parts[1]) if len(parts) > 1 else {}
        except json.JSONDecodeError:
            console.print("[red]Invalid JSON params. Usage: /tool <name> {\"key\": \"value\"}[/red]")
            return

        will = systems.get("WILL")
        if will and hasattr(will, "executive"):
            console.print(f"[dim]⏳ Invoking tool: {tool_name}...[/dim]")
            result = await will.executive.invoke_tool(tool_name, **params)
            success = result.get("success", False)
            color = "green" if success else "red"
            console.print(
                Panel(
                    str(result.get("output", result.get("error", "No output"))),
                    title=f"🔧 {tool_name} [{'✓' if success else '✗'}]",
                    border_style=color,
                )
            )
        else:
            console.print("[red]Will system not available.[/red]")

    elif command == "/journal":
        will = systems.get("WILL")
        if will and hasattr(will, "executive"):
            entries = will.executive.security.journal.recent(15)
            if not entries:
                console.print("[dim]No journal entries yet.[/dim]")
                return
            table = Table(title="📜 Action Journal", show_lines=True)
            table.add_column("#", style="dim", width=4)
            table.add_column("Time", width=19)
            table.add_column("Tool", style="cyan", width=14)
            table.add_column("Action", width=10)
            table.add_column("Verdict", width=10)
            table.add_column("✓/✗", width=4)
            table.add_column("Undo", width=5)
            for e in entries:
                v_color = {"ALLOWED": "green", "DENIED": "red", "VETOED": "red"}.get(e["verdict"], "yellow")
                table.add_row(
                    str(e["id"]),
                    e["timestamp"],
                    e["tool"],
                    e["action"],
                    f"[{v_color}]{e['verdict']}[/{v_color}]",
                    "✓" if e["success"] else "✗",
                    "🔄" if e["rollback_available"] else "",
                )
            console.print(table)
        else:
            console.print("[red]Will system not available.[/red]")

    elif command == "/undo":
        will = systems.get("WILL")
        if will and hasattr(will, "executive"):
            result = will.executive.security.journal.undo_last()
            if result["success"]:
                console.print(
                    Panel(
                        f"Undone action #{result['undone_id']}: "
                        f"{result['tool']}.{result['action']}\n"
                        f"Restored: {result['restored']}",
                        title="↩️ Undo Successful",
                        border_style="green",
                    )
                )
            else:
                console.print(f"[red]Undo failed: {result['error']}[/red]")
        else:
            console.print("[red]Will system not available.[/red]")

    elif command == "/security":
        will = systems.get("WILL")
        if will and hasattr(will, "executive"):
            status = will.executive.security.get_status()
            table = Table(title="🔒 Security Policy Status", show_lines=True)
            table.add_column("Metric", style="cyan", width=20)
            table.add_column("Value", style="green", width=10)
            for k, v in status.items():
                table.add_row(k.replace("_", " ").title(), str(v))
            console.print(table)
        else:
            console.print("[red]Will system not available.[/red]")

    elif command.startswith("/twin"):
        parts = command.split(None, 2)
        sub = parts[1] if len(parts) > 1 else "status"

        # Lazy load twin engine
        if not hasattr(handle_command, "_twin_engine"):
            from core.twin import DigitalTwinEngine
            handle_command._twin_engine = DigitalTwinEngine(
                constellation={"nexus": nexus, "memory": memory, "ishm": ishm, "systems": systems}
            )
        twin = handle_command._twin_engine

        if sub == "status":
            status = twin.get_status()
            table = Table(title="🧬 Digital Twin Status", show_lines=True)
            table.add_column("Metric", style="cyan", width=20)
            table.add_column("Value", style="green", width=12)
            for k, v in status.items():
                table.add_row(k.replace("_", " ").title(), str(v))
            console.print(table)

        elif sub == "history":
            history = twin.get_history()
            if not history:
                console.print("[dim]No twin attempts yet.[/dim]")
            else:
                table = Table(title="🧬 Twin History", show_lines=True)
                table.add_column("ID", style="dim", width=10)
                table.add_column("Time", width=19)
                table.add_column("Status", width=12)
                table.add_column("Verdict", width=10)
                table.add_column("Tests", width=8)
                table.add_column("Description", width=30)
                for h in history:
                    s_color = {"completed": "green", "rolled_back": "yellow", "failed": "red"}.get(h["status"], "dim")
                    table.add_row(
                        h["twin_id"], h["timestamp"],
                        f"[{s_color}]{h['status']}[/{s_color}]",
                        h["verdict"], h["tests"],
                        h["description"][:30],
                    )
                console.print(table)

        elif sub == "run":
            description = parts[2] if len(parts) > 2 else "Manual twin test"
            console.print(f"[dim]🧬 Starting Digital Twin cycle: {description}...[/dim]")

            async def twin_confirm(report):
                console.print(
                    Panel(
                        f"[bold green]Twin {report.twin_id} ready for migration[/bold green]\n\n"
                        f"Genesis: {'✓' if report.genesis_ok else '✗'}\n"
                        f"Tests: {report.tests_passed}/{report.tests_total} "
                        f"({report.test_pass_rate:.0%})\n"
                        f"Reason approved: {'✓' if report.reason_approved else '✗'}\n"
                        f"Files mutated: {report.files_mutated}",
                        title="🧬 Migration Approval",
                        border_style="yellow",
                    )
                )
                answer = Prompt.ask("Approve migration?", choices=["y", "n"], default="n")
                return answer.lower() == "y"

            report = await twin.run_cycle(
                description=description,
                confirm_callback=twin_confirm,
            )
            color = {"completed": "green", "rolled_back": "yellow"}.get(report.status.value, "red")
            console.print(
                Panel(
                    f"Status: [{color}]{report.status.value}[/{color}]\n"
                    f"Verdict: {report.verdict}\n"
                    f"Genesis: {'✓' if report.genesis_ok else '✗'}  |  "
                    f"Tests: {report.tests_passed}/{report.tests_total}\n"
                    f"Notes: {report.evaluation_notes}",
                    title=f"🧬 Twin {report.twin_id} Complete",
                    border_style=color,
                )
            )
        else:
            console.print("[dim]Usage: /twin status | /twin run <description> | /twin history[/dim]")

    elif command == "/save":
        if persistence:
            from core.persistence import ConstellationStateSaver
            state_saved = ConstellationStateSaver.save_system_states(systems, memory)
            saved = persistence.save_all(memory)
            status = persistence.get_status()
            state_summary = "\n".join(f"  {k}: {v}" for k, v in state_saved.items()) or "  (none)"
            console.print(
                Panel(
                    f"Stores saved: [green]{saved}[/green]\n"
                    f"Total entries: {status['total_entries']}\n"
                    f"System states:\n{state_summary}\n"
                    f"Database: [dim]{status['db_path']}[/dim]",
                    title="💾 Memory + State Saved",
                    border_style="green",
                )
            )
        else:
            console.print("[red]No persistence layer configured.[/red]")

    elif command == "/contemplate" or command.startswith("/contemplate "):
        # On-demand contemplation
        topic = command[len("/contemplate"):].strip()
        if not topic:
            topic = "Reflect on the current state of the constellation and what could be improved."
        if thought_system:
            console.print(f"[dim]💭 Contemplating: {topic[:60]}...[/dim]")
            result = await thought_system.contemplate(topic)
            console.print(
                Panel(
                    str(result),
                    title="💭 Contemplation",
                    border_style="magenta",
                )
            )
        else:
            console.print("[red]ThoughtSystem not available.[/red]")

    elif command == "/insights":
        # View recent autonomous contemplation insights
        if thought_system:
            insights = thought_system.get_recent_insights(5)
            if not insights:
                console.print("[dim]No autonomous insights yet. The system contemplates every 60s.[/dim]")
            else:
                for i, ins in enumerate(insights, 1):
                    import datetime
                    ts = datetime.datetime.fromtimestamp(ins.get("timestamp", 0)).strftime("%H:%M:%S")
                    console.print(
                        Panel(
                            f"[bold]{ins.get('type', 'general')}[/bold] — {ins.get('health', '?')}\n"
                            f"Interactions tracked: {ins.get('interaction_count', 0)}\n\n"
                            f"{str(ins.get('reflection', ''))[:500]}",
                            title=f"💭 Insight #{i} ({ts})",
                            border_style="magenta",
                        )
                    )
        else:
            console.print("[red]ThoughtSystem not available.[/red]")

    else:
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print(
            "[dim]Available: /status, /health, /memory, /consciousness, "
            "/tools, /tool, /journal, /undo, /security, /twin, /save, "
            "/conference, /contemplate, /insights, /quit[/dim]"
        )

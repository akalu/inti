"""
INTI — TAS (AI Agent Version) — Main Entry Point
====================================
Boots the cognitive constellation and enters the interaction loop.

Usage:
    python main.py
"""

import asyncio
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.panel import Panel

# ================================================================
# PRE-FLIGHT INTEGRITY CHECK
# Runs BEFORE importing project modules to catch syntax errors
# that would prevent the system from starting.
# Uses Gemini API directly (no WILL/ISHM needed).
# ================================================================

def preflight_integrity_check():
    """
    Compile-check all core source files before importing them.
    If any have syntax errors, attempt LLM-based repair.
    Returns True if all files are OK (or were fixed).
    """
    import py_compile
    from pathlib import Path

    project_root = Path(__file__).resolve().parent
    console = Console()

    CORE_FILES = [
        "systems/will.py", "systems/reason.py", "systems/intellect.py",
        "systems/thought.py", "systems/sensory.py", "systems/decision.py",
        "systems/understanding.py", "systems/presentation.py",
        "core/nexus.py", "core/base.py", "core/messages.py",
        "genesis.py", "interface/cli.py",
    ]

    broken = []
    for rel_path in CORE_FILES:
        full_path = project_root / rel_path
        if not full_path.exists():
            continue
        try:
            py_compile.compile(str(full_path), doraise=True)
        except py_compile.PyCompileError as e:
            broken.append((rel_path, str(full_path), str(e)))

    if not broken:
        return True

    # Show what's broken
    console.print(f"\n[bold red]⚠️  PRE-FLIGHT CHECK: {len(broken)} file(s) have syntax errors![/bold red]")
    for rel, full, err in broken:
        console.print(f"[red]   ❌ {rel}[/red]")
        # Show just the error line
        err_short = err.split('\n')[-1] if '\n' in err else err[:200]
        console.print(f"[dim]      {err_short}[/dim]")

    console.print()

    # Attempt repair
    auto_repair = os.getenv("AUTO_REPAIR", "false").lower() in ("true", "1", "yes")

    for rel_path, full_path, error_msg in broken:
        console.print(f"\n[yellow]🔧 Attempting to repair {rel_path}...[/yellow]")

        try:
            # Read the broken file
            source = Path(full_path).read_text(encoding="utf-8")

            # Use Gemini API directly (minimal dependency)
            import google.genai as genai
            client = genai.Client()
            model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

            prompt = (
                f"You are a code repair system. Fix the SYNTAX ERROR in this Python file.\n"
                f"Error: {error_msg[:500]}\n\n"
                f"Source code:\n```python\n{source[:8000]}\n```\n\n"
                f"Return ONLY the complete fixed Python source code. "
                f"No markdown fences, no explanations. Just the code."
            )

            response = client.models.generate_content(model=model, contents=prompt)
            patched = response.text.strip()

            # Clean markdown fences if present
            if patched.startswith("```"):
                lines = patched.split("\n")
                lines = lines[1:]  # Remove opening fence
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                patched = "\n".join(lines)

            if not patched or len(patched) < 20:
                console.print(f"[red]   LLM returned empty patch, skipping.[/red]")
                continue

            # Generate diff
            import difflib
            diff = difflib.unified_diff(
                source.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
            )
            diff_text = "".join(diff)

            if not diff_text:
                console.print(f"[dim]   No changes needed (LLM returned identical code).[/dim]")
                continue

            # Show diff preview
            console.print(Panel(
                diff_text[:2000],
                title=f"📝 Repair Diff: {rel_path}",
                border_style="yellow",
                expand=False,
            ))

            # Approval gate
            if auto_repair:
                apply = True
                console.print(f"[yellow]   AUTO_REPAIR=true → applying automatically[/yellow]")
            else:
                response_input = input(f"   Apply this patch to {rel_path}? [y/n]: ").strip().lower()
                apply = response_input in ("y", "yes")

            if apply:
                # Backup original
                backup_path = Path(full_path).with_suffix(".py.bak")
                backup_path.write_text(source, encoding="utf-8")

                # Verify patch compiles
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
                    tmp.write(patched)
                    tmp_path = tmp.name

                try:
                    py_compile.compile(tmp_path, doraise=True)
                    # Patch compiles! Apply it.
                    Path(full_path).write_text(patched, encoding="utf-8")
                    console.print(f"[bold green]   ✅ {rel_path} repaired successfully! (backup: {backup_path.name})[/bold green]")
                except py_compile.PyCompileError:
                    console.print(f"[red]   ❌ LLM patch has syntax errors too! Keeping original.[/red]")
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
            else:
                console.print(f"[dim]   Skipped.[/dim]")

        except Exception as e:
            console.print(f"[red]   Repair failed: {e}[/red]")

    # Re-check
    still_broken = []
    for rel_path in CORE_FILES:
        full_path = project_root / rel_path
        if not full_path.exists():
            continue
        try:
            py_compile.compile(str(full_path), doraise=True)
        except py_compile.PyCompileError:
            still_broken.append(rel_path)

    if still_broken:
        console.print(f"\n[bold red]❌ {len(still_broken)} file(s) still broken. Cannot start.[/bold red]")
        for f in still_broken:
            console.print(f"[red]   {f}[/red]")
        return False

    console.print(f"\n[bold green]✅ All files OK — proceeding with startup.[/bold green]")
    return True


# Run pre-flight check BEFORE importing project modules
if not preflight_integrity_check():
    print("Aborting: source integrity check failed.")
    sys.exit(1)

from genesis import GenesisProtocol
from interface.cli import display_genesis_moment, show_genesis_complete, interaction_loop

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/taas.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("taas")

# Silence noisy library loggers (still go to file)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)

console = Console()


BANNER = r"""
 ██╗███╗  ██╗████████╗██╗    ████████╗ █████╗ ███████╗
 ██║████╗ ██║╚══██╔══╝██║    ╚══██╔══╝██╔══██╗██╔════╝
 ██║██╔██╗██║   ██║   ██║█████╗ ██║   ███████║███████╗
 ██║██║╚████║   ██║   ██║╚════╝ ██║   ██╔══██║╚════██║
 ██║██║ ████║   ██║   ██║       ██║   ██║  ██║███████║
 ╚═╝╚═╝ ╚═══╝   ╚═╝   ╚═╝       ╚═╝   ╚═╝  ╚═╝╚══════╝

    Thinking Autonomous System — AI Agent Version
    Cognitive Constellation Architecture — Figueroa 2025
"""


async def main():
    """Main entry point — boot the constellation."""
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    console.print(Panel(BANNER, border_style="bright_blue", title="INTI"))
    console.print()
    console.print("[bold cyan]🚀 Initiating 9-Moment Genesis Protocol...[/bold cyan]")
    console.print()

    genesis = GenesisProtocol()

    try:
        result = await genesis.execute(on_moment=display_genesis_moment)
        show_genesis_complete(result)

        if result["status"] == "OPERATIONAL":
            constellation = genesis.get_constellation()

            # Start ISHM background monitoring
            await genesis.ishm.start_monitoring()

            # Start Nexus dispatch loop
            await genesis.nexus.start_dispatch()

            # Enter interaction loop
            await interaction_loop(constellation)

            # Cleanup
            await genesis.ishm.stop_monitoring()
            await genesis.nexus.stop_dispatch()
        else:
            console.print("[bold red]❌ Genesis failed! Constellation not operational.[/bold red]")
            sys.exit(1)

    except SystemExit:
        console.print("[yellow]👋 Constellation shutdown.[/yellow]")
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Interrupted. Shutting down...[/yellow]")
    except Exception as e:
        console.print(f"[bold red]❌ Fatal error: {e}[/bold red]")
        logger.exception("Fatal error during constellation boot")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

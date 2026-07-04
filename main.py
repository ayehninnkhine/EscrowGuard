"""
main.py
-------
EscrowGuard — Approval-Gated Shell and System Mutation Agent

Entry point for the interactive CLI. Displays a welcome banner
and runs the orchestrator in a loop until the user quits.

Usage:
    export GEMINI_API_KEY="your_api_key_here"
    python main.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.text import Text

# ── Ensure the project root is on the Python path ───────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from orchestrator import EscrowGuardOrchestrator

console = Console()

_BANNER = """\
[bold cyan]
  ███████╗███████╗ ██████╗██████╗  ██████╗ ██╗    ██╗ ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗
  ██╔════╝██╔════╝██╔════╝██╔══██╗██╔═══██╗██║    ██║██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗
  █████╗  ███████╗██║     ██████╔╝██║   ██║██║ █╗ ██║██║  ███╗██║   ██║███████║██████╔╝██║  ██║
  ██╔══╝  ╚════██║██║     ██╔══██╗██║   ██║██║███╗██║██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║
  ███████╗███████║╚██████╗██║  ██║╚██████╔╝╚███╔███╔╝╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝
  ╚══════╝╚══════╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝
[/bold cyan]"""

_SUBTITLE = """\
[bold white]Approval-Gated Shell and System Mutation Agent[/bold white]
[dim]Powered by Google Antigravity SDK  ·  Multi-Agent Developer Workflow[/dim]"""

_HELP = """\
[bold]How it works:[/bold]
  1. You describe a developer task in plain language.
  2. The [cyan]Planner Agent[/cyan] breaks it into steps tagged as 🟢 safe / 🟡 moderate / 🔴 risky.
  3. Safe steps execute immediately.
  4. Risky steps pause at the [bold red]Approval Gate[/bold red] — you see the risk analysis and decide.
  5. The [cyan]Reviewer Agent[/cyan] explains every risk before you decide.
  6. All decisions are logged to [bold]escrowguard_audit.jsonl[/bold].

[bold]Example tasks to try:[/bold]
  • "List all Python files in the current directory"
  • "Clean build artifacts and update the version in package.json to 2.0.0"
  • "Delete all .log files in /tmp and restart the app server"
  • "Update the .env file to set DEBUG=false and call the health check API"

[dim]Type [bold]quit[/bold] or [bold]exit[/bold] to end the session. Type [bold]help[/bold] to show this message again.[/dim]"""


def _check_api_key() -> bool:
    """Verify that GEMINI_API_KEY is set."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        console.print()
        console.print(
            Panel(
                "[bold red]❌ GEMINI_API_KEY is not set.[/bold red]\n\n"
                "Please export your API key before running EscrowGuard:\n\n"
                '[dim]  export GEMINI_API_KEY="your_api_key_here"[/dim]',
                title="[bold red]Configuration Error[/bold red]",
                border_style="red",
                box=box.ROUNDED,
            )
        )
        return False
    return True


def _print_welcome() -> None:
    """Print the welcome banner and help text."""
    console.print(_BANNER)
    console.print(Panel(_SUBTITLE, border_style="cyan", box=box.ROUNDED, expand=False))
    console.print()
    console.print(Panel(_HELP, title="[bold white]Quick Start[/bold white]", border_style="dim", box=box.ROUNDED))
    console.print()


async def _interactive_loop() -> None:
    """Main interactive loop — accepts tasks and runs the orchestrator."""
    orchestrator = EscrowGuardOrchestrator()

    while True:
        console.print(Rule("[dim]New Task[/dim]"))
        try:
            user_input = await asyncio.to_thread(
                Prompt.ask,
                "\n[bold cyan]🔐 EscrowGuard[/bold cyan] [dim]>[/dim]",
                console=console,
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[bold white]👋 Session ended. Goodbye![/bold white]")
            break

        user_input = user_input.strip()

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[bold white]👋 Session ended. Goodbye![/bold white]")
            break

        if user_input.lower() in ("help", "h", "?"):
            console.print(Panel(_HELP, border_style="dim", box=box.ROUNDED))
            continue

        try:
            await orchestrator.run(user_input)
        except SystemExit:
            break
        except KeyboardInterrupt:
            console.print("\n[bold yellow]⚠️  Task interrupted by user.[/bold yellow]")
        except Exception as exc:
            console.print(f"\n[bold red]❌ Orchestrator error:[/bold red] {exc}")


async def main() -> None:
    if not _check_api_key():
        sys.exit(1)

    _print_welcome()

    try:
        await _interactive_loop()
    except KeyboardInterrupt:
        console.print("\n[bold white]👋 Session ended. Goodbye![/bold white]")


if __name__ == "__main__":
    asyncio.run(main())

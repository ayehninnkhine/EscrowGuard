"""
approval_gate.py
----------------
The human approval gate for EscrowGuard.

When the Antigravity SDK's `ask_user` policy fires for a risky tool call,
this module:
  1. Asks the Reviewer Agent to analyze the risk.
  2. Renders a rich terminal approval panel.
  3. Prompts the human: [A]pprove / [R]eject / [V]Revise.
  4. Returns the decision so the SDK can proceed or cancel the tool call.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from core.audit_log import AuditLog, Decision
from core.risk_classifier import RiskLevel, RiskReport, classify_risk

if TYPE_CHECKING:
    pass

console = Console()

_RISK_COLORS = {
    RiskLevel.SAFE: "green",
    RiskLevel.MODERATE: "yellow",
    RiskLevel.RISKY: "red",
}

_RISK_ICONS = {
    RiskLevel.SAFE: "🟢",
    RiskLevel.MODERATE: "🟡",
    RiskLevel.RISKY: "🔴",
}


@dataclass
class ApprovalDecision:
    approved: bool
    revised_args: dict[str, Any] | None = None  # set when user chooses Revise
    reason: str = ""


class ApprovalGate:
    """
    Manages the human-in-the-loop approval gate.

    Usage:
        gate = ApprovalGate(audit_log=log, reviewer_agent=reviewer)
        decision = await gate.handle(agent_name, tool_name, args, risk_report)
    """

    def __init__(
        self,
        audit_log: AuditLog,
        reviewer_agent: Any | None = None,  # ReviewerAgent instance; optional
    ) -> None:
        self._log = audit_log
        self._reviewer = reviewer_agent

    async def handle(
        self,
        agent_name: str,
        tool_name: str,
        args: dict[str, Any],
        risk_report: RiskReport | None = None,
    ) -> ApprovalDecision:
        """
        Display the approval gate UI and wait for a human decision.
        Returns an ApprovalDecision.
        """
        if risk_report is None:
            risk_report = classify_risk(tool_name, args)

        # Get Reviewer analysis if reviewer agent is available
        reviewer_text = await self._get_reviewer_analysis(tool_name, args)

        # Render approval panel
        self._render_panel(agent_name, tool_name, args, risk_report, reviewer_text)

        # Prompt for decision
        decision = await self._prompt_decision(agent_name, tool_name, args, risk_report, reviewer_text)
        return decision

    async def _get_reviewer_analysis(
        self, tool_name: str, args: dict[str, Any]
    ) -> str:
        """Ask the Reviewer Agent for a risk analysis summary."""
        if self._reviewer is None:
            return "Reviewer Agent not available — using heuristic analysis only."
        try:
            return await self._reviewer.analyze(tool_name, args)
        except Exception as exc:
            return f"Reviewer Agent error: {exc}"

    def _render_panel(
        self,
        agent_name: str,
        tool_name: str,
        args: dict[str, Any],
        risk_report: RiskReport,
        reviewer_text: str,
    ) -> None:
        """Render the rich terminal approval gate panel."""
        color = _RISK_COLORS[risk_report.level]
        icon = _RISK_ICONS[risk_report.level]

        # Build args display
        args_display = "\n".join(
            f"  [dim]{k}:[/dim] {str(v)[:120]}" for k, v in args.items()
        )

        body = (
            f"[bold]Agent:[/bold]       [cyan]{agent_name}[/cyan]\n"
            f"[bold]Tool:[/bold]        [yellow]{tool_name}[/yellow]\n"
            f"[bold]Arguments:[/bold]\n{args_display}\n\n"
            f"[bold]Risk Level:[/bold]  [{color}]{icon}  {risk_report.level.value.upper()}[/{color}]\n"
            f"[bold]Reason:[/bold]      {risk_report.reason}\n\n"
            f"[bold]Reviewer Analysis:[/bold]\n"
            f"[italic]{reviewer_text}[/italic]\n\n"
            "[dim]Options: [bold green](A)[/bold green]pprove  "
            "[bold red](R)[/bold red]eject  "
            "[bold yellow](V)[/bold yellow]Revise  "
            "[bold white](Q)[/bold white]uit[/dim]"
        )

        panel = Panel(
            body,
            title="[bold white on red]  ⚠  ESCROWGUARD APPROVAL GATE  ⚠  [/bold white on red]",
            border_style=color,
            box=box.DOUBLE_EDGE,
            expand=False,
            padding=(1, 3),
        )
        console.print()
        console.print(panel)
        console.print()

    async def _prompt_decision(
        self,
        agent_name: str,
        tool_name: str,
        args: dict[str, Any],
        risk_report: RiskReport,
        reviewer_text: str,
    ) -> ApprovalDecision:
        """Prompt the user for a decision and return an ApprovalDecision."""
        while True:
            choice = await asyncio.to_thread(
                Prompt.ask,
                "[bold]Your decision[/bold]",
                choices=["a", "r", "v", "q"],
                default="r",
                console=console,
            )
            choice = choice.lower()

            if choice == "a":
                console.print("[bold green]✅ Action APPROVED by human.[/bold green]\n")
                await self._log.record_decision(
                    agent=agent_name,
                    tool_name=tool_name,
                    args=args,
                    risk_level=risk_report.level.value,
                    decision=Decision.APPROVED,
                    reason="Human approved via approval gate.",
                    reviewer_summary=reviewer_text,
                )
                return ApprovalDecision(approved=True, reason="Human approved.")

            elif choice == "r":
                console.print("[bold red]❌ Action REJECTED by human.[/bold red]\n")
                await self._log.record_decision(
                    agent=agent_name,
                    tool_name=tool_name,
                    args=args,
                    risk_level=risk_report.level.value,
                    decision=Decision.REJECTED,
                    reason="Human rejected via approval gate.",
                    reviewer_summary=reviewer_text,
                )
                return ApprovalDecision(approved=False, reason="Human rejected.")

            elif choice == "v":
                console.print("[bold yellow]✏️  Enter revised arguments:[/bold yellow]")
                revised = await self._collect_revised_args(tool_name, args)
                console.print("[bold green]✅ Revised action APPROVED by human.[/bold green]\n")
                await self._log.record_decision(
                    agent=agent_name,
                    tool_name=tool_name,
                    args=revised,
                    risk_level=risk_report.level.value,
                    decision=Decision.REVISED,
                    reason="Human revised and approved via approval gate.",
                    reviewer_summary=reviewer_text,
                )
                return ApprovalDecision(approved=True, revised_args=revised, reason="Human revised and approved.")

            elif choice == "q":
                console.print("[bold white]👋 Session terminated by human.[/bold white]")
                raise SystemExit(0)

    async def _collect_revised_args(
        self, tool_name: str, original_args: dict[str, Any]
    ) -> dict[str, Any]:
        """Interactively collect revised arguments from the human."""
        revised = dict(original_args)
        for key, original_value in original_args.items():
            new_val = await asyncio.to_thread(
                Prompt.ask,
                f"  [dim]{key}[/dim]",
                default=str(original_value),
                console=console,
            )
            # Try to preserve type
            if isinstance(original_value, bool):
                revised[key] = new_val.lower() in ("true", "1", "yes")
            elif isinstance(original_value, int):
                try:
                    revised[key] = int(new_val)
                except ValueError:
                    revised[key] = new_val
            else:
                revised[key] = new_val
        return revised

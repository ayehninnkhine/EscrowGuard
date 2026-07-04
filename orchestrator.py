"""
orchestrator.py
---------------
EscrowGuard Orchestrator — the top-level coordinator.

Responsibilities:
  1. Accept a user request.
  2. Call the Planner Agent to decompose it into steps.
  3. For each step, route to the appropriate sub-agent (Shell, Mutation).
  4. Risky steps are automatically intercepted by the approval gate.
  5. Log every action and decision to the audit trail.
  6. Stream results back to the user in real time.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich import box

from agents.planner import PlannerAgent, PlanStep
from agents.reviewer import ReviewerAgent
from agents.shell_utility import ShellUtilityAgent
from agents.mutation import MutationAgent
from core.approval_gate import ApprovalGate
from core.audit_log import AuditLog, Decision
from core.risk_classifier import classify_risk, RiskLevel

console = Console()


class EscrowGuardOrchestrator:
    """
    Top-level orchestrator that coordinates all four sub-agents.
    """

    def __init__(self) -> None:
        self._session_id = str(uuid.uuid4())[:8]
        self._audit = AuditLog(session_id=self._session_id)

        # Initialize agents
        self._reviewer = ReviewerAgent()
        self._gate = ApprovalGate(audit_log=self._audit, reviewer_agent=self._reviewer)
        self._planner = PlannerAgent()
        self._shell = ShellUtilityAgent(approval_gate=self._gate)
        self._mutation = MutationAgent(approval_gate=self._gate)

    async def run(self, user_request: str) -> None:
        """
        Main orchestration loop for a single user request.
        """
        console.print()
        console.print(
            Panel(
                f"[bold cyan]{user_request}[/bold cyan]",
                title="[bold white]📋 User Request[/bold white]",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )

        # ── Step 1: Plan ────────────────────────────────────────────────────
        console.print()
        console.print(Rule("[bold blue]🧠 Planning Phase[/bold blue]"))

        plan: list[PlanStep]
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
            console=console,
        ) as progress:
            task = progress.add_task("Planner Agent is decomposing your request...", total=None)
            try:
                plan = await self._planner.plan(user_request)
            except Exception as exc:
                console.print(f"[bold red]❌ Planner failed:[/bold red] {exc}")
                await self._audit.record_error("PlannerAgent", str(exc))
                return

        await self._audit.record_plan(
            agent="PlannerAgent",
            plan_summary=f"{len(plan)} steps planned for: {user_request[:80]}",
        )

        # Print plan summary
        console.print(f"\n[bold green]✅ Plan ready — {len(plan)} step(s)[/bold green]\n")
        for step in plan:
            risk_color = {"safe": "green", "moderate": "yellow", "risky": "red"}.get(
                step.risk_level, "white"
            )
            console.print(
                f"  [{risk_color}]{'●'}[/{risk_color}] "
                f"[dim]Step {step.step}[/dim]  "
                f"[bold]{step.description}[/bold]  "
                f"[dim]→ {step.agent} / {step.tool}[/dim]"
            )
        console.print()

        # ── Step 2: Execute each step ────────────────────────────────────────
        console.print(Rule("[bold blue]⚡ Execution Phase[/bold blue]"))

        for step in plan:
            await self._execute_step(step)

        # ── Step 3: Audit summary ────────────────────────────────────────────
        console.print()
        console.print(Rule("[bold blue]📋 Session Summary[/bold blue]"))
        self._audit.print_summary()

    async def _execute_step(self, step: PlanStep) -> None:
        """Route a single step to the correct sub-agent and handle its result."""
        risk_icon = {"safe": "🟢", "moderate": "🟡", "risky": "🔴"}.get(step.risk_level, "⚪")
        risk_color = {"safe": "green", "moderate": "yellow", "risky": "red"}.get(
            step.risk_level, "white"
        )

        console.print(
            f"\n[bold]{risk_icon}  Step {step.step}:[/bold] {step.description}"
        )
        console.print(
            f"   [dim]Agent: {step.agent}  |  Tool: {step.tool}  |  "
            f"Risk: [{risk_color}]{step.risk_level.upper()}[/{risk_color}][/dim]"
        )

        # Log the proposed tool call
        await self._audit.record_tool_call(
            agent=step.agent,
            tool_name=step.tool,
            args=step.args,
            risk_level=step.risk_level,
        )

        # Route to the correct agent
        try:
            if step.agent == "shell_utility":
                result = await self._shell.execute(step.tool, step.args)
            elif step.agent == "mutation":
                result = await self._mutation.execute(step.tool, step.args)
            elif step.agent == "reviewer":
                result = await self._reviewer.analyze(step.tool, step.args)
            else:
                result = f"[warning] Unknown agent '{step.agent}', skipping step."

            # Update audit with result
            await self._audit.record_tool_call(
                agent=step.agent,
                tool_name=step.tool,
                args=step.args,
                risk_level=step.risk_level,
                result=result[:200],
            )

            # Display result
            if result and not result.startswith("[error]"):
                console.print(
                    Panel(
                        result.strip(),
                        title=f"[dim]Step {step.step} Result[/dim]",
                        border_style="dim",
                        box=box.SIMPLE,
                        padding=(0, 2),
                    )
                )
            elif result:
                console.print(f"   [bold red]{result}[/bold red]")

        except SystemExit:
            raise  # propagate quit signal
        except Exception as exc:
            err = f"Step {step.step} failed: {type(exc).__name__}: {exc}"
            console.print(f"   [bold red]❌ {err}[/bold red]")
            await self._audit.record_error(step.agent, err)

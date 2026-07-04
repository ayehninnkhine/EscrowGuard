"""
shell_utility.py
----------------
Shell Utility Agent — executes shell commands with a policy-controlled
approval gate for risky operations.

Uses the Antigravity SDK's `ask_user` hook policy to intercept
destructive commands before execution.
"""

from __future__ import annotations

import sys
from typing import Any

from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.hooks.policy import deny, allow, ask_user

from tools.shell_tools import SHELL_TOOLS
from core.risk_classifier import classify_risk, RiskLevel

_SHELL_AGENT_SYSTEM_PROMPT = """\
You are the EscrowGuard Shell Utility Agent — a specialized sub-agent that executes
shell commands on behalf of the orchestrator.

You have access to the following tools:
- run_shell_command(command): Run a shell command and return its output.
- list_processes(): List running processes.
- read_file_contents(path): Read a file (read-only).
- list_directory(path): List directory contents.

Safety rules you MUST follow:
1. ALWAYS use the exact tool arguments given to you by the orchestrator.
2. For SAFE commands, execute directly and report the output.
3. For RISKY or MODERATE commands, the approval gate will automatically intercept
   the tool call — you do NOT need to ask separately. Simply proceed with the call.
4. After each tool execution, report the output clearly and concisely.
5. Do NOT modify the arguments passed to you. Execute exactly what is requested.
"""


async def _build_shell_approval_handler(gate: Any) -> Any:
    """Build an async handler for the ask_user policy hook."""
    async def handler(tool_name: str, args: dict[str, Any]) -> bool:
        risk_report = classify_risk(tool_name, args)
        decision = await gate.handle(
            agent_name="Shell Utility Agent",
            tool_name=tool_name,
            args=args,
            risk_report=risk_report,
        )
        return decision.approved
    return handler


class ShellUtilityAgent:
    """
    Shell Utility Agent with approval-gated command execution.
    """

    def __init__(self, approval_gate: Any) -> None:
        self._gate = approval_gate
        self._config = None  # built lazily after handler is ready

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute a tool call. Risky calls are intercepted by the approval gate.
        """
        handler = await _build_shell_approval_handler(self._gate)

        # Build policies: deny all by default, allow safe reads,
        # ask_user for any run_command invocation
        policies = [
            deny("*"),
            allow("read_file_contents"),
            allow("list_directory"),
            allow("list_processes"),
            ask_user("run_shell_command", handler=handler),
        ]

        config = LocalAgentConfig(
            system_instructions=_SHELL_AGENT_SYSTEM_PROMPT,
            capabilities=CapabilitiesConfig(),
            tools=SHELL_TOOLS,
            policies=policies,
        )

        prompt = (
            f"Execute this tool call:\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {args}\n\n"
            f"Run the tool and report its output."
        )

        try:
            async with Agent(config) as agent:
                # Stream tool call events for audit visibility
                response = await agent.chat(prompt)
                async for call in response.tool_calls:
                    pass  # tool_calls stream — consumed for side-effects (logging)
                return await response.text()
        except Exception as exc:
            return f"[Shell Agent Error] {type(exc).__name__}: {exc}"

"""
shell_utility.py
----------------
Shell Utility Agent — executes shell commands with approval gating.
"""

from typing import Any

from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.hooks.policy import allow, deny, ask_user

from tools.shell_tools import SHELL_TOOLS
from core.risk_classifier import classify_risk, RiskLevel


_SYSTEM_PROMPT = """\
You are the Shell Utility Agent.

Execute shell-related tools exactly as requested.
Do not modify tool arguments.
Report only the tool output.
"""


async def _build_shell_approval_handler(gate: Any) -> Any:
    async def handler(tool_call: Any) -> bool:
        tool_name = tool_call.name
        args = tool_call.args or {}

        risk_report = classify_risk(tool_name, args)

        if risk_report.level == RiskLevel.SAFE:
            return True

        decision = await gate.handle(
            agent_name="Shell Utility Agent",
            tool_name=tool_name,
            args=args,
            risk_report=risk_report,
        )

        return decision.approved

    return handler


def _needs_shell_approval(args: dict[str, Any]) -> bool:
    risk_report = classify_risk("run_shell_command", args or {})
    return risk_report.level != RiskLevel.SAFE


class ShellUtilityAgent:
    def __init__(self, approval_gate: Any) -> None:
        self._gate = approval_gate

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        handler = await _build_shell_approval_handler(self._gate)

        policies = [
            allow("read_file_contents"),
            allow("list_directory"),
            allow("list_processes"),

            ask_user(
                "run_shell_command",
                handler=handler,
                when=_needs_shell_approval,
            ),

            allow("run_shell_command"),
            deny("*"),
        ]

        config = LocalAgentConfig(
            system_instructions=_SYSTEM_PROMPT,
            capabilities=CapabilitiesConfig(),
            tools=SHELL_TOOLS,
            policies=policies,
        )

        prompt = (
            "Execute exactly this tool call.\n\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {args}\n\n"
            "Return only the tool output."
        )

        try:
            async with Agent(config) as agent:
                response = await agent.chat(prompt)
                return await response.text()

        except Exception as exc:
            return f"[Shell Agent Error] {type(exc).__name__}: {exc}"

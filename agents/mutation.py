"""
mutation.py
-----------
Mutation Agent — handles file edits, external API calls, database changes,
config updates, and other system-state-mutating operations.

Every write operation is gated by the human approval gate via the
`ask_user` policy hook.
"""

from __future__ import annotations

from typing import Any

from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.hooks.policy import deny, allow, ask_user

from tools.mutation_tools import MUTATION_TOOLS
from core.risk_classifier import classify_risk

_MUTATION_AGENT_SYSTEM_PROMPT = """\
You are the EscrowGuard Mutation Agent — a specialized sub-agent responsible for
modifying system state: editing files, writing files, calling external APIs,
updating config files, and deleting files.

You have access to the following tools:
- edit_file(path, old_content, new_content): Replace text in a file.
- write_file(path, content, overwrite): Write/create a file.
- call_external_api(url, method, payload, headers): Make HTTP requests.
- update_config(path, key, value): Update a config file key.
- delete_file(path): Delete a file permanently.

Safety rules you MUST follow:
1. ALWAYS use the exact tool arguments given to you by the orchestrator.
2. ALL mutation tools require human approval — the gate will intercept them automatically.
3. After each tool execution, report the result clearly and concisely.
4. If an operation fails, report the exact error without attempting to retry automatically.
5. Do NOT modify the arguments passed to you.
"""


async def _build_mutation_approval_handler(gate: Any) -> Any:
    """Build an async handler for the ask_user policy hooks."""
    async def handler(tool_name: str, args: dict[str, Any]) -> bool:
        risk_report = classify_risk(tool_name, args)
        decision = await gate.handle(
            agent_name="Mutation Agent",
            tool_name=tool_name,
            args=args,
            risk_report=risk_report,
        )
        return decision.approved
    return handler


class MutationAgent:
    """
    Mutation Agent with approval-gated state-modification tools.
    Every tool in MUTATION_TOOLS requires explicit human approval.
    """

    def __init__(self, approval_gate: Any) -> None:
        self._gate = approval_gate

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute a mutation tool call. All calls are intercepted by the approval gate.
        """
        handler = await _build_mutation_approval_handler(self._gate)

        # All mutation tools require ask_user approval
        policies = [
            deny("*"),
            ask_user("edit_file",         handler=handler),
            ask_user("write_file",        handler=handler),
            ask_user("call_external_api", handler=handler),
            ask_user("update_config",     handler=handler),
            ask_user("delete_file",       handler=handler),
        ]

        config = LocalAgentConfig(
            system_instructions=_MUTATION_AGENT_SYSTEM_PROMPT,
            capabilities=CapabilitiesConfig(),
            tools=MUTATION_TOOLS,
            policies=policies,
        )

        prompt = (
            f"Execute this mutation tool call:\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {args}\n\n"
            f"Run the tool and report its result."
        )

        try:
            async with Agent(config) as agent:
                response = await agent.chat(prompt)
                return await response.text()
        except Exception as exc:
            return f"[Mutation Agent Error] {type(exc).__name__}: {exc}"

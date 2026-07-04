"""
planner.py
----------
Planner Agent — decomposes a user task into a structured execution plan
where each step is tagged with a risk level and the appropriate agent to execute it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks.policy import deny, allow

_PLANNER_SYSTEM_PROMPT = """\
You are the EscrowGuard Planner Agent — the first stage of a safe, approval-gated
multi-agent developer workflow.

Your job is to receive a developer task and decompose it into a sequence of atomic steps.
For each step, you must classify:
  - "agent": which sub-agent should execute it ("shell_utility" | "mutation" | "reviewer")
  - "risk_level": "safe" | "moderate" | "risky"
  - "description": a plain-language description of the step
  - "tool": the specific tool to call (e.g., "run_shell_command", "write_file", "edit_file", "call_external_api")
  - "args": a dict of tool arguments

Risk classification rules:
  - "safe": read-only operations (list files, read file, list processes, etc.)
  - "moderate": operations that change state but are easily reversible (move file, kill process, git push)
  - "risky": destructive or irreversible operations (rm -rf, write to .env, call external API, deploy, db mutation)

CRITICAL: Always respond with a valid JSON array of step objects, no markdown fences, no extra text.

Schema for each step:
{
  "step": <integer, 1-indexed>,
  "description": "<what this step does>",
  "agent": "shell_utility" | "mutation" | "reviewer",
  "risk_level": "safe" | "moderate" | "risky",
  "tool": "<tool name>",
  "args": { <tool arguments> }
}

Example response for "clean build artifacts and redeploy":
[
  {
    "step": 1,
    "description": "List current build directory contents",
    "agent": "shell_utility",
    "risk_level": "safe",
    "tool": "run_shell_command",
    "args": {"command": "ls -la ./build"}
  },
  {
    "step": 2,
    "description": "Delete all build artifacts recursively",
    "agent": "shell_utility",
    "risk_level": "risky",
    "tool": "run_shell_command",
    "args": {"command": "rm -rf ./build"}
  },
  {
    "step": 3,
    "description": "Update deployment config version tag",
    "agent": "mutation",
    "risk_level": "risky",
    "tool": "update_config",
    "args": {"path": "deploy.json", "key": "version", "value": "2.1.0"}
  }
]
"""

_PLANNER_POLICIES = [
    deny("*"),
    allow("view_file"),
]


@dataclass
class PlanStep:
    step: int
    description: str
    agent: str          # "shell_utility" | "mutation" | "reviewer"
    risk_level: str     # "safe" | "moderate" | "risky"
    tool: str
    args: dict[str, Any]

    @property
    def is_risky(self) -> bool:
        return self.risk_level in ("risky", "moderate")

    def __str__(self) -> str:
        risk_icon = {"safe": "🟢", "moderate": "🟡", "risky": "🔴"}.get(self.risk_level, "⚪")
        return f"Step {self.step} [{risk_icon} {self.risk_level.upper()}] ({self.agent}) — {self.description}"


class PlannerAgent:
    """
    Wraps the Planner sub-agent. Provides the `plan()` method
    that returns a list of PlanStep objects.
    """

    def __init__(self) -> None:
        self._config = LocalAgentConfig(
            system_instructions=_PLANNER_SYSTEM_PROMPT,
            policies=_PLANNER_POLICIES,
        )

    async def plan(self, user_request: str) -> list[PlanStep]:
        """
        Decompose a user request into a list of PlanStep objects.
        """
        try:
            async with Agent(self._config) as agent:
                response = await agent.chat(
                    f"Decompose this developer task into steps:\n\n{user_request}"
                )
                raw = await response.text()
                return self._parse_plan(raw)
        except Exception as exc:
            raise RuntimeError(f"Planner Agent failed: {exc}") from exc

    def _parse_plan(self, raw: str) -> list[PlanStep]:
        """Parse the JSON plan output and return PlanStep objects."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:-1])

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Planner returned invalid JSON: {exc}\nRaw: {cleaned[:500]}") from exc

        if not isinstance(data, list):
            raise ValueError(f"Planner response is not a list: {type(data)}")

        steps = []
        for item in data:
            steps.append(
                PlanStep(
                    step=int(item.get("step", len(steps) + 1)),
                    description=item.get("description", ""),
                    agent=item.get("agent", "shell_utility"),
                    risk_level=item.get("risk_level", "safe"),
                    tool=item.get("tool", "run_shell_command"),
                    args=item.get("args", {}),
                )
            )
        return steps

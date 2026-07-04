"""
reviewer.py
-----------
Reviewer Agent — analyzes proposed risky actions and produces a structured
risk assessment with a recommendation: approve, reject, or revise.

This agent runs in read-only mode and its sole job is analysis.
"""

from __future__ import annotations

import json
from typing import Any

from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks.policy import deny, allow

_REVIEWER_SYSTEM_PROMPT = """\
You are the EscrowGuard Reviewer Agent — a security-focused AI analyst embedded in
a multi-agent developer workflow.

Your ONLY job is to analyze proposed tool calls and produce a structured risk assessment.

When given a tool name and its arguments, you must:
1. Identify what the tool does and what side effects it may have.
2. Classify the risk level: LOW, MEDIUM, or HIGH.
3. Explain the risk clearly in 2-4 sentences (plain language, no jargon).
4. Give a recommendation: APPROVE, REJECT, or REVISE.
5. Provide a confidence score from 0.0 to 1.0.
6. If recommending REVISE, suggest the safer alternative.

CRITICAL: Always respond with a valid JSON object in exactly this schema:
{
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "explanation": "<2-4 sentence plain-language risk explanation>",
  "recommendation": "APPROVE" | "REJECT" | "REVISE",
  "confidence": <float 0.0-1.0>,
  "safer_alternative": "<string, only if recommendation is REVISE, else null>"
}

Do NOT include any text outside the JSON. Do NOT use markdown fences.
"""

_REVIEWER_POLICIES = [
    deny("*"),          # Reviewer never executes any tools
    allow("view_file"), # It may read files for context
]


class ReviewerAgent:
    """
    Wraps the Reviewer sub-agent. Provides the `analyze()` method
    used by the ApprovalGate.
    """

    def __init__(self) -> None:
        self._config = LocalAgentConfig(
            system_instructions=_REVIEWER_SYSTEM_PROMPT,
            policies=_REVIEWER_POLICIES,
            # No CapabilitiesConfig — read-only is the default
        )

    async def analyze(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Ask the Reviewer Agent to analyze a proposed tool call.

        Returns a human-readable string (parsed from the JSON response)
        suitable for display in the approval gate panel.
        """
        prompt = (
            f"Analyze the following proposed tool call:\n\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(args, indent=2, default=str)}\n\n"
            "Respond with the JSON risk assessment as instructed."
        )

        try:
            async with Agent(self._config) as agent:
                response = await agent.chat(prompt)
                raw = await response.text()
                return self._format_analysis(raw)
        except Exception as exc:
            return f"Reviewer analysis failed: {exc}"

    def _format_analysis(self, raw_json: str) -> str:
        """Parse the JSON and format it as a human-readable string."""
        try:
            # Strip markdown fences if the model wraps them
            cleaned = raw_json.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[1:-1])

            data = json.loads(cleaned)
            risk = data.get("risk_level", "UNKNOWN")
            explanation = data.get("explanation", "")
            rec = data.get("recommendation", "UNKNOWN")
            confidence = data.get("confidence", 0.0)
            safer = data.get("safer_alternative")

            lines = [
                f"Risk: {risk}  |  Recommendation: {rec}  |  Confidence: {confidence:.0%}",
                f"",
                explanation,
            ]
            if safer:
                lines += ["", f"Safer alternative: {safer}"]
            return "\n".join(lines)
        except (json.JSONDecodeError, KeyError):
            # If JSON parsing fails, return raw text
            return raw_json[:600]

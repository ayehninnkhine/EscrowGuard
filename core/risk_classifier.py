"""
risk_classifier.py
------------------
Heuristic risk classifier for EscrowGuard.
Determines whether a proposed tool call is safe, moderate, or risky
without needing an LLM — used as a fast pre-filter before the Reviewer Agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    RISKY = "risky"


# ── Shell command destructive pattern groups ─────────────────────────────────

_RISKY_SHELL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-[rf]", re.IGNORECASE),             # rm -rf / rm -r
    re.compile(r"\brmdir\b", re.IGNORECASE),                 # rmdir
    re.compile(r"\bdd\b.*if=", re.IGNORECASE),               # dd if=... (disk write)
    re.compile(r"\bmkfs\b", re.IGNORECASE),                  # format filesystem
    re.compile(r"\bsudo\b", re.IGNORECASE),                  # privilege escalation
    re.compile(r"curl\s+.*\|\s*(?:bash|sh|zsh)", re.IGNORECASE),   # curl | sh
    re.compile(r"wget\s+.*\|\s*(?:bash|sh|zsh)", re.IGNORECASE),   # wget | sh
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),             # force-kill process
    re.compile(r"\bchmod\s+777\b", re.IGNORECASE),           # world-writable
    re.compile(r"\bchown\b.*root", re.IGNORECASE),           # chown to root
    re.compile(r"\bdrop\s+(?:table|database)\b", re.IGNORECASE),  # SQL drop
    re.compile(r"\btruncate\s+table\b", re.IGNORECASE),      # SQL truncate
    re.compile(r">\s*/dev/", re.IGNORECASE),                 # write to device
    re.compile(r"\bformat\b.*(?:c:|d:|/dev/)", re.IGNORECASE),    # format drive
    re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b", re.IGNORECASE),
]

_MODERATE_SHELL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bkill\b", re.IGNORECASE),                  # kill (without -9)
    re.compile(r"\bmv\b", re.IGNORECASE),                    # move files
    re.compile(r"\bchmod\b", re.IGNORECASE),                 # any chmod
    re.compile(r"\bapt\b|\byum\b|\bbrew\b", re.IGNORECASE), # package managers
    re.compile(r"\bgit\s+(?:push|reset|rebase|force)\b", re.IGNORECASE),
    re.compile(r"\bdocker\s+(?:rm|rmi|prune)\b", re.IGNORECASE),
]

# ── Mutation tool risk rules ─────────────────────────────────────────────────

_RISKY_MUTATION_TOOLS = {
    "write_file",
    "edit_file",
    "call_external_api",
    "update_config",
}

_MODERATE_MUTATION_TOOLS = {
    "read_file",  # reading is safe; mutations of sensitive paths are moderate
}

_SENSITIVE_PATH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\.env", re.IGNORECASE),
    re.compile(r"(?:private|secret|credential|password|token)", re.IGNORECASE),
    re.compile(r"(?:/etc/|/usr/|/var/|/bin/|/sbin/)", re.IGNORECASE),
    re.compile(r"(?:~/.ssh|~/.aws|~/.gcp)", re.IGNORECASE),
    re.compile(r"(?:id_rsa|id_ed25519|\.pem|\.key)", re.IGNORECASE),
    re.compile(r"(?:database\.yml|settings\.py|config\.json|secrets\.yaml)", re.IGNORECASE),
]


@dataclass
class RiskReport:
    level: RiskLevel
    matched_patterns: list[str]
    reason: str

    @property
    def is_risky(self) -> bool:
        return self.level == RiskLevel.RISKY

    @property
    def requires_approval(self) -> bool:
        return self.level in (RiskLevel.RISKY, RiskLevel.MODERATE)


def classify_risk(tool_name: str, args: dict[str, Any]) -> RiskReport:
    """
    Classifies the risk of a tool invocation based on tool name and arguments.

    Returns a RiskReport with the risk level and the reason.
    """
    matched: list[str] = []

    # ── Shell command classification ─────────────────────────────────────────
    if tool_name == "run_shell_command":
        command: str = args.get("command", "")

        for pattern in _RISKY_SHELL_PATTERNS:
            if pattern.search(command):
                matched.append(pattern.pattern)

        if matched:
            return RiskReport(
                level=RiskLevel.RISKY,
                matched_patterns=matched,
                reason=f"Command matches {len(matched)} destructive pattern(s): {', '.join(matched[:3])}",
            )

        for pattern in _MODERATE_SHELL_PATTERNS:
            if pattern.search(command):
                matched.append(pattern.pattern)

        if matched:
            return RiskReport(
                level=RiskLevel.MODERATE,
                matched_patterns=matched,
                reason=f"Command matches {len(matched)} moderate-risk pattern(s)",
            )

        return RiskReport(
            level=RiskLevel.SAFE,
            matched_patterns=[],
            reason="No destructive patterns detected in shell command.",
        )

    # ── Mutation tool classification ─────────────────────────────────────────
    if tool_name in _RISKY_MUTATION_TOOLS:
        # Check if the target path is sensitive
        path = args.get("path", "") or args.get("url", "")
        for pattern in _SENSITIVE_PATH_PATTERNS:
            if pattern.search(str(path)):
                matched.append(pattern.pattern)

        reason = (
            f"Mutation tool '{tool_name}' targeting sensitive path: {path}"
            if matched
            else f"Mutation tool '{tool_name}' modifies system state"
        )
        return RiskReport(
            level=RiskLevel.RISKY,
            matched_patterns=matched,
            reason=reason,
        )

    # ── Default: safe ────────────────────────────────────────────────────────
    return RiskReport(
        level=RiskLevel.SAFE,
        matched_patterns=[],
        reason=f"Tool '{tool_name}' is read-only or low-risk.",
    )

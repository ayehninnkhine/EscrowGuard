"""
audit_log.py
------------
Append-only, structured audit trail for EscrowGuard.
Every tool call, approval decision, and agent action is recorded
to `escrowguard_audit.jsonl` in the working directory.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    AUTO_APPROVED = "auto_approved"  # safe actions that skip the gate
    SKIPPED = "skipped"


@dataclass
class AuditEntry:
    timestamp: str
    event_type: str           # "tool_call", "approval_decision", "agent_plan", "error"
    agent: str
    tool_name: str | None
    args: dict[str, Any] | None
    risk_level: str | None
    decision: str | None
    decision_reason: str | None
    reviewer_summary: str | None
    result: str | None
    session_id: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class AuditLog:
    """
    Thread-safe, append-only audit log.
    Writes JSONL to `escrowguard_audit.jsonl` in the project root.
    """

    def __init__(self, session_id: str, log_path: str | None = None) -> None:
        self.session_id = session_id
        self._log_path = Path(log_path or "escrowguard_audit.jsonl")
        self._lock = asyncio.Lock()
        self._entries: list[AuditEntry] = []

    async def record_tool_call(
        self,
        agent: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        result: str | None = None,
    ) -> None:
        entry = AuditEntry(
            timestamp=_now(),
            event_type="tool_call",
            agent=agent,
            tool_name=tool_name,
            args=args,
            risk_level=risk_level,
            decision=None,
            decision_reason=None,
            reviewer_summary=None,
            result=result,
            session_id=self.session_id,
        )
        await self._append(entry)

    async def record_decision(
        self,
        agent: str,
        tool_name: str,
        args: dict[str, Any],
        risk_level: str,
        decision: Decision,
        reason: str,
        reviewer_summary: str | None = None,
    ) -> None:
        entry = AuditEntry(
            timestamp=_now(),
            event_type="approval_decision",
            agent=agent,
            tool_name=tool_name,
            args=args,
            risk_level=risk_level,
            decision=decision.value,
            decision_reason=reason,
            reviewer_summary=reviewer_summary,
            result=None,
            session_id=self.session_id,
        )
        await self._append(entry)

    async def record_plan(
        self,
        agent: str,
        plan_summary: str,
    ) -> None:
        entry = AuditEntry(
            timestamp=_now(),
            event_type="agent_plan",
            agent=agent,
            tool_name=None,
            args=None,
            risk_level=None,
            decision=None,
            decision_reason=None,
            reviewer_summary=None,
            result=plan_summary,
            session_id=self.session_id,
        )
        await self._append(entry)

    async def record_error(self, agent: str, error: str) -> None:
        entry = AuditEntry(
            timestamp=_now(),
            event_type="error",
            agent=agent,
            tool_name=None,
            args=None,
            risk_level=None,
            decision=None,
            decision_reason=None,
            reviewer_summary=None,
            result=error,
            session_id=self.session_id,
        )
        await self._append(entry)

    async def _append(self, entry: AuditEntry) -> None:
        async with self._lock:
            self._entries.append(entry)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(entry.to_json() + "\n")

    def get_entries(self) -> list[AuditEntry]:
        return list(self._entries)

    def print_summary(self) -> None:
        """Print a compact decision summary to stdout."""
        total = len(self._entries)
        decisions = [e for e in self._entries if e.event_type == "approval_decision"]
        approved = sum(1 for d in decisions if d.decision in ("approved", "auto_approved"))
        rejected = sum(1 for d in decisions if d.decision == "rejected")
        revised = sum(1 for d in decisions if d.decision == "revised")
        print(f"\n📋 Audit Summary — {total} events, {len(decisions)} decisions")
        print(f"   ✅ Approved: {approved}  ❌ Rejected: {rejected}  ✏️  Revised: {revised}")
        print(f"   📁 Full log: {self._log_path.resolve()}\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

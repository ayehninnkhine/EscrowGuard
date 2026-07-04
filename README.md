# EscrowGuard

# EscrowGuard: Building Approval-Gated AI Agents with the Google Antigravity SDK

## How to stop your AI agent from accidentally running `rm -rf` on your production server

---

> *"Autonomous AI agents are powerful. Autonomous AI agents with no kill switch are terrifying."*

We're entering an era where AI agents don't just suggest code — they execute it. They run shell commands, modify files, call external APIs, and mutate production databases. The productivity gains are enormous. So is the blast radius when something goes wrong.

This article is about a system called **EscrowGuard**: an approval-gated multi-agent developer workflow that ensures no risky action — no destructive shell command, no production config change, no API call — executes without a human explicitly signing off. Think of it as an escrow service for your shell.

We'll cover:
- **The theory**: What is the Google Antigravity SDK? What are sub-agents? What is human-in-the-loop?
- **The system**: How EscrowGuard's four-agent architecture works
- **The tutorial**: A complete step-by-step guide to building it yourself

Let's dive in.

---

## Part 1: The Theory

### 1.1 What Is the Google Antigravity SDK?

The **Google Antigravity SDK** (`google-antigravity`) is a Python SDK for building AI agents powered by Gemini. It abstracts the full agentic lifecycle — the loop of *think → use tool → observe → repeat* — behind a clean, async Python API.

Here's the mental model:

```
┌──────────────────────────────────────────────────────────┐
│                     Agent (SDK Layer)                    │
│                                                          │
│   LocalAgentConfig ──► system_instructions               │
│                    ──► tools = [my_python_functions]     │
│                    ──► policies = [deny, allow, ask_user]│
│                    ──► capabilities = CapabilitiesConfig  │
│                                                          │
│   async with Agent(config) as agent:                     │
│       response = await agent.chat("Do something")        │
│       async for token in response: ...  # streaming      │
│       async for call in response.tool_calls: ...         │
└──────────────────────────────────────────────────────────┘
```

The three things that make it special for production workflows are:

**1. Custom tools registration.** Any Python function with a docstring becomes an agent-callable tool:

```python
def run_shell_command(command: str) -> str:
    """Run a shell command and return its output."""
    return subprocess.run(command, shell=True, capture_output=True, text=True).stdout

config = LocalAgentConfig(tools=[run_shell_command])
```

**2. The policy system.** A declarative layer that controls which tools the agent can call — and what happens when it tries:

```python
from google.antigravity.hooks.policy import deny, allow, ask_user

policies = [
    deny("*"),                    # block everything by default
    allow("read_file"),           # allow this specific tool
    ask_user("run_command", handler=my_handler),  # pause and ask human
]
```

**3. The `ask_user` hook.** This is the secret ingredient. When the agent attempts to call a tool gated by `ask_user`, execution pauses, your handler is called with the tool name and arguments, and the tool only fires if your handler returns `True`. This is how you build a human approval gate.

---

### 1.2 What Are Sub-Agents?

A **sub-agent** is an AI agent scoped to a single responsibility, operating within a larger orchestrated system. Instead of one monolithic agent that does everything, you break the problem into specialist agents:

```
                    USER REQUEST
                         │
                         ▼
              ┌──────────────────┐
              │   ORCHESTRATOR   │
              │  (coordinator)   │
              └────────┬─────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ Planner  │  │  Shell   │  │ Mutation │
   │  Agent   │  │  Agent   │  │  Agent   │
   └──────────┘  └──────────┘  └──────────┘
                       │             │
                       └──────┬──────┘
                              ▼
                       ┌──────────┐
                       │ Reviewer │
                       │  Agent   │
                       └──────────┘
```

Each sub-agent gets:
- Its own **system prompt** scoped to its job
- Its own **set of tools** it can call
- Its own **policy set** defining what it can and cannot do
- Its own **capability level** (read-only vs. write-enabled)

This creates a **least-privilege architecture**: the Planner Agent can't execute commands, the Reviewer Agent can't write files, and the Shell Agent can't touch mutation tools. Each agent is sandboxed to exactly what it needs.

In the Antigravity SDK, each sub-agent is simply another `Agent` instance with its own `LocalAgentConfig`:

```python
# Planner: read-only, produces JSON plans
planner_config = LocalAgentConfig(
    system_instructions="You decompose tasks into step plans...",
    policies=[deny("*"), allow("view_file")],
)

# Shell agent: can execute commands, but risky ones are gated
shell_config = LocalAgentConfig(
    system_instructions="You execute shell commands...",
    capabilities=CapabilitiesConfig(),  # write-capable
    tools=[run_shell_command, list_processes],
    policies=[deny("*"), allow("list_processes"), ask_user("run_shell_command", handler=gate)],
)
```

---

### 1.3 What Is Human-in-the-Loop (HITL)?

**Human-in-the-loop (HITL)** is a design pattern where humans are embedded in an automated decision pipeline at critical checkpoints — not to review everything (that would defeat the purpose of automation), but to review the things that matter.

The classic HITL spectrum looks like this:

```
Full Automation ◄────────────────────────────────► Full Manual

  Agent acts        Agent acts,      Agent proposes,     Human does
  autonomously      logs for later   human approves      everything
                    review           before execution
                                          ▲
                                     EscrowGuard
```

EscrowGuard sits at the **"Agent proposes, human approves"** position — the sweet spot for developer workflows where automation saves time but irreversible actions need a human signature.

Good HITL design follows three principles:

1. **Risk-proportional gates**: Don't gate everything — only gate actions proportional to their risk. `ls -la` should execute silently. `rm -rf ./production` should require explicit approval with a detailed explanation.

2. **Informed decisions**: The human shouldn't just be shown "approve or reject?". They should see exactly what will happen, a risk explanation, and a recommendation. Blind approval is not safer than full automation.

3. **Audit trails**: Every gate decision — approve, reject, revise — must be logged with a timestamp, the agent that proposed it, the exact arguments, and the reviewer's analysis. Accountability matters.

---

## Part 2: The EscrowGuard System

### 2.1 Architecture Overview

EscrowGuard implements four specialized sub-agents coordinated by an orchestrator:

```
User: "Delete all .log files and restart the server"
                    │
                    ▼
          ┌─────────────────┐
          │ Planner Agent   │ → JSON step plan:
          │                 │   Step 1: list .log files   [🟢 SAFE]
          │  deny("*")      │   Step 2: delete .log files [🔴 RISKY]
          │  allow("view")  │   Step 3: restart server    [🔴 RISKY]
          └────────┬────────┘
                   │
          ┌────────▼────────┐
          │  Orchestrator   │ routes each step
          └────┬───────┬────┘
               │       │
    ┌──────────▼──┐  ┌──▼───────────┐
    │Shell Utility│  │  Mutation    │
    │   Agent     │  │  Agent       │
    │             │  │              │
    │ ask_user(   │  │ ask_user(    │
    │  run_cmd)   │  │  write_file) │
    └──────┬──────┘  └──────┬───────┘
           │                │
           └────────┬───────┘
                    │  RISKY step detected
                    ▼
          ╔═══════════════════════════╗
          ║  APPROVAL GATE            ║
          ║                           ║
          ║  Reviewer Agent analyzes  ║
          ║  → Risk: 🔴 HIGH          ║
          ║  → Rec: REJECT            ║
          ║  → Confidence: 94%        ║
          ║                           ║
          ║  [A]pprove [R]eject [V]   ║
          ╚═══════════════════════════╝
```

### 2.2 The Four Agents

| Agent | System Prompt Focus | Capabilities | Policy |
|---|---|---|---|
| **Planner** | Decompose tasks into JSON step plans with risk tags | Read-only | `deny("*"), allow("view_file")` |
| **Shell Utility** | Execute shell commands safely | Write (`CapabilitiesConfig`) | `ask_user("run_shell_command", ...)` |
| **Mutation** | File edits, API calls, config changes | Write (`CapabilitiesConfig`) | `ask_user(...)` on every write tool |
| **Reviewer** | Risk analysis in structured JSON format | Read-only | `deny("*"), allow("view_file")` |

### 2.3 The Approval Gate Flow

When a risky tool call fires, here's exactly what happens at the SDK level:

```python
# Inside shell_utility.py — the ask_user handler
async def handler(tool_name: str, args: dict) -> bool:
    risk_report = classify_risk(tool_name, args)   # heuristic pre-check
    decision = await gate.handle(                   # show approval UI
        agent_name="Shell Utility Agent",
        tool_name=tool_name,
        args=args,
        risk_report=risk_report,
    )
    return decision.approved                        # True = execute, False = cancel

# The policy hooks this handler into the agent's tool execution
policies = [
    deny("*"),
    allow("list_directory"),
    ask_user("run_shell_command", handler=handler),  # ← fires before execution
]
```

The SDK guarantees that `run_shell_command` cannot execute until `handler` returns `True`. If it returns `False`, the tool call is cancelled and the agent's next turn receives a "tool call denied" signal.

---

## Part 3: Step-by-Step Tutorial

Now let's build it. By the end of this section, you'll have a working EscrowGuard system running locally.

### Prerequisites

- Python 3.11+
- A Gemini API key (get one at [aistudio.google.com](https://aistudio.google.com))

---

### Step 1: Project Setup

Create the project directory structure:

```bash
mkdir -p escrowguard/agents escrowguard/core escrowguard/tools
cd escrowguard

touch agents/__init__.py core/__init__.py tools/__init__.py
```

Install dependencies:

```bash
pip install google-antigravity rich httpx

# Fix protobuf version conflict (required for google-antigravity 0.1.5)
pip install --upgrade protobuf
```

Set your API key:

```bash
export GEMINI_API_KEY="your_api_key_here"
```

Your final structure will look like this:

```
escrowguard/
├── main.py
├── orchestrator.py
├── requirements.txt
├── agents/
│   ├── planner.py
│   ├── reviewer.py
│   ├── shell_utility.py
│   └── mutation.py
├── core/
│   ├── risk_classifier.py
│   ├── approval_gate.py
│   └── audit_log.py
└── tools/
    ├── shell_tools.py
    └── mutation_tools.py
```

---

### Step 2: The Risk Classifier (`core/risk_classifier.py`)

Before anything reaches the LLM-powered Reviewer Agent, we run a fast heuristic pre-filter using regex patterns. This catches obvious destructive patterns instantly without a network call.

```python
# core/risk_classifier.py
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    RISKY = "risky"


# Patterns that are immediately classified as RISKY
_RISKY_SHELL_PATTERNS = [
    re.compile(r"\brm\s+-[rf]", re.IGNORECASE),       # rm -rf
    re.compile(r"\bdd\b.*if=", re.IGNORECASE),         # disk dump
    re.compile(r"\bmkfs\b", re.IGNORECASE),            # format filesystem
    re.compile(r"\bsudo\b", re.IGNORECASE),            # privilege escalation
    re.compile(r"curl\s+.*\|\s*(?:bash|sh)", re.IGNORECASE),  # curl | sh
    re.compile(r"\bkill\s+-9\b", re.IGNORECASE),       # force kill
    re.compile(r"\bchmod\s+777\b", re.IGNORECASE),     # world-writable
    re.compile(r"\bdrop\s+(?:table|database)\b", re.IGNORECASE),  # SQL drop
    re.compile(r"\bshutdown\b|\breboot\b", re.IGNORECASE),
]

# All mutation tools are inherently risky (they change state)
_RISKY_MUTATION_TOOLS = {
    "write_file", "edit_file", "call_external_api",
    "update_config", "delete_file",
}

# Sensitive paths that escalate risk
_SENSITIVE_PATH_PATTERNS = [
    re.compile(r"\.env", re.IGNORECASE),
    re.compile(r"(?:private|secret|credential|password|token)", re.IGNORECASE),
    re.compile(r"(?:/etc/|/usr/|/bin/)", re.IGNORECASE),
    re.compile(r"(?:id_rsa|\.pem|\.key)", re.IGNORECASE),
]


@dataclass
class RiskReport:
    level: RiskLevel
    matched_patterns: list[str]
    reason: str

    @property
    def requires_approval(self) -> bool:
        return self.level in (RiskLevel.RISKY, RiskLevel.MODERATE)


def classify_risk(tool_name: str, args: dict[str, Any]) -> RiskReport:
    matched = []

    if tool_name == "run_shell_command":
        command = args.get("command", "")
        for pattern in _RISKY_SHELL_PATTERNS:
            if pattern.search(command):
                matched.append(pattern.pattern)
        if matched:
            return RiskReport(RiskLevel.RISKY, matched,
                f"Command matches {len(matched)} destructive pattern(s)")
        return RiskReport(RiskLevel.SAFE, [], "No destructive patterns detected.")

    if tool_name in _RISKY_MUTATION_TOOLS:
        path = args.get("path", "") or args.get("url", "")
        for pattern in _SENSITIVE_PATH_PATTERNS:
            if pattern.search(str(path)):
                matched.append(pattern.pattern)
        return RiskReport(RiskLevel.RISKY, matched,
            f"Mutation tool '{tool_name}' modifies system state")

    return RiskReport(RiskLevel.SAFE, [], f"Tool '{tool_name}' is read-only.")
```

**Key design decision**: Classification is two-tier. The fast regex filter catches the obvious cases; the Reviewer Agent (an LLM) handles the nuanced ones. This keeps latency low for simple commands while giving complex mutations a full LLM analysis.

---

### Step 3: The Audit Log (`core/audit_log.py`)

Every decision must be traceable. The audit log writes append-only JSONL to disk:

```python
# core/audit_log.py
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class Decision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    AUTO_APPROVED = "auto_approved"


@dataclass
class AuditEntry:
    timestamp: str
    event_type: str       # "tool_call", "approval_decision", "agent_plan", "error"
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
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._log_path = Path("escrowguard_audit.jsonl")
        self._lock = asyncio.Lock()

    async def record_decision(
        self, agent: str, tool_name: str, args: dict,
        risk_level: str, decision: Decision,
        reason: str, reviewer_summary: str | None = None,
    ) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="approval_decision",
            agent=agent, tool_name=tool_name, args=args,
            risk_level=risk_level, decision=decision.value,
            decision_reason=reason, reviewer_summary=reviewer_summary,
            result=None, session_id=self.session_id,
        )
        async with self._lock:
            with self._log_path.open("a") as fh:
                fh.write(entry.to_json() + "\n")
```

The `asyncio.Lock` is important — multiple agents can write concurrently, and without it you'd get interleaved JSON lines that corrupt the log.

---

### Step 4: The Shell and Mutation Tools

These are plain Python functions that the Antigravity SDK wraps as agent-callable tools. The SDK uses your function's name, type hints, and docstring to build the tool description.

```python
# tools/shell_tools.py
import subprocess
import os


def run_shell_command(command: str) -> str:
    """Run a shell command and return its combined stdout + stderr output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        parts = []
        if result.stdout:
            parts.append(result.stdout.strip())
        if result.stderr:
            parts.append(f"[stderr] {result.stderr.strip()}")
        return "\n".join(parts) or f"[exit code: {result.returncode}]"
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 30 seconds."
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def list_directory(path: str = ".") -> str:
    """List the contents of a directory."""
    entries = os.listdir(path)
    lines = []
    for name in sorted(entries):
        full = os.path.join(path, name)
        icon = "📁" if os.path.isdir(full) else "📄"
        lines.append(f"{icon}  {name}")
    return f"Directory: {os.path.abspath(path)}\n" + "\n".join(lines)


SHELL_TOOLS = [run_shell_command, list_directory]
```

```python
# tools/mutation_tools.py
import json
from pathlib import Path
from typing import Any


def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """Write content to a file. Creates the file if it does not exist."""
    file_path = Path(path)
    if file_path.exists() and not overwrite:
        return f"[error] File already exists: {path}. Set overwrite=True."
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"✅ Wrote {len(content):,} chars to {path}."


def edit_file(path: str, old_content: str, new_content: str) -> str:
    """Edit a file by replacing a specific block of text."""
    file_path = Path(path)
    if not file_path.exists():
        return f"[error] File not found: {path}"
    current = file_path.read_text(encoding="utf-8")
    if old_content not in current:
        return f"[error] Target text not found in {path}."
    updated = current.replace(old_content, new_content, 1)
    file_path.write_text(updated, encoding="utf-8")
    return f"✅ Edited {path}."


def update_config(path: str, key: str, value: str) -> str:
    """Update a key in a JSON config file."""
    file_path = Path(path)
    data = json.loads(file_path.read_text())
    keys = key.split(".")
    node = data
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    file_path.write_text(json.dumps(data, indent=2))
    return f"✅ Updated '{key}' in {path}."


MUTATION_TOOLS = [write_file, edit_file, update_config]
```

---

### Step 5: The Four Agents

#### 5a. Reviewer Agent (`agents/reviewer.py`)

The Reviewer is read-only — its only job is to analyze proposed actions and return structured risk assessments. The strict JSON output format is enforced in the system prompt:

```python
# agents/reviewer.py
import json
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks.policy import deny, allow

_SYSTEM_PROMPT = """
You are the EscrowGuard Reviewer Agent — a security analyst.
Analyze proposed tool calls and return ONLY a valid JSON object:
{
  "risk_level": "LOW" | "MEDIUM" | "HIGH",
  "explanation": "<2-4 sentence risk explanation>",
  "recommendation": "APPROVE" | "REJECT" | "REVISE",
  "confidence": <float 0.0-1.0>,
  "safer_alternative": "<string or null>"
}
No markdown. No extra text. Only JSON.
"""

class ReviewerAgent:
    def __init__(self):
        self._config = LocalAgentConfig(
            system_instructions=_SYSTEM_PROMPT,
            policies=[deny("*"), allow("view_file")],
            # No CapabilitiesConfig — read-only by default
        )

    async def analyze(self, tool_name: str, args: dict) -> str:
        prompt = (
            f"Analyze this proposed tool call:\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {json.dumps(args, indent=2, default=str)}\n"
            f"Return the JSON risk assessment."
        )
        async with Agent(self._config) as agent:
            response = await agent.chat(prompt)
            raw = await response.text()
            return self._format(raw)

    def _format(self, raw: str) -> str:
        try:
            data = json.loads(raw.strip().strip("```json").strip("```"))
            return (
                f"Risk: {data['risk_level']}  |  "
                f"Recommendation: {data['recommendation']}  |  "
                f"Confidence: {data['confidence']:.0%}\n\n"
                f"{data['explanation']}"
            )
        except Exception:
            return raw[:400]
```

#### 5b. Planner Agent (`agents/planner.py`)

The Planner decomposes natural language into a JSON step plan. Each step carries a `risk_level` and designates which sub-agent should execute it:

```python
# agents/planner.py
import json
from dataclasses import dataclass
from typing import Any
from google.antigravity import Agent, LocalAgentConfig
from google.antigravity.hooks.policy import deny, allow

_SYSTEM_PROMPT = """
You are the EscrowGuard Planner Agent.
Decompose developer tasks into a JSON array of steps. Each step:
{
  "step": <int>,
  "description": "<what this does>",
  "agent": "shell_utility" | "mutation",
  "risk_level": "safe" | "moderate" | "risky",
  "tool": "<tool name>",
  "args": { <arguments> }
}

Risk rules:
- safe: read-only (ls, cat, ps)
- moderate: reversible state changes (mv, kill, git push)
- risky: irreversible or destructive (rm -rf, write .env, call API, deploy)

Respond ONLY with the JSON array. No markdown. No explanation.
"""

@dataclass
class PlanStep:
    step: int
    description: str
    agent: str
    risk_level: str
    tool: str
    args: dict[str, Any]

class PlannerAgent:
    def __init__(self):
        self._config = LocalAgentConfig(
            system_instructions=_SYSTEM_PROMPT,
            policies=[deny("*"), allow("view_file")],
        )

    async def plan(self, user_request: str) -> list[PlanStep]:
        async with Agent(self._config) as agent:
            response = await agent.chat(
                f"Decompose this task:\n\n{user_request}"
            )
            raw = await response.text()
            data = json.loads(raw.strip().strip("```json").strip("```"))
            return [PlanStep(**item) for item in data]
```

#### 5c. Shell Utility Agent (`agents/shell_utility.py`)

This is where the `ask_user` policy hook does its magic. The handler is called by the SDK before `run_shell_command` can execute:

```python
# agents/shell_utility.py
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.hooks.policy import deny, allow, ask_user
from tools.shell_tools import SHELL_TOOLS
from core.risk_classifier import classify_risk


class ShellUtilityAgent:
    def __init__(self, approval_gate):
        self._gate = approval_gate

    async def execute(self, tool_name: str, args: dict) -> str:
        # Build the approval handler for this tool call
        async def handler(tool: str, call_args: dict) -> bool:
            risk = classify_risk(tool, call_args)
            decision = await self._gate.handle(
                agent_name="Shell Utility Agent",
                tool_name=tool,
                args=call_args,
                risk_report=risk,
            )
            return decision.approved

        # Policy: deny all, allow safe reads, gate run_shell_command
        policies = [
            deny("*"),
            allow("list_directory"),
            allow("list_processes"),
            ask_user("run_shell_command", handler=handler),  # ← THE GATE
        ]

        config = LocalAgentConfig(
            system_instructions="Execute shell commands. Use exact args provided.",
            capabilities=CapabilitiesConfig(),
            tools=SHELL_TOOLS,
            policies=policies,
        )

        async with Agent(config) as agent:
            response = await agent.chat(
                f"Execute: Tool={tool_name}, Args={args}. Report the output."
            )
            return await response.text()
```

#### 5d. Mutation Agent (`agents/mutation.py`)

Every single write tool gets its own `ask_user` gate:

```python
# agents/mutation.py
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
from google.antigravity.hooks.policy import deny, ask_user
from tools.mutation_tools import MUTATION_TOOLS
from core.risk_classifier import classify_risk


class MutationAgent:
    def __init__(self, approval_gate):
        self._gate = approval_gate

    async def execute(self, tool_name: str, args: dict) -> str:
        async def handler(tool: str, call_args: dict) -> bool:
            risk = classify_risk(tool, call_args)
            decision = await self._gate.handle(
                agent_name="Mutation Agent",
                tool_name=tool,
                args=call_args,
                risk_report=risk,
            )
            return decision.approved

        # Every mutation tool is gated
        policies = [
            deny("*"),
            ask_user("write_file",        handler=handler),
            ask_user("edit_file",         handler=handler),
            ask_user("update_config",     handler=handler),
            ask_user("call_external_api", handler=handler),
            ask_user("delete_file",       handler=handler),
        ]

        config = LocalAgentConfig(
            system_instructions="Execute file/config mutations. Use exact args provided.",
            capabilities=CapabilitiesConfig(),
            tools=MUTATION_TOOLS,
            policies=policies,
        )

        async with Agent(config) as agent:
            response = await agent.chat(
                f"Execute: Tool={tool_name}, Args={args}. Report the result."
            )
            return await response.text()
```

---

### Step 6: The Approval Gate (`core/approval_gate.py`)

This is the HITL interface — it renders the terminal UI, queries the Reviewer, and waits for the human:

```python
# core/approval_gate.py
import asyncio
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from core.audit_log import AuditLog, Decision
from core.risk_classifier import RiskReport, RiskLevel, classify_risk

console = Console()

_COLORS = {RiskLevel.SAFE: "green", RiskLevel.MODERATE: "yellow", RiskLevel.RISKY: "red"}
_ICONS  = {RiskLevel.SAFE: "🟢",    RiskLevel.MODERATE: "🟡",     RiskLevel.RISKY: "🔴"}


@dataclass
class ApprovalDecision:
    approved: bool
    revised_args: dict | None = None
    reason: str = ""


class ApprovalGate:
    def __init__(self, audit_log: AuditLog, reviewer_agent=None):
        self._log = audit_log
        self._reviewer = reviewer_agent

    async def handle(self, agent_name, tool_name, args, risk_report=None):
        if risk_report is None:
            risk_report = classify_risk(tool_name, args)

        # Step 1: Get Reviewer analysis
        reviewer_text = "Reviewer unavailable — heuristic analysis only."
        if self._reviewer:
            reviewer_text = await self._reviewer.analyze(tool_name, args)

        # Step 2: Render the approval panel
        color = _COLORS[risk_report.level]
        icon  = _ICONS[risk_report.level]
        args_display = "\n".join(f"  {k}: {v}" for k, v in args.items())

        body = (
            f"[bold]Agent:[/bold]      [cyan]{agent_name}[/cyan]\n"
            f"[bold]Tool:[/bold]       [yellow]{tool_name}[/yellow]\n"
            f"[bold]Arguments:[/bold]\n{args_display}\n\n"
            f"[bold]Risk:[/bold]       [{color}]{icon} {risk_report.level.value.upper()}[/{color}]\n"
            f"[bold]Reason:[/bold]     {risk_report.reason}\n\n"
            f"[bold]Reviewer:[/bold]\n[italic]{reviewer_text}[/italic]\n\n"
            "[dim](A)pprove  (R)eject  (V)Revise  (Q)uit[/dim]"
        )
        console.print(Panel(
            body,
            title="[bold white on red]  ⚠  ESCROWGUARD APPROVAL GATE  ⚠  [/bold white on red]",
            border_style=color,
            box=box.DOUBLE_EDGE,
        ))

        # Step 3: Prompt for decision
        while True:
            choice = await asyncio.to_thread(
                Prompt.ask, "Decision", choices=["a", "r", "v", "q"], default="r"
            )
            if choice == "a":
                console.print("[bold green]✅ APPROVED[/bold green]")
                await self._log.record_decision(
                    agent_name, tool_name, args,
                    risk_report.level.value, Decision.APPROVED,
                    "Human approved.", reviewer_text
                )
                return ApprovalDecision(approved=True)

            elif choice == "r":
                console.print("[bold red]❌ REJECTED[/bold red]")
                await self._log.record_decision(
                    agent_name, tool_name, args,
                    risk_report.level.value, Decision.REJECTED,
                    "Human rejected.", reviewer_text
                )
                return ApprovalDecision(approved=False)

            elif choice == "v":
                # Collect revised arguments interactively
                revised = {}
                for k, v in args.items():
                    new = await asyncio.to_thread(Prompt.ask, f"  {k}", default=str(v))
                    revised[k] = new
                await self._log.record_decision(
                    agent_name, tool_name, revised,
                    risk_report.level.value, Decision.REVISED,
                    "Human revised.", reviewer_text
                )
                return ApprovalDecision(approved=True, revised_args=revised)

            elif choice == "q":
                raise SystemExit(0)
```

---

### Step 7: The Orchestrator (`orchestrator.py`)

The orchestrator ties everything together. It runs the planner, routes each step, and delegates risky steps through the gate:

```python
# orchestrator.py
import asyncio
import uuid
from rich.console import Console
from rich.rule import Rule
from rich import box
from rich.panel import Panel

from agents.planner import PlannerAgent
from agents.reviewer import ReviewerAgent
from agents.shell_utility import ShellUtilityAgent
from agents.mutation import MutationAgent
from core.approval_gate import ApprovalGate
from core.audit_log import AuditLog

console = Console()


class EscrowGuardOrchestrator:
    def __init__(self):
        self._audit    = AuditLog(session_id=str(uuid.uuid4())[:8])
        self._reviewer = ReviewerAgent()
        self._gate     = ApprovalGate(audit_log=self._audit, reviewer_agent=self._reviewer)
        self._planner  = PlannerAgent()
        self._shell    = ShellUtilityAgent(approval_gate=self._gate)
        self._mutation = MutationAgent(approval_gate=self._gate)

    async def run(self, user_request: str):
        console.print(Rule("[bold blue]🧠 Planning[/bold blue]"))
        plan = await self._planner.plan(user_request)

        console.print(f"\n[green]✅ {len(plan)} step(s) planned[/green]\n")
        for step in plan:
            color = {"safe": "green", "moderate": "yellow", "risky": "red"}[step.risk_level]
            console.print(f"  [{color}]●[/{color}] Step {step.step}: {step.description}")

        console.print()
        console.print(Rule("[bold blue]⚡ Execution[/bold blue]"))

        for step in plan:
            console.print(f"\n[bold]Step {step.step}:[/bold] {step.description}")
            try:
                if step.agent == "shell_utility":
                    result = await self._shell.execute(step.tool, step.args)
                elif step.agent == "mutation":
                    result = await self._mutation.execute(step.tool, step.args)
                else:
                    result = "Unknown agent."

                console.print(Panel(result.strip(), border_style="dim", box=box.SIMPLE))
            except SystemExit:
                raise
            except Exception as exc:
                console.print(f"[red]❌ {exc}[/red]")

        self._audit.print_summary()
```

---

### Step 8: The Entry Point (`main.py`)

```python
# main.py
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from rich.console import Console
from rich.prompt import Prompt
from rich.rule import Rule
from orchestrator import EscrowGuardOrchestrator

console = Console()

_BANNER = """
[bold cyan]
  ███████╗███████╗ ██████╗██████╗  ██████╗ ██╗    ██╗ ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗
  ██╔════╝██╔════╝██╔════╝██╔══██╗██╔═══██╗██║    ██║██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗
  ███████╗██║     ██║     ██████╔╝██║   ██║██║ █╗ ██║██║  ███╗██║   ██║███████║██████╔╝██║  ██║
  ╚════██║██║     ██║     ██╔══██╗██║   ██║██║███╗██║██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║
  ███████║╚══════╝╚██████╗██║  ██║╚██████╔╝╚███╔███╔╝╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝
  ╚══════╝ ╚═════╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝  ╚══╝╚══╝  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝
[/bold cyan]
"""

async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        console.print("[red]❌ Set GEMINI_API_KEY before running.[/red]")
        sys.exit(1)

    console.print(_BANNER)
    orchestrator = EscrowGuardOrchestrator()

    while True:
        console.print(Rule("[dim]New Task[/dim]"))
        try:
            task = await asyncio.to_thread(
                Prompt.ask, "\n[bold cyan]🔐 EscrowGuard[/bold cyan] [dim]>[/dim]"
            )
        except (EOFError, KeyboardInterrupt):
            break

        if task.strip().lower() in ("quit", "exit", "q"):
            break

        await orchestrator.run(task.strip())

    console.print("[white]👋 Goodbye![/white]")


if __name__ == "__main__":
    asyncio.run(main())
```

---

### Step 9: Running EscrowGuard

```bash
export GEMINI_API_KEY="your_api_key_here"
python main.py
```

Try these example tasks:

**Safe task** (no gate triggered):
```
🔐 EscrowGuard > List all Python files in the current directory
```
→ `list_directory` runs immediately. No gate.

**Risky task** (gate appears):
```
🔐 EscrowGuard > Delete all .log files in /tmp and restart nginx
```
→ Planner produces a 3-step plan. Steps 2 and 3 trigger the gate.

**Mutation task** (gate appears):
```
🔐 EscrowGuard > Update the DEBUG flag to false in .env and deploy
```
→ Both `update_config` and any deployment steps are gated.

---

### Step 10: Inspecting the Audit Trail

After running a session, open `escrowguard_audit.jsonl`:

```bash
cat escrowguard_audit.jsonl | python -m json.tool
```

You'll see entries like:

```json
{
  "timestamp": "2026-07-04T08:15:00Z",
  "event_type": "approval_decision",
  "agent": "shell_utility",
  "tool_name": "run_shell_command",
  "args": {"command": "rm -rf ./build"},
  "risk_level": "risky",
  "decision": "approved",
  "decision_reason": "Human approved via approval gate.",
  "reviewer_summary": "Risk: HIGH | Recommendation: REJECT | 94%\nRecursively deletes the build directory...",
  "session_id": "a1b2c3d4"
}
```

This gives you a complete, tamper-evident record of every AI-proposed action and every human decision.

---

## Part 4: What We Learned

### The Policy System Is the Key Abstraction

The most powerful insight from building EscrowGuard is that the Antigravity SDK's policy system (`deny`, `allow`, `ask_user`) separates **what an agent can do** from **what it's allowed to do**. You write the agent's capabilities (its tools) independently from its authorization layer (its policies). This clean separation is what makes it easy to build safe agentic systems.

### Sub-Agents Aren't Just for Parallelism

Multi-agent architectures are often sold as a way to parallelize work. But EscrowGuard shows another crucial benefit: **trust isolation**. The Reviewer Agent literally cannot modify a file. The Planner Agent literally cannot run a shell command. These aren't just conventions in the code — they're enforced at the SDK policy layer. You can reason about each agent's blast radius independently.

### HITL Isn't a Tax on Automation — It's a Feature

The instinct is to minimize human gates because they slow things down. But in developer workflows, the right gate at the right moment is exactly what makes AI tooling trustworthy enough to put near production systems. The goal isn't zero human involvement — it's *proportional* human involvement. EscrowGuard's heuristic pre-filter means safe commands never hit the gate; only genuinely risky ones do.

---

## Conclusion

EscrowGuard demonstrates that building production-safe AI agent systems doesn't require a massive custom framework. The Google Antigravity SDK provides the primitives you need — `ask_user` policies, custom tools, per-agent capability configuration — and the real work is in designing your agents' responsibilities, risk classifications, and audit trails thoughtfully.

The complete source code is available at the project directory referenced throughout this article. The architecture is deliberately simple so you can extend it: add a database mutation agent, a Kubernetes operator agent, or a GitHub PR agent — and the approval gate will catch anything dangerous automatically.

**The most important engineering decision you'll make with AI agents isn't which model to use. It's where you put the human.**

---

*Built with the Google Antigravity SDK (v0.1.5) · Python 3.12 · Rich · httpx*

---

**Tags:** `#AI` `#Agents` `#MultiAgent` `#HumanInTheLoop` `#Python` `#DevTools` `#AIEngineering` `#Automation`

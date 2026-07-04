# 🔐 EscrowGuard

> **Approval-Gated Shell and System Mutation Agent**  
> A multi-agent developer workflow built on the [Google Antigravity SDK](https://github.com/google-antigravity/antigravity-sdk-python).


## Overview

EscrowGuard is a four-agent system where sub-agents can propose any action, but **risky or state-mutating actions are paused at a human approval gate** before execution. Think of it as an escrow service for your shell and filesystem — nothing dangerous executes without your explicit sign-off.

```
User Request
     │
     ▼
┌─────────────┐     Execution Plan (JSON)
│   Planner   │ ──────────────────────────────────────────────┐
│   Agent     │  (safe/moderate/risky steps, per-agent routes) │
└─────────────┘                                                │
                                                               ▼
          ┌────────────────────────────────────────────────────┐
          │           ORCHESTRATOR                             │
          │   routes each step to the correct sub-agent        │
          └────┬──────────────────────┬────────────────────────┘
               │                     │
       ┌───────▼──────┐    ┌──────────▼──────┐
       │ Shell Utility│    │    Mutation     │
       │   Agent      │    │    Agent        │
       │  (ask_user)  │    │  (ask_user)     │
       └───────┬──────┘    └──────────┬──────┘
               │                     │
               └──────────┬──────────┘
                    RISKY? │
                           ▼
               ┌───────────────────────┐
               │   APPROVAL GATE       │   ← Human approves / rejects / revises
               │                       │
               │  Reviewer Agent       │   ← Explains risk, recommends action
               └───────────────────────┘
```


## Architecture

### Agents

| Agent | Role | Capabilities | Policy |
|---|---|---|---|
| **Planner** | Decomposes tasks into JSON step plans with risk tags | Read-only | `deny("*"), allow("view_file")` |
| **Shell Utility** | Executes shell commands | Write (CapabilitiesConfig) | `ask_user("run_shell_command", ...)` |
| **Mutation** | File edits, API calls, config changes | Write (CapabilitiesConfig) | `ask_user(...)` on every write tool |
| **Reviewer** | Analyzes risk, recommends approve/reject/revise | Read-only | `deny("*"), allow("view_file")` |

### SDK Primitives Used

- **`Agent` + `LocalAgentConfig`** — each sub-agent is an independent `Agent` instance with its own system prompt
- **Custom `tools=[]`** — Python functions (`run_shell_command`, `edit_file`, etc.) registered as SDK tools
- **`ask_user` policy hook** — the core approval gate mechanism; pauses execution until the human decides
- **`deny` / `allow` policies** — least-privilege baseline per agent
- **`CapabilitiesConfig`** — write capabilities granted only to Shell and Mutation agents
- **`response.tool_calls`** — streamed for real-time audit logging


## Project Structure

```
escrowguard/
├── main.py                   # Entry point — interactive CLI
├── orchestrator.py           # Orchestrator — coordinates all agents
├── requirements.txt
├── agents/
│   ├── planner.py            # Planner Agent
│   ├── shell_utility.py      # Shell Utility Agent
│   ├── mutation.py           # Mutation Agent
│   └── reviewer.py           # Reviewer Agent
├── core/
│   ├── approval_gate.py      # Human approval gate (rich terminal UI)
│   ├── risk_classifier.py    # Heuristic risk pre-filter
│   └── audit_log.py          # Append-only JSONL audit trail
└── tools/
    ├── shell_tools.py         # Shell tool functions
    └── mutation_tools.py      # Mutation tool functions
```


## Quick Start

### 1. Create virtual environment

```bash
conda create -n antigravity python=3.12 -y

conda activate antigravity

python -m pip install --upgrade pip

```

### 2. Set your API key

```bash
export GEMINI_API_KEY="your_api_key_here"
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run EscrowGuard

```bash
python main.py
```

## Example Session

```
🔐 EscrowGuard > Clean build artifacts and update version in package.json to 2.0.0

🧠 Planning Phase
✅ Plan ready — 3 step(s)
  🟢 Step 1  List current build directory contents  → shell_utility / run_shell_command
  🔴 Step 2  Delete all build artifacts recursively  → shell_utility / run_shell_command
  🔴 Step 3  Update version key in package.json  → mutation / update_config

⚡ Execution Phase

🟢 Step 1: List current build directory contents
  ╔══════════════════ Step 1 Result ════════════════════╗
  │  dist/  bundle.js  index.html  ...                  │
  ╚═════════════════════════════════════════════════════╝

🔴 Step 2: Delete all build artifacts recursively
╔══════════════════════════════════════════════════════╗
║         ⚠  ESCROWGUARD APPROVAL GATE  ⚠              ║
╠══════════════════════════════════════════════════════╣
║  Agent:    Shell Utility Agent                       ║
║  Tool:     run_shell_command                         ║
║  Command:  rm -rf ./build                            ║
╠══════════════════════════════════════════════════════╣
║  Risk: 🔴 HIGH | Recommendation: REJECT | 94%        ║
║  Recursively deletes the build directory. Cannot     ║
║  be undone without a backup.                         ║
╠══════════════════════════════════════════════════════╣
║  [A]pprove  [R]eject  [V]Revise  [Q]uit              ║
╚══════════════════════════════════════════════════════╝

Your decision [a/r/v/q]: a
✅ Action APPROVED by human.
```

## Approval Gate Options

| Key | Action |
|-----|--------|
| `A` | **Approve** — execute the action as proposed |
| `R` | **Reject** — skip the action, continue to next step |
| `V` | **Revise** — edit arguments interactively, then approve |
| `Q` | **Quit** — end the session immediately |


## Audit Trail

Every action and decision is logged to `escrowguard_audit.jsonl`:

```json
{"timestamp":"2026-07-04T08:15:00Z","event_type":"approval_decision","agent":"shell_utility","tool_name":"run_shell_command","args":{"command":"rm -rf ./build"},"risk_level":"risky","decision":"approved","decision_reason":"Human approved via approval gate.","reviewer_summary":"Risk: HIGH | Recommendation: REJECT | 94%\nRecursively deletes the build directory...","session_id":"a1b2c3d4"}
```

## Risk Classification

The `RiskClassifier` uses pattern matching to pre-screen tool calls before sending them to the Reviewer Agent:

| Pattern | Level |
|---|---|
| `rm -rf`, `dd if=`, `mkfs`, `curl \| sh` | 🔴 Risky |
| `sudo`, `chmod 777`, `DROP TABLE` | 🔴 Risky |
| `kill`, `mv`, `chmod`, `git push --force` | 🟡 Moderate |
| All mutation tools (`write_file`, `edit_file`, etc.) | 🔴 Risky |
| Read-only tools (`list_directory`, `read_file`) | 🟢 Safe |

## Acknowledgement

Google cloud credits are supported for this project. #AgenticArchitectSprint #Antigravity

"""
shell_tools.py
--------------
Custom tools registered with the Shell Utility Agent.
These are plain Python functions — the Antigravity SDK wraps them as agent-callable tools.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys


def run_shell_command(command: str) -> str:
    """
    Run a shell command and return its combined stdout + stderr output.
    Maximum execution time is 30 seconds.

    Args:
        command: The shell command to execute.

    Returns:
        The combined stdout and stderr of the command, or an error message.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output_parts: list[str] = []
        if result.stdout:
            output_parts.append(result.stdout.strip())
        if result.stderr:
            output_parts.append(f"[stderr] {result.stderr.strip()}")
        if not output_parts:
            output_parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(output_parts)
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 30 seconds."
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def list_processes() -> str:
    """
    List currently running processes.

    Returns:
        A formatted table of running processes (PID, CPU%, MEM%, command).
    """
    cmd = "ps aux --sort=-%cpu" if sys.platform != "darwin" else "ps aux -r"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        lines = result.stdout.strip().splitlines()
        # Limit to top 20 processes for readability
        return "\n".join(lines[:21])
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def read_file_contents(path: str) -> str:
    """
    Read and return the contents of a file (read-only).

    Args:
        path: Absolute or relative path to the file.

    Returns:
        File contents as a string, or an error message.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        if len(content) > 8000:
            return content[:8000] + f"\n\n[... truncated — file has {len(content)} total chars]"
        return content
    except FileNotFoundError:
        return f"[error] File not found: {path}"
    except PermissionError:
        return f"[error] Permission denied: {path}"
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def list_directory(path: str = ".") -> str:
    """
    List the contents of a directory.

    Args:
        path: Directory path to list. Defaults to current directory.

    Returns:
        A formatted directory listing.
    """
    try:
        entries = os.listdir(path)
        lines = []
        for name in sorted(entries):
            full = os.path.join(path, name)
            if os.path.isdir(full):
                lines.append(f"📁  {name}/")
            else:
                size = os.path.getsize(full)
                lines.append(f"📄  {name}  ({size:,} bytes)")
        return f"Directory: {os.path.abspath(path)}\n" + "\n".join(lines)
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


# Expose all tools as a list for easy registration with LocalAgentConfig
SHELL_TOOLS = [
    run_shell_command,
    list_processes,
    read_file_contents,
    list_directory,
]

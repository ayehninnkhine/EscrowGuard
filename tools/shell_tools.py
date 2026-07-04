import os
import subprocess


def run_shell_command(command: str) -> str:
    """Run a shell command and return its output."""

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return f"Command failed with exit code {result.returncode}\n{stderr}"

        return stdout or "Command completed successfully with no output."

    except Exception as exc:
        return f"Shell command failed: {type(exc).__name__}: {exc}"


def list_processes() -> str:
    """List running processes."""

    return run_shell_command("ps aux")


def read_file_contents(path: str) -> str:
    """Read a file and return its contents."""

    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read()

    except Exception as exc:
        return f"Failed to read file: {type(exc).__name__}: {exc}"


def list_directory(path: str = ".") -> str:
    """List directory contents."""

    try:
        return "\n".join(os.listdir(path))

    except Exception as exc:
        return f"Failed to list directory: {type(exc).__name__}: {exc}"


SHELL_TOOLS = [
    run_shell_command,
    list_processes,
    read_file_contents,
    list_directory,
]

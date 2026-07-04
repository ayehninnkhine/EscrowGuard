"""
mutation_tools.py
-----------------
Custom tools registered with the Mutation Agent.
All of these tools modify system state — they are gated by the approval system.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def edit_file(path: str, old_content: str, new_content: str) -> str:
    """
    Edit a file by replacing a specific block of text.

    Args:
        path: Path to the file to edit.
        old_content: The exact text to find and replace.
        new_content: The replacement text.

    Returns:
        A success or error message.
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"[error] File not found: {path}"
        current = file_path.read_text(encoding="utf-8")
        if old_content not in current:
            return f"[error] Target text not found in {path}. No changes made."
        updated = current.replace(old_content, new_content, 1)
        file_path.write_text(updated, encoding="utf-8")
        return f"✅ Successfully edited {path} — replaced {len(old_content)} chars with {len(new_content)} chars."
    except PermissionError:
        return f"[error] Permission denied: {path}"
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def write_file(path: str, content: str, overwrite: bool = False) -> str:
    """
    Write content to a file. Creates the file if it does not exist.

    Args:
        path: Target file path.
        content: Content to write.
        overwrite: If False (default), fails if the file already exists.

    Returns:
        A success or error message.
    """
    try:
        file_path = Path(path)
        if file_path.exists() and not overwrite:
            return (
                f"[error] File already exists: {path}. "
                "Set overwrite=True to replace it."
            )
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"✅ Successfully wrote {len(content):,} chars to {path}."
    except PermissionError:
        return f"[error] Permission denied: {path}"
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def call_external_api(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """
    Make an HTTP request to an external API endpoint.

    Args:
        url: The full URL to call.
        method: HTTP method (GET, POST, PUT, DELETE, PATCH).
        payload: Optional JSON body for POST/PUT/PATCH.
        headers: Optional additional HTTP headers.

    Returns:
        The API response body as a string.
    """
    try:
        import httpx  # imported lazily so the module loads even if httpx isn't installed

        method = method.upper()
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        with httpx.Client(timeout=15.0) as client:
            if method == "GET":
                resp = client.get(url, headers=req_headers)
            elif method == "POST":
                resp = client.post(url, json=payload or {}, headers=req_headers)
            elif method == "PUT":
                resp = client.put(url, json=payload or {}, headers=req_headers)
            elif method == "PATCH":
                resp = client.patch(url, json=payload or {}, headers=req_headers)
            elif method == "DELETE":
                resp = client.delete(url, headers=req_headers)
            else:
                return f"[error] Unsupported HTTP method: {method}"

            body = resp.text[:4000]  # cap response length
            return f"[HTTP {resp.status_code}]\n{body}"
    except ImportError:
        return "[error] httpx is not installed. Run: pip install httpx"
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def update_config(path: str, key: str, value: str) -> str:
    """
    Update a key in a JSON or simple KEY=VALUE config file.

    Args:
        path: Path to the config file.
        key: The key to update (dot-notation supported for JSON, e.g. "server.port").
        value: The new value as a string.

    Returns:
        A success or error message.
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"[error] Config file not found: {path}"

        suffix = file_path.suffix.lower()
        content = file_path.read_text(encoding="utf-8")

        if suffix == ".json":
            data = json.loads(content)
            # Support dot notation for nested keys
            keys = key.split(".")
            node = data
            for k in keys[:-1]:
                if k not in node:
                    node[k] = {}
                node = node[k]
            # Attempt type coercion
            try:
                node[keys[-1]] = json.loads(value)
            except json.JSONDecodeError:
                node[keys[-1]] = value
            file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return f"✅ Updated JSON key '{key}' in {path}."

        else:
            # KEY=VALUE format (.env, .ini style)
            pattern = re.compile(rf"^({re.escape(key)}\s*=\s*).*$", re.MULTILINE)
            if pattern.search(content):
                updated = pattern.sub(rf"\g<1>{value}", content)
            else:
                updated = content.rstrip() + f"\n{key}={value}\n"
            file_path.write_text(updated, encoding="utf-8")
            return f"✅ Updated key '{key}' in {path}."

    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


def delete_file(path: str) -> str:
    """
    Delete a file permanently.

    Args:
        path: Path to the file to delete.

    Returns:
        A success or error message.
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"[error] File not found: {path}"
        file_path.unlink()
        return f"✅ Deleted {path}."
    except PermissionError:
        return f"[error] Permission denied: {path}"
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


# Expose all tools as a list for easy registration with LocalAgentConfig
MUTATION_TOOLS = [
    edit_file,
    write_file,
    call_external_api,
    update_config,
    delete_file,
]

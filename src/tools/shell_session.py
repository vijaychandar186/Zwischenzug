"""
Persistent shell sessions — named shells that persist across tool calls.

Provides session lifecycle (create, list, close), command execution within
named sessions, and background process support.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.shell_session")

MAX_OUTPUT = 50_000
DEFAULT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Shell session state
# ---------------------------------------------------------------------------

@dataclass
class ShellSession:
    """A persistent shell subprocess."""
    name: str
    process: asyncio.subprocess.Process | None = None
    cwd: str = "."
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    _output_buffer: list[str] = field(default_factory=list)
    _reader_task: asyncio.Task | None = field(default=None, repr=False)


# Session-scoped shell pools
_SHELL_POOLS: dict[str, dict[str, ShellSession]] = {}


def _get_shells(session_id: str) -> dict[str, ShellSession]:
    if session_id not in _SHELL_POOLS:
        _SHELL_POOLS[session_id] = {}
    return _SHELL_POOLS[session_id]


# ---------------------------------------------------------------------------
# ShellCreateTool
# ---------------------------------------------------------------------------

class ShellCreateTool(Tool):
    """Create a persistent named shell session."""

    @property
    def name(self) -> str:
        return "shell_create"

    @property
    def description(self) -> str:
        return (
            "Create a new persistent shell session. The shell stays alive "
            "across tool calls, so environment variables, directory changes, "
            "and background processes persist. Use shell_exec to run commands "
            "in the session."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name for this shell session (e.g., 'build', 'test').",
                },
            },
            "required": ["session_name"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        session_name: str = kwargs["session_name"].strip()

        if not session_name:
            return ToolOutput.error("session_name cannot be empty.")

        shells = _get_shells(ctx.session_id)

        if session_name in shells:
            return ToolOutput.error(
                f"Shell '{session_name}' already exists. Close it first or use a different name."
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                "/bin/bash --norc --noprofile",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=ctx.cwd,
                env={**os.environ, "PS1": ""},
            )
        except Exception as exc:
            return ToolOutput.error(f"Failed to create shell: {exc}")

        session = ShellSession(name=session_name, process=proc, cwd=ctx.cwd)
        shells[session_name] = session

        return ToolOutput.success(
            f"Shell '{session_name}' created (PID {proc.pid}).\n"
            f"Use shell_exec(session_name='{session_name}', command='...') to run commands."
        )


# ---------------------------------------------------------------------------
# ShellExecTool
# ---------------------------------------------------------------------------

class ShellExecTool(Tool):
    """Execute a command in a persistent shell session."""

    @property
    def name(self) -> str:
        return "shell_exec"

    @property
    def description(self) -> str:
        return (
            "Execute a command in an existing persistent shell session. "
            "The shell retains state (env vars, cwd) between calls. "
            "Output is captured and returned."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name of the shell session to use.",
                },
                "command": {
                    "type": "string",
                    "description": "The command to execute in the shell.",
                },
                "timeout": {
                    "type": "number",
                    "description": f"Timeout in seconds (default {int(DEFAULT_TIMEOUT)}).",
                },
            },
            "required": ["session_name", "command"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        session_name: str = kwargs["session_name"]
        command: str = kwargs["command"]
        timeout: float = float(kwargs.get("timeout") or DEFAULT_TIMEOUT)

        shells = _get_shells(ctx.session_id)
        shell = shells.get(session_name)

        if shell is None:
            return ToolOutput.error(
                f"Shell '{session_name}' not found. Create it with shell_create first."
            )

        proc = shell.process
        if proc is None or proc.returncode is not None:
            return ToolOutput.error(
                f"Shell '{session_name}' has exited. Create a new one."
            )

        # Use a sentinel to detect end of output
        sentinel = f"__ZWIS_SENTINEL_{id(command)}__"
        full_cmd = f"{command}\necho {sentinel}\n"

        try:
            proc.stdin.write(full_cmd.encode())
            await proc.stdin.drain()
        except Exception as exc:
            return ToolOutput.error(f"Failed to send command: {exc}")

        # Read output until sentinel
        output_lines: list[str] = []
        try:
            async def _read_until_sentinel():
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    if sentinel in decoded:
                        break
                    output_lines.append(decoded)

            await asyncio.wait_for(_read_until_sentinel(), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolOutput.error(
                f"Command timed out after {timeout}s in shell '{session_name}'."
            )

        shell.last_used = time.time()
        text = "".join(output_lines)

        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + f"\n...[truncated, {len(text)} chars total]"

        return ToolOutput.success(text or "(no output)")


# ---------------------------------------------------------------------------
# ShellListTool
# ---------------------------------------------------------------------------

class ShellListTool(Tool):
    """List all active shell sessions."""

    @property
    def name(self) -> str:
        return "shell_list"

    @property
    def description(self) -> str:
        return "List all persistent shell sessions and their status."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        shells = _get_shells(ctx.session_id)

        if not shells:
            return ToolOutput.success("No active shell sessions.")

        lines = [f"Shell sessions ({len(shells)}):"]
        for s in shells.values():
            alive = s.process is not None and s.process.returncode is None
            status = "alive" if alive else "exited"
            elapsed = time.time() - s.created_at
            lines.append(
                f"  {s.name}  [{status}]  "
                f"PID {s.process.pid if s.process else '?'}  "
                f"{elapsed:.0f}s old"
            )
        return ToolOutput.success("\n".join(lines))


# ---------------------------------------------------------------------------
# ShellCloseTool
# ---------------------------------------------------------------------------

class ShellCloseTool(Tool):
    """Close a persistent shell session."""

    @property
    def name(self) -> str:
        return "shell_close"

    @property
    def description(self) -> str:
        return "Close and terminate a persistent shell session."

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name of the shell session to close.",
                },
            },
            "required": ["session_name"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        session_name: str = kwargs["session_name"]
        shells = _get_shells(ctx.session_id)
        shell = shells.get(session_name)

        if shell is None:
            return ToolOutput.error(f"Shell '{session_name}' not found.")

        if shell.process and shell.process.returncode is None:
            try:
                shell.process.terminate()
                await asyncio.wait_for(shell.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                shell.process.kill()
            except Exception:
                pass

        del shells[session_name]
        return ToolOutput.success(f"Shell '{session_name}' closed.")

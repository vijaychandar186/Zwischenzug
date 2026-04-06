"""BashTool — execute shell commands via subprocess."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from . import Tool, ToolContext, ToolOutput

DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT = 50_000  # chars


class BashTool(Tool):
    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return stdout + stderr. "
            "Use for running scripts, build commands, git operations, and system tasks. "
            f"Default timeout: {int(DEFAULT_TIMEOUT)}s. Output capped at {MAX_OUTPUT} chars."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "number",
                    "description": f"Timeout in seconds (default {int(DEFAULT_TIMEOUT)}).",
                },
            },
            "required": ["command"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        command: str = kwargs["command"]
        timeout: float = float(kwargs.get("timeout") or DEFAULT_TIMEOUT)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=ctx.cwd,
                env={**os.environ},
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                return ToolOutput.error(f"Command timed out after {timeout}s: {command!r}")

            text = stdout.decode("utf-8", errors="replace")
            if len(text) > MAX_OUTPUT:
                text = text[:MAX_OUTPUT] + f"\n...[truncated, {len(text)} chars total]"

            if proc.returncode != 0:
                return ToolOutput(
                    content=text or f"(exit code {proc.returncode})",
                    is_error=True,
                )
            return ToolOutput.success(text or "(no output)")

        except FileNotFoundError:
            return ToolOutput.error(f"Shell not found. Cannot execute: {command!r}")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Unexpected error running command: {exc}")

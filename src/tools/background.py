"""
Background task control — run, monitor, and manage background tasks.

Provides task lifecycle management: start in background, check status,
retrieve output, and stop running tasks.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.background")

MAX_OUTPUT = 50_000


class TaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class BackgroundTask:
    """A background task."""
    task_id: str
    command: str
    status: TaskStatus = TaskStatus.RUNNING
    output: list[str] = field(default_factory=list)
    exit_code: int | None = None
    created_at: float = field(default_factory=time.time)
    _process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _task_handle: asyncio.Task | None = field(default=None, repr=False)


# Session-scoped task pools
_TASK_POOLS: dict[str, dict[str, BackgroundTask]] = {}


def _get_tasks(session_id: str) -> dict[str, BackgroundTask]:
    if session_id not in _TASK_POOLS:
        _TASK_POOLS[session_id] = {}
    return _TASK_POOLS[session_id]


# ---------------------------------------------------------------------------
# TaskStartTool
# ---------------------------------------------------------------------------

class TaskStartTool(Tool):
    """Start a command as a background task."""

    @property
    def name(self) -> str:
        return "task_start"

    @property
    def description(self) -> str:
        return (
            "Start a shell command as a background task. Returns a task_id "
            "you can use with task_output, task_status, and task_stop. "
            "Use for long-running processes like builds, test suites, or servers."
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
                    "description": "The shell command to run in the background.",
                },
            },
            "required": ["command"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        import os

        command: str = kwargs["command"]
        if not command.strip():
            return ToolOutput.error("Command cannot be empty.")

        task_id = f"task-{uuid.uuid4().hex[:8]}"
        tasks = _get_tasks(ctx.session_id)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=ctx.cwd,
                env={**os.environ},
            )
        except Exception as exc:
            return ToolOutput.error(f"Failed to start background task: {exc}")

        task = BackgroundTask(
            task_id=task_id,
            command=command,
            _process=proc,
        )

        async def _monitor():
            try:
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    task.output.append(line.decode("utf-8", errors="replace"))
                await proc.wait()
                task.exit_code = proc.returncode
                task.status = (
                    TaskStatus.COMPLETED if proc.returncode == 0
                    else TaskStatus.FAILED
                )
            except asyncio.CancelledError:
                task.status = TaskStatus.STOPPED

        task._task_handle = asyncio.create_task(_monitor())
        tasks[task_id] = task

        return ToolOutput.success(
            f"Background task started: {task_id}\n"
            f"Command: {command}\n"
            f"PID: {proc.pid}\n"
            f"Use task_output('{task_id}') to check output."
        )


# ---------------------------------------------------------------------------
# TaskOutputTool
# ---------------------------------------------------------------------------

class TaskOutputTool(Tool):
    """Retrieve output from a background task."""

    @property
    def name(self) -> str:
        return "task_output"

    @property
    def description(self) -> str:
        return (
            "Get the current output of a background task. "
            "Shows output accumulated so far, even if the task is still running. "
            "Use 'tail' parameter to get only the last N lines."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to get output from.",
                },
                "tail": {
                    "type": "integer",
                    "description": "Only show the last N lines (default: all).",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        task_id: str = kwargs["task_id"]
        tail: int | None = kwargs.get("tail")

        tasks = _get_tasks(ctx.session_id)
        task = tasks.get(task_id)

        if task is None:
            return ToolOutput.error(f"Unknown task: {task_id}")

        output_lines = task.output
        if tail and tail > 0:
            output_lines = output_lines[-tail:]

        text = "".join(output_lines)
        if len(text) > MAX_OUTPUT:
            text = text[-MAX_OUTPUT:]
            text = f"[...truncated, showing last {MAX_OUTPUT} chars...]\n" + text

        header = (
            f"Task: {task_id} [{task.status.value}]\n"
            f"Command: {task.command}\n"
        )
        if task.exit_code is not None:
            header += f"Exit code: {task.exit_code}\n"
        header += f"Output ({len(task.output)} lines):\n\n"

        return ToolOutput.success(header + (text or "(no output yet)"))


# ---------------------------------------------------------------------------
# TaskStatusTool
# ---------------------------------------------------------------------------

class TaskStatusTool(Tool):
    """Check the status of background tasks."""

    @property
    def name(self) -> str:
        return "task_status"

    @property
    def description(self) -> str:
        return "List all background tasks and their current status."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        tasks = _get_tasks(ctx.session_id)

        if not tasks:
            return ToolOutput.success("No background tasks.")

        lines = [f"Background tasks ({len(tasks)}):"]
        for t in tasks.values():
            elapsed = time.time() - t.created_at
            pid = t._process.pid if t._process else "?"
            lines.append(
                f"  {t.task_id}  [{t.status.value}]  "
                f"PID {pid}  {elapsed:.0f}s  "
                f"{len(t.output)} lines  — {t.command[:60]}"
            )
        return ToolOutput.success("\n".join(lines))


# ---------------------------------------------------------------------------
# TaskStopTool
# ---------------------------------------------------------------------------

class TaskStopTool(Tool):
    """Stop a running background task."""

    @property
    def name(self) -> str:
        return "task_stop"

    @property
    def description(self) -> str:
        return "Stop a running background task. Sends SIGTERM, then SIGKILL if needed."

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to stop.",
                },
            },
            "required": ["task_id"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        task_id: str = kwargs["task_id"]

        tasks = _get_tasks(ctx.session_id)
        task = tasks.get(task_id)

        if task is None:
            return ToolOutput.error(f"Unknown task: {task_id}")

        if task.status != TaskStatus.RUNNING:
            return ToolOutput.success(
                f"Task {task_id} is already {task.status.value}."
            )

        proc = task._process
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except Exception:
                pass

        if task._task_handle and not task._task_handle.done():
            task._task_handle.cancel()

        task.status = TaskStatus.STOPPED
        task.exit_code = proc.returncode if proc else None

        return ToolOutput.success(
            f"Task {task_id} stopped (exit code: {task.exit_code})."
        )

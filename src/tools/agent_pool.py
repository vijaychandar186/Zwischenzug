"""
Enhanced subagent system — spawn, message, wait, list, and lifecycle control.

Provides an agent pool where multiple child agents can run concurrently,
be messaged with follow-up instructions, waited on, and interrupted/closed.
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

logger = logging.getLogger("zwischenzug.tools.agent_pool")

_MAX_RESULT_CHARS = 50_000
_DEFAULT_MAX_TURNS = 15


# ---------------------------------------------------------------------------
# Agent pool state (process-global, keyed by session)
# ---------------------------------------------------------------------------

class AgentStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class ManagedAgent:
    """Represents a child agent in the pool."""
    agent_id: str
    task: str
    status: AgentStatus = AgentStatus.RUNNING
    output: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    _task_handle: asyncio.Task | None = field(default=None, repr=False)
    _message_queue: asyncio.Queue | None = field(default=None, repr=False)
    error: str = ""


# Session-scoped pools: session_id -> {agent_id -> ManagedAgent}
_AGENT_POOLS: dict[str, dict[str, ManagedAgent]] = {}


def _get_pool(session_id: str) -> dict[str, ManagedAgent]:
    if session_id not in _AGENT_POOLS:
        _AGENT_POOLS[session_id] = {}
    return _AGENT_POOLS[session_id]


# ---------------------------------------------------------------------------
# SpawnAgentTool
# ---------------------------------------------------------------------------

class SpawnAgentTool(Tool):
    """Spawn a child agent that runs in the background."""

    @property
    def name(self) -> str:
        return "spawn_agent"

    @property
    def description(self) -> str:
        return (
            "Launch a child agent to handle a subtask in the background. "
            "Returns an agent_id you can use with message_agent, wait_agent, "
            "and list_agents. The child runs concurrently — you can spawn "
            "multiple agents in parallel for independent tasks."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        "A clear, self-contained description of the subtask. "
                        "Include all necessary context — the child has no memory "
                        "of the parent conversation."
                    ),
                },
                "max_turns": {
                    "type": "integer",
                    "description": (
                        f"Maximum turns for the child agent (default {_DEFAULT_MAX_TURNS}, max 50)."
                    ),
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional system prompt for the child agent.",
                },
            },
            "required": ["task"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        task: str = kwargs["task"]
        max_turns = min(kwargs.get("max_turns") or _DEFAULT_MAX_TURNS, 50)
        system_prompt: str = kwargs.get("system_prompt") or ""

        if not task.strip():
            return ToolOutput.error("Task description cannot be empty.")

        provider = getattr(ctx, "provider", None)
        model = getattr(ctx, "model", None)
        if not provider or not model:
            return ToolOutput.error(
                "spawn_agent requires provider and model info on ToolContext."
            )

        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        pool = _get_pool(ctx.session_id)

        managed = ManagedAgent(
            agent_id=agent_id,
            task=task,
            _message_queue=asyncio.Queue(),
        )

        async def _run():
            try:
                result = await _run_child_agent(
                    task=task,
                    provider=provider,
                    model=model,
                    cwd=ctx.cwd,
                    permission_mode=ctx.permission_mode,
                    session_id=ctx.session_id,
                    max_turns=max_turns,
                    system_prompt=system_prompt,
                    message_queue=managed._message_queue,
                )
                managed.output.append(result)
                managed.status = AgentStatus.COMPLETED
            except asyncio.CancelledError:
                managed.status = AgentStatus.INTERRUPTED
            except Exception as exc:
                managed.error = str(exc)
                managed.status = AgentStatus.FAILED
                logger.warning("agent %s failed: %s", agent_id, exc)

        managed._task_handle = asyncio.create_task(_run())
        pool[agent_id] = managed

        return ToolOutput.success(
            f"Agent spawned: {agent_id}\n"
            f"Task: {task[:200]}\n"
            f"Use wait_agent('{agent_id}') to get results, or "
            f"message_agent('{agent_id}', ...) to send follow-up instructions."
        )


# ---------------------------------------------------------------------------
# MessageAgentTool
# ---------------------------------------------------------------------------

class MessageAgentTool(Tool):
    """Send a follow-up message to a running agent."""

    @property
    def name(self) -> str:
        return "message_agent"

    @property
    def description(self) -> str:
        return (
            "Send a follow-up message to a running child agent. "
            "The message is queued and the agent processes it after "
            "its current turn completes."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the agent to message.",
                },
                "message": {
                    "type": "string",
                    "description": "The follow-up message or instruction.",
                },
            },
            "required": ["agent_id", "message"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        agent_id: str = kwargs["agent_id"]
        message: str = kwargs["message"]

        pool = _get_pool(ctx.session_id)
        managed = pool.get(agent_id)

        if managed is None:
            return ToolOutput.error(f"Unknown agent: {agent_id}")

        if managed.status != AgentStatus.RUNNING:
            return ToolOutput.error(
                f"Agent {agent_id} is {managed.status.value}, cannot message it."
            )

        if managed._message_queue is not None:
            await managed._message_queue.put(message)

        return ToolOutput.success(f"Message queued for agent {agent_id}.")


# ---------------------------------------------------------------------------
# WaitAgentTool
# ---------------------------------------------------------------------------

class WaitAgentTool(Tool):
    """Wait for a child agent to complete and retrieve its output."""

    @property
    def name(self) -> str:
        return "wait_agent"

    @property
    def description(self) -> str:
        return (
            "Wait for a child agent to complete and return its output. "
            "If the agent is already done, returns immediately. "
            "Optional timeout (default 120s)."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the agent to wait for.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Max seconds to wait (default 120).",
                },
            },
            "required": ["agent_id"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        agent_id: str = kwargs["agent_id"]
        timeout: float = float(kwargs.get("timeout") or 120.0)

        pool = _get_pool(ctx.session_id)
        managed = pool.get(agent_id)

        if managed is None:
            return ToolOutput.error(f"Unknown agent: {agent_id}")

        if managed.status == AgentStatus.RUNNING and managed._task_handle:
            try:
                await asyncio.wait_for(managed._task_handle, timeout=timeout)
            except asyncio.TimeoutError:
                return ToolOutput.error(
                    f"Agent {agent_id} still running after {timeout}s. "
                    "Try again later or interrupt it."
                )

        result = "".join(managed.output)
        if len(result) > _MAX_RESULT_CHARS:
            result = result[:_MAX_RESULT_CHARS] + "\n\n[output truncated]"

        status_line = f"Status: {managed.status.value}"
        if managed.error:
            status_line += f"\nError: {managed.error}"

        return ToolOutput.success(f"{status_line}\n\n{result}" if result else status_line)


# ---------------------------------------------------------------------------
# ListAgentsTool
# ---------------------------------------------------------------------------

class ListAgentsTool(Tool):
    """List all agents in the current session's pool."""

    @property
    def name(self) -> str:
        return "list_agents"

    @property
    def description(self) -> str:
        return "List all spawned agents and their current status."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        pool = _get_pool(ctx.session_id)

        if not pool:
            return ToolOutput.success("No agents in pool.")

        lines = [f"Agents ({len(pool)}):"]
        for a in pool.values():
            elapsed = time.time() - a.created_at
            lines.append(
                f"  {a.agent_id}  [{a.status.value}]  "
                f"{elapsed:.0f}s ago  — {a.task[:80]}"
            )
        return ToolOutput.success("\n".join(lines))


# ---------------------------------------------------------------------------
# InterruptAgentTool
# ---------------------------------------------------------------------------

class InterruptAgentTool(Tool):
    """Interrupt (cancel) a running agent."""

    @property
    def name(self) -> str:
        return "interrupt_agent"

    @property
    def description(self) -> str:
        return "Cancel a running child agent. Partial output may still be available."

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "The ID of the agent to interrupt.",
                },
            },
            "required": ["agent_id"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        agent_id: str = kwargs["agent_id"]
        pool = _get_pool(ctx.session_id)
        managed = pool.get(agent_id)

        if managed is None:
            return ToolOutput.error(f"Unknown agent: {agent_id}")

        if managed.status != AgentStatus.RUNNING:
            return ToolOutput.success(
                f"Agent {agent_id} is already {managed.status.value}."
            )

        if managed._task_handle and not managed._task_handle.done():
            managed._task_handle.cancel()
            try:
                await managed._task_handle
            except asyncio.CancelledError:
                pass

        managed.status = AgentStatus.INTERRUPTED
        return ToolOutput.success(f"Agent {agent_id} interrupted.")


# ---------------------------------------------------------------------------
# Child agent runner (shared with spawn)
# ---------------------------------------------------------------------------

async def _run_child_agent(
    *,
    task: str,
    provider: str,
    model: str,
    cwd: str,
    permission_mode,
    session_id: str,
    max_turns: int,
    system_prompt: str,
    message_queue: asyncio.Queue | None = None,
) -> str:
    """Build and run an isolated child agent, returning its collected text."""
    from ..provider import build_llm
    from ..core.session import SessionConfig, SessionState
    from ..core.agent import run_agent, TextDelta
    from . import ToolContext, ToolOrchestrator, ToolRegistry, PermissionMode

    child_llm = build_llm(provider, model, streaming=True)

    child_config = SessionConfig(
        model=model,
        system_prompt=system_prompt or "You are a helpful coding assistant. Be concise and direct.",
        max_turns=max_turns,
        permission_mode=str(permission_mode.value) if hasattr(permission_mode, "value") else str(permission_mode),
    )
    child_session = SessionState.new(child_config, cwd=cwd)
    child_session.push_human(task)

    child_registry = _child_registry()
    child_orchestrator = ToolOrchestrator(child_registry)

    collected: list[str] = []

    def on_event(event):
        if isinstance(event, TextDelta):
            collected.append(event.text)

    await run_agent(
        child_session,
        child_llm,
        child_registry,
        child_orchestrator,
        on_event=on_event,
    )

    return "".join(collected)


def _child_registry() -> "ToolRegistry":
    """Build a tool registry for child agents — standard tools, no agent pool."""
    from .bash import BashTool
    from .files import FileEditTool, FileReadTool, FileWriteTool
    from .search import GlobTool, GrepTool
    from .web import WebFetchTool, WebSearchTool
    from . import ToolRegistry

    registry = ToolRegistry()
    for tool in [
        BashTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        WebSearchTool(),
    ]:
        registry.register(tool)
    return registry

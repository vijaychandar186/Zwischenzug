"""
Subagent tool — spawn a child agent to handle a subtask autonomously.

The child agent gets its own session, tool registry, and orchestrator.
It inherits the parent's provider, model, and permission mode by default,
but these can be overridden via tool parameters.
"""
from __future__ import annotations

import logging
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.subagent")

# Sensible defaults for child agents
_DEFAULT_MAX_TURNS = 15
_MAX_RESULT_CHARS = 50_000


class SubagentTool(Tool):
    """Spawn a child agent to handle a subtask."""

    @property
    def name(self) -> str:
        return "subagent"

    @property
    def description(self) -> str:
        return (
            "Launch a child agent to handle a complex subtask autonomously. "
            "The child gets its own conversation, tools (bash, file read/write/edit, "
            "glob, grep, web fetch/search), and token budget. "
            "Use this when a task is independent and can be delegated — "
            "e.g. researching a question, searching code, running a multi-step operation. "
            "Returns the child's final text output. "
            "The child inherits the parent's provider, model, cwd, and permissions."
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
                        f"Maximum turns for the child agent (default {_DEFAULT_MAX_TURNS}). "
                        "Keep low for simple lookups, raise for multi-step work."
                    ),
                },
                "system_prompt": {
                    "type": "string",
                    "description": (
                        "Optional system prompt for the child agent. "
                        "If omitted, the child uses a minimal default prompt."
                    ),
                },
            },
            "required": ["task"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        task: str = kwargs["task"]
        raw_max_turns = kwargs.get("max_turns")
        max_turns: int = raw_max_turns if raw_max_turns is not None else _DEFAULT_MAX_TURNS
        system_prompt: str = kwargs.get("system_prompt") or ""

        if not task.strip():
            return ToolOutput.error("Task description cannot be empty.")

        # Resolve parent provider/model from context (validate early)
        provider = getattr(ctx, "provider", None)
        model = getattr(ctx, "model", None)
        if not provider or not model:
            return ToolOutput.error(
                "Subagent requires provider and model info on ToolContext. "
                "This is a configuration bug — please report it."
            )

        if max_turns < 1:
            return ToolOutput.error("max_turns must be at least 1.")
        if max_turns > 50:
            max_turns = 50  # hard cap

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
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("subagent failed: %s", exc)
            return ToolOutput.error(f"Subagent failed: {exc}")

        # Truncate very large outputs
        if len(result) > _MAX_RESULT_CHARS:
            result = result[:_MAX_RESULT_CHARS] + "\n\n[output truncated]"

        return ToolOutput.success(result or "(subagent produced no output)")


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
) -> str:
    """Build and run an isolated child agent, returning its collected text."""
    from ..provider import build_llm
    from ..core.session import SessionConfig, SessionState
    from ..core.agent import run_agent, TextDelta, ThinkingDelta
    from . import ToolContext, ToolOrchestrator, ToolRegistry, PermissionMode, default_registry

    # Build child LLM (reuses the same provider credentials from env)
    child_llm = build_llm(
        provider,
        model,
        streaming=True,
    )

    # Build child session
    child_config = SessionConfig(
        model=model,
        system_prompt=system_prompt or "You are a helpful coding assistant. Be concise and direct.",
        max_turns=max_turns,
        permission_mode=str(permission_mode.value) if hasattr(permission_mode, "value") else str(permission_mode),
    )
    child_session = SessionState.new(child_config, cwd=cwd)
    child_session.push_human(task)

    # Build child tool registry (standard tools, no subagent to prevent recursion)
    child_registry = _child_registry()
    child_orchestrator = ToolOrchestrator(child_registry)

    child_ctx_permission = (
        permission_mode
        if isinstance(permission_mode, PermissionMode)
        else PermissionMode(permission_mode)
    )

    # Collect output
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
    """Build a tool registry for child agents — standard tools, no subagent."""
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

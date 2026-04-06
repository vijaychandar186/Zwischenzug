"""
Zwischenzug tool system — protocol, registry, context, orchestrator.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from langchain_core.tools import StructuredTool


class PermissionMode(str, Enum):
    AUTO        = "auto"
    INTERACTIVE = "interactive"
    DENY        = "deny"


@dataclass
class ToolContext:
    """Execution context passed to every tool call."""
    cwd: str
    permission_mode: PermissionMode = PermissionMode.AUTO
    session_id: str = ""
    provider: str = ""
    model: str = ""


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False

    @classmethod
    def success(cls, content: str) -> "ToolOutput":
        return cls(content=content, is_error=False)

    @classmethod
    def error(cls, message: str) -> "ToolOutput":
        return cls(content=message, is_error=True)


class Tool(ABC):
    """Base class for all Zwischenzug tools."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    def is_read_only(self) -> bool:
        return False

    @abstractmethod
    def input_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput: ...

    def as_langchain_tool(self, ctx: ToolContext) -> StructuredTool:
        """Wrap this tool as a LangChain StructuredTool."""
        tool_self = self
        schema = self.input_schema()
        fields = schema.get("properties", {})

        async def _run(**kwargs: Any) -> str:
            out = await tool_self.execute(ctx, **kwargs)
            prefix = "[ERROR] " if out.is_error else ""
            return f"{prefix}{out.content}"

        return StructuredTool.from_function(
            coroutine=_run,
            name=self.name,
            description=self.description,
            args_schema=_make_pydantic_model(self.name, fields, schema.get("required", [])),
        )


def _make_pydantic_model(name: str, fields: dict, required: list[str]):
    """Dynamically build a Pydantic model for tool input validation."""
    from pydantic import Field, create_model

    def _annotation_from_schema(schema: dict[str, Any]) -> Any:
        if not isinstance(schema, dict):
            return Any
        if "enum" in schema:
            return str
        schema_type = schema.get("type")
        if schema_type == "integer":
            return int
        if schema_type == "number":
            return float
        if schema_type == "boolean":
            return bool
        if schema_type == "array":
            return list[Any]
        if schema_type == "object":
            return dict[str, Any]
        if isinstance(schema.get("anyOf"), list) or isinstance(schema.get("oneOf"), list):
            return Any
        return str

    annotations: dict[str, Any] = {}
    defaults: dict[str, Any] = {}

    for fname, fdef in fields.items():
        description = fdef.get("description", "")
        ftype = _annotation_from_schema(fdef)

        if fname in required:
            annotations[fname] = ftype
            defaults[fname] = Field(description=description)
        else:
            annotations[fname] = ftype | None
            defaults[fname] = Field(default=None, description=description)

    return create_model(f"{name}Input", **{k: (annotations[k], defaults[k]) for k in annotations})


class ToolRegistry:
    """In-memory tool registry."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def as_langchain_tools(self, ctx: ToolContext) -> list[StructuredTool]:
        return [t.as_langchain_tool(ctx) for t in self._tools.values()]


@dataclass
class ToolResult:
    tool_call_id: str
    output: ToolOutput


class ToolOrchestrator:
    """Executes tool calls with permission enforcement."""

    def __init__(
        self,
        registry: ToolRegistry,
        on_approve: Callable[[str, str, dict], bool] | None = None,
        permission_manager: Any = None,  # PermissionManager | None
    ) -> None:
        self._registry = registry
        self._on_approve = on_approve
        self._permission_manager = permission_manager

    async def execute(
        self,
        tool_call_id: str,
        name: str,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        tool = self._registry.get(name)
        if tool is None:
            return ToolResult(
                tool_call_id=tool_call_id,
                output=ToolOutput.error(f"Unknown tool: {name}"),
            )

        # ── Permission check ─────────────────────────────────────────────────
        primary_input = str(args.get("command") or args.get("path") or args.get("url")
                            or args.get("query") or args.get("pattern") or "")

        if self._permission_manager is not None:
            decision = self._permission_manager.check(name, primary_input, tool.is_read_only)
        else:
            # Fallback to simple mode-based check
            decision = _simple_permission_check(ctx.permission_mode, tool.is_read_only)

        if decision == "deny":
            return ToolResult(
                tool_call_id=tool_call_id,
                output=ToolOutput.error(
                    f"Permission denied: tool '{name}' blocked by permission rules."
                ),
            )

        if decision == "ask":
            approved = self._interactive_approve(name, args)
            if not approved:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    output=ToolOutput.error(f"Permission denied by user: tool '{name}'"),
                )

        try:
            output = await tool.execute(ctx, **args)
        except Exception as exc:  # noqa: BLE001
            output = ToolOutput.error(f"Tool '{name}' raised an exception: {exc}")

        return ToolResult(tool_call_id=tool_call_id, output=output)

    async def execute_batch(
        self,
        calls: list[dict[str, Any]],
        ctx: ToolContext,
    ) -> list[ToolResult]:
        """
        Execute a batch of tool calls.
        Read-only tools run concurrently; write tools run serially.
        """
        # Split into read-only and write calls
        readonly_calls = []
        write_calls = []
        for call in calls:
            tool = self._registry.get(call["name"])
            if tool and tool.is_read_only:
                readonly_calls.append(call)
            else:
                write_calls.append(call)

        results: list[ToolResult] = []

        # Dispatch read-only tools concurrently
        if readonly_calls:
            ro_tasks = [
                self.execute(c["id"], c["name"], c["args"], ctx)
                for c in readonly_calls
            ]
            results.extend(await asyncio.gather(*ro_tasks))

        # Dispatch write tools serially
        for call in write_calls:
            results.append(await self.execute(call["id"], call["name"], call["args"], ctx))

        # Restore original order
        order = {c["id"]: i for i, c in enumerate(calls)}
        results.sort(key=lambda r: order.get(r.tool_call_id, 0))
        return results

    def _interactive_approve(self, name: str, args: dict) -> bool:
        if self._on_approve is not None:
            return self._on_approve(name, "", args)
        summary = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:3])
        try:
            answer = input(f"\n[Permission] Allow tool '{name}'({summary})? [y/N] ").strip().lower()
            return answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False


def _simple_permission_check(
    mode: PermissionMode, is_read_only: bool
) -> str:
    if mode == PermissionMode.DENY and not is_read_only:
        return "deny"
    if mode == PermissionMode.INTERACTIVE and not is_read_only:
        return "ask"
    return "allow"


def default_registry() -> ToolRegistry:
    """Build and return the standard Zwischenzug tool registry."""
    from .bash import BashTool
    from .files import FileEditTool, FileReadTool, FileWriteTool
    from .search import GlobTool, GrepTool
    from .web import WebFetchTool, WebSearchTool
    from .auxiliary import AskUserQuestionTool, TodoWriteTool
    from .subagent import SubagentTool
    # Enhanced subagent pool
    from .agent_pool import (
        SpawnAgentTool, MessageAgentTool, WaitAgentTool,
        ListAgentsTool, InterruptAgentTool,
    )
    # Structured planning
    from .planning import PlanTool, PlanModeTool
    # Native patch editing
    from .patch import ApplyPatchTool
    # Persistent shell sessions
    from .shell_session import ShellCreateTool, ShellExecTool, ShellListTool, ShellCloseTool
    # Sandboxing
    from .sandbox import SandboxTool
    # Browser automation
    from .browser import BrowserTool
    from .browser_agent import BrowserAgentTool
    # Notebook editing
    from .notebook import NotebookEditTool
    # Worktree isolation
    from .worktree import (
        WorktreeCreateTool, WorktreeListTool, WorktreeMergeTool, WorktreeRemoveTool,
    )
    # Background task control
    from .background import TaskStartTool, TaskOutputTool, TaskStatusTool, TaskStopTool

    registry = ToolRegistry()
    for tool in [
        # Core tools
        BashTool(),
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        GlobTool(),
        GrepTool(),
        WebFetchTool(),
        WebSearchTool(),
        TodoWriteTool(),
        AskUserQuestionTool(),
        SubagentTool(),
        # Enhanced subagent pool
        SpawnAgentTool(),
        MessageAgentTool(),
        WaitAgentTool(),
        ListAgentsTool(),
        InterruptAgentTool(),
        # Structured planning
        PlanTool(),
        PlanModeTool(),
        # Native patch editing
        ApplyPatchTool(),
        # Persistent shell sessions
        ShellCreateTool(),
        ShellExecTool(),
        ShellListTool(),
        ShellCloseTool(),
        # Sandboxing
        SandboxTool(),
        # Browser automation
        BrowserTool(),
        BrowserAgentTool(),
        # Notebook editing
        NotebookEditTool(),
        # Worktree isolation
        WorktreeCreateTool(),
        WorktreeListTool(),
        WorktreeMergeTool(),
        WorktreeRemoveTool(),
        # Background task control
        TaskStartTool(),
        TaskOutputTool(),
        TaskStatusTool(),
        TaskStopTool(),
    ]:
        registry.register(tool)
    return registry

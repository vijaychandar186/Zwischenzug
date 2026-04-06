"""
Tests for src/tools — ToolRegistry, ToolOrchestrator, PermissionMode, ToolContext.
"""
from __future__ import annotations

import pytest

from src.tools import (
    PermissionMode,
    Tool,
    ToolContext,
    ToolOrchestrator,
    ToolOutput,
    ToolRegistry,
    default_registry,
)


# ── minimal test tool ───────────────────────────────��─────────────────────────

class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the input message."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self):
        return {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Text to echo."}},
            "required": ["message"],
        }

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolOutput:
        return ToolOutput.success(kwargs["message"])


class _MutateTool(Tool):
    """Non-read-only tool — should be blocked in deny mode."""

    @property
    def name(self) -> str:
        return "mutate"

    @property
    def description(self) -> str:
        return "Writes something."

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self):
        return {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolOutput:
        return ToolOutput.success(f"mutated: {kwargs['value']}")


# ── ToolRegistry ──────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        assert reg.get("echo") is not None

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("does_not_exist") is None

    def test_all_returns_registered_tools(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        reg.register(_MutateTool())
        assert len(reg.all()) == 2

    def test_names_returns_all_tool_names(self):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        assert "echo" in reg.names()

    def test_default_registry_has_core_tools(self):
        reg = default_registry()
        names = reg.names()
        assert "bash" in names
        assert "read_file" in names
        assert "write_file" in names
        assert "edit_file" in names
        assert "glob" in names
        assert "grep" in names


# ── ToolContext ───────────────────────────────────────────────────────────────

class TestToolContext:
    def test_default_permission_mode(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        assert ctx.permission_mode == PermissionMode.AUTO

    def test_session_id_defaults_empty(self, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path))
        assert ctx.session_id == ""


# ── ToolOrchestrator ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestToolOrchestrator:
    async def test_execute_read_only_tool_in_auto_mode(self, tmp_path):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)

        result = await orc.execute("call-1", "echo", {"message": "hello"}, ctx)
        assert not result.output.is_error
        assert result.output.content == "hello"

    async def test_execute_unknown_tool_returns_error(self, tmp_path):
        reg = ToolRegistry()
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path))

        result = await orc.execute("call-x", "ghost", {}, ctx)
        assert result.output.is_error
        assert "Unknown tool" in result.output.content

    async def test_deny_mode_blocks_write_tool(self, tmp_path):
        reg = ToolRegistry()
        reg.register(_MutateTool())
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.DENY)

        result = await orc.execute("call-2", "mutate", {"value": "x"}, ctx)
        assert result.output.is_error
        assert "permission denied" in result.output.content.lower()

    async def test_deny_mode_allows_read_only_tool(self, tmp_path):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.DENY)

        result = await orc.execute("call-3", "echo", {"message": "safe"}, ctx)
        assert not result.output.is_error
        assert result.output.content == "safe"

    async def test_execute_batch_runs_all_calls(self, tmp_path):
        reg = ToolRegistry()
        reg.register(_EchoTool())
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path))

        calls = [
            {"id": "c1", "name": "echo", "args": {"message": "first"}},
            {"id": "c2", "name": "echo", "args": {"message": "second"}},
        ]
        results = await orc.execute_batch(calls, ctx)
        assert len(results) == 2
        contents = {r.output.content for r in results}
        assert "first" in contents
        assert "second" in contents

    async def test_execute_batch_returns_error_for_unknown(self, tmp_path):
        reg = ToolRegistry()
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path))

        results = await orc.execute_batch([{"id": "c1", "name": "nope", "args": {}}], ctx)
        assert results[0].output.is_error

    async def test_tool_exception_is_caught(self, tmp_path):
        class _BrokenTool(Tool):
            @property
            def name(self): return "broken"
            @property
            def description(self): return "always fails"
            @property
            def is_read_only(self): return True
            def input_schema(self): return {"type": "object", "properties": {}}
            async def execute(self, ctx, **kwargs): raise RuntimeError("kaboom")

        reg = ToolRegistry()
        reg.register(_BrokenTool())
        orc = ToolOrchestrator(reg)
        ctx = ToolContext(cwd=str(tmp_path))

        result = await orc.execute("c1", "broken", {}, ctx)
        assert result.output.is_error
        assert "kaboom" in result.output.content


# ── LangChain tool wrapping ───────────────────────────────────────────────────

class TestLangChainToolWrap:
    def test_as_langchain_tool_has_correct_name(self, auto_ctx):
        lc = _EchoTool().as_langchain_tool(auto_ctx)
        assert lc.name == "echo"

    def test_as_langchain_tool_has_description(self, auto_ctx):
        lc = _EchoTool().as_langchain_tool(auto_ctx)
        assert "echo" in lc.description.lower()

    @pytest.mark.asyncio
    async def test_as_langchain_tool_runs(self, auto_ctx):
        lc = _EchoTool().as_langchain_tool(auto_ctx)
        result = await lc.ainvoke({"message": "ping"})
        assert "ping" in result

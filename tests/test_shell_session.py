"""Tests for persistent shell sessions."""
from __future__ import annotations

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.shell_session import (
    ShellCloseTool,
    ShellCreateTool,
    ShellExecTool,
    ShellListTool,
    _SHELL_POOLS,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-shell",
    )


@pytest.fixture(autouse=True)
def _clear_pools():
    _SHELL_POOLS.clear()
    yield
    # Clean up any remaining shell processes
    import asyncio
    for pool in _SHELL_POOLS.values():
        for shell in pool.values():
            if shell.process and shell.process.returncode is None:
                try:
                    shell.process.kill()
                except Exception:
                    pass
    _SHELL_POOLS.clear()


class TestShellCreateMetadata:
    def test_name(self):
        assert ShellCreateTool().name == "shell_create"

    def test_not_read_only(self):
        assert not ShellCreateTool().is_read_only

    def test_schema_requires_session_name(self):
        assert "session_name" in ShellCreateTool().input_schema()["required"]


class TestShellCreate:
    @pytest.mark.asyncio
    async def test_create_shell(self, ctx):
        result = await ShellCreateTool().execute(ctx, session_name="build")
        assert not result.is_error
        assert "build" in result.content
        assert "PID" in result.content

    @pytest.mark.asyncio
    async def test_create_empty_name(self, ctx):
        result = await ShellCreateTool().execute(ctx, session_name="   ")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_create_duplicate(self, ctx):
        await ShellCreateTool().execute(ctx, session_name="dup")
        result = await ShellCreateTool().execute(ctx, session_name="dup")
        assert result.is_error
        assert "already exists" in result.content.lower()


class TestShellExec:
    @pytest.mark.asyncio
    async def test_exec_in_nonexistent_shell(self, ctx):
        result = await ShellExecTool().execute(
            ctx, session_name="nope", command="echo hi"
        )
        assert result.is_error

    @pytest.mark.asyncio
    async def test_exec_echo(self, ctx):
        await ShellCreateTool().execute(ctx, session_name="test")
        result = await ShellExecTool().execute(
            ctx, session_name="test", command="echo hello_world"
        )
        assert not result.is_error
        assert "hello_world" in result.content


class TestShellList:
    @pytest.mark.asyncio
    async def test_list_empty(self, ctx):
        result = await ShellListTool().execute(ctx)
        assert "no active" in result.content.lower()

    @pytest.mark.asyncio
    async def test_list_with_shells(self, ctx):
        await ShellCreateTool().execute(ctx, session_name="a")
        await ShellCreateTool().execute(ctx, session_name="b")
        result = await ShellListTool().execute(ctx)
        assert "a" in result.content
        assert "b" in result.content

    def test_is_read_only(self):
        assert ShellListTool().is_read_only


class TestShellClose:
    @pytest.mark.asyncio
    async def test_close_nonexistent(self, ctx):
        result = await ShellCloseTool().execute(ctx, session_name="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_close_existing(self, ctx):
        await ShellCreateTool().execute(ctx, session_name="doomed")
        result = await ShellCloseTool().execute(ctx, session_name="doomed")
        assert not result.is_error
        assert "closed" in result.content.lower()

        # Verify it's gone
        result = await ShellListTool().execute(ctx)
        assert "doomed" not in result.content


class TestRegistryIntegration:
    def test_shell_tools_in_default_registry(self):
        from src.tools import default_registry
        reg = default_registry()
        for name in ["shell_create", "shell_exec", "shell_list", "shell_close"]:
            assert reg.get(name) is not None, f"{name} not in registry"

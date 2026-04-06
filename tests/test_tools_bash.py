"""
Tests for src/tools/bash — BashTool.
"""
from __future__ import annotations

import pytest

from src.tools.bash import BashTool, DEFAULT_TIMEOUT, MAX_OUTPUT
from src.tools import ToolContext, PermissionMode


@pytest.fixture
def tool():
    return BashTool()


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


@pytest.mark.asyncio
class TestBashTool:
    async def test_name_and_description(self, tool):
        assert tool.name == "bash"
        assert "shell" in tool.description.lower() or "command" in tool.description.lower()

    async def test_is_not_read_only(self, tool):
        assert not tool.is_read_only

    async def test_simple_command_succeeds(self, tool, ctx):
        result = await tool.execute(ctx, command="echo hello")
        assert not result.is_error
        assert "hello" in result.content

    async def test_command_with_exit_code_zero_is_success(self, tool, ctx):
        result = await tool.execute(ctx, command="true")
        assert not result.is_error

    async def test_command_with_nonzero_exit_is_error(self, tool, ctx):
        result = await tool.execute(ctx, command="false")
        assert result.is_error

    async def test_stderr_included_in_output(self, tool, ctx):
        result = await tool.execute(ctx, command="echo err >&2; echo out")
        assert "out" in result.content or "err" in result.content

    async def test_cwd_is_respected(self, tool, tmp_path):
        ctx = ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)
        (tmp_path / "marker.txt").write_text("found")
        result = await tool.execute(ctx, command="cat marker.txt")
        assert not result.is_error
        assert "found" in result.content

    async def test_multiline_output(self, tool, ctx):
        result = await tool.execute(ctx, command="printf 'a\\nb\\nc\\n'")
        assert not result.is_error
        assert "a" in result.content and "b" in result.content

    async def test_timeout_raises_error(self, tool, ctx):
        result = await tool.execute(ctx, command="sleep 10", timeout=0.1)
        assert result.is_error
        assert "timed out" in result.content.lower()

    async def test_output_is_capped(self, tool, ctx):
        # Generate output larger than MAX_OUTPUT
        result = await tool.execute(ctx, command=f"python3 -c \"print('x' * {MAX_OUTPUT + 1000})\"")
        assert len(result.content) <= MAX_OUTPUT + 100  # small margin for truncation suffix

    async def test_empty_output_returns_no_output_message(self, tool, ctx):
        result = await tool.execute(ctx, command="true")
        assert not result.is_error
        assert result.content  # not empty

    async def test_env_var_access(self, tool, ctx):
        import os
        os.environ["_ZW_TEST_VAR"] = "zwischenzug_test"
        result = await tool.execute(ctx, command="echo $_ZW_TEST_VAR")
        assert "zwischenzug_test" in result.content

    async def test_pipe_commands(self, tool, ctx):
        result = await tool.execute(ctx, command="echo 'hello world' | tr 'a-z' 'A-Z'")
        assert not result.is_error
        assert "HELLO WORLD" in result.content

    async def test_input_schema_has_required_command(self, tool):
        schema = tool.input_schema()
        assert "command" in schema["required"]
        assert "command" in schema["properties"]

"""
Tests for src/tools/subagent — the subagent spawn tool.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.tools import PermissionMode, ToolContext
from src.tools.subagent import SubagentTool, _child_registry, _DEFAULT_MAX_TURNS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tool():
    return SubagentTool()


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-session",
        provider="groq",
        model="groq/llama-3.3-70b-versatile",
    )


@pytest.fixture
def ctx_no_provider(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-session",
    )


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------

class TestSubagentToolMetadata:
    def test_name(self, tool):
        assert tool.name == "subagent"

    def test_description_not_empty(self, tool):
        assert len(tool.description) > 20

    def test_is_not_read_only(self, tool):
        assert tool.is_read_only is False

    def test_input_schema_has_task_required(self, tool):
        schema = tool.input_schema()
        assert "task" in schema["properties"]
        assert "task" in schema["required"]

    def test_input_schema_has_optional_fields(self, tool):
        schema = tool.input_schema()
        assert "max_turns" in schema["properties"]
        assert "system_prompt" in schema["properties"]
        # These should NOT be required
        assert "max_turns" not in schema["required"]
        assert "system_prompt" not in schema["required"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestSubagentValidation:
    @pytest.mark.asyncio
    async def test_empty_task_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, task="   ")
        assert result.is_error
        assert "empty" in result.content.lower()

    @pytest.mark.asyncio
    async def test_missing_provider_returns_error(self, tool, ctx_no_provider):
        result = await tool.execute(ctx_no_provider, task="do something")
        assert result.is_error
        assert "provider" in result.content.lower()

    @pytest.mark.asyncio
    async def test_invalid_max_turns_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, task="do something", max_turns=0)
        assert result.is_error
        assert "max_turns" in result.content

    @pytest.mark.asyncio
    async def test_negative_max_turns_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, task="do something", max_turns=-5)
        assert result.is_error


# ---------------------------------------------------------------------------
# Child registry
# ---------------------------------------------------------------------------

class TestChildRegistry:
    def test_child_registry_has_standard_tools(self):
        registry = _child_registry()
        names = registry.names()
        for expected in ["bash", "read_file", "write_file", "edit_file", "glob", "grep"]:
            assert expected in names, f"Missing tool: {expected}"

    def test_child_registry_excludes_subagent(self):
        registry = _child_registry()
        assert "subagent" not in registry.names()

    def test_child_registry_excludes_auxiliary(self):
        registry = _child_registry()
        assert "todo_write" not in registry.names()
        assert "ask_user" not in registry.names()


# ---------------------------------------------------------------------------
# Execution (mocked)
# ---------------------------------------------------------------------------

def _make_mock_build_llm():
    """Return a mock build_llm that produces a mock LLM."""
    response = AIMessage(content="Child agent result text.")
    response.tool_calls = []
    response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

    mock_llm = MagicMock()
    mock_llm.bind_tools = MagicMock(return_value=mock_llm)

    async def _astream(messages):
        yield response

    mock_llm.astream = _astream
    return mock_llm


class TestSubagentExecution:
    @pytest.mark.asyncio
    async def test_successful_subagent_returns_text(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm) as mock_build:
            result = await tool.execute(ctx, task="Find all Python files")

        assert not result.is_error
        assert "Child agent result text." in result.content
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_subagent_passes_provider_and_model(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm) as mock_build:
            await tool.execute(ctx, task="test task")

        call_args = mock_build.call_args
        assert call_args[0][0] == "groq"  # provider
        assert call_args[0][1] == "groq/llama-3.3-70b-versatile"  # model

    @pytest.mark.asyncio
    async def test_subagent_respects_max_turns(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm):
            with patch("src.core.agent.run_agent") as mock_run:
                mock_run.return_value = None
                await tool.execute(ctx, task="test", max_turns=5)

                # Check the session config passed to run_agent
                call_args = mock_run.call_args
                child_session = call_args[0][0]  # first positional arg
                assert child_session.config.max_turns == 5

    @pytest.mark.asyncio
    async def test_subagent_caps_max_turns_at_50(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm):
            with patch("src.core.agent.run_agent") as mock_run:
                mock_run.return_value = None
                await tool.execute(ctx, task="test", max_turns=100)

                child_session = mock_run.call_args[0][0]
                assert child_session.config.max_turns == 50

    @pytest.mark.asyncio
    async def test_subagent_uses_custom_system_prompt(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm):
            with patch("src.core.agent.run_agent") as mock_run:
                mock_run.return_value = None
                await tool.execute(
                    ctx,
                    task="test",
                    system_prompt="You are a security auditor.",
                )

                child_session = mock_run.call_args[0][0]
                assert child_session.config.system_prompt == "You are a security auditor."

    @pytest.mark.asyncio
    async def test_subagent_inherits_permission_mode(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm):
            with patch("src.core.agent.run_agent") as mock_run:
                mock_run.return_value = None
                await tool.execute(ctx, task="test")

                child_session = mock_run.call_args[0][0]
                assert child_session.config.permission_mode == "auto"

    @pytest.mark.asyncio
    async def test_subagent_inherits_cwd(self, tool, ctx):
        mock_llm = _make_mock_build_llm()

        with patch("src.provider.build_llm", return_value=mock_llm):
            with patch("src.core.agent.run_agent") as mock_run:
                mock_run.return_value = None
                await tool.execute(ctx, task="test")

                child_session = mock_run.call_args[0][0]
                assert child_session.cwd == ctx.cwd

    @pytest.mark.asyncio
    async def test_subagent_handles_child_failure(self, tool, ctx):
        with patch("src.provider.build_llm", side_effect=ValueError("bad key")):
            result = await tool.execute(ctx, task="test task")

        assert result.is_error
        assert "failed" in result.content.lower()

    @pytest.mark.asyncio
    async def test_subagent_no_output_returns_placeholder(self, tool, ctx):
        # LLM that produces empty content
        response = AIMessage(content="")
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 5, "output_tokens": 1}

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        async def _astream(messages):
            yield response

        mock_llm.astream = _astream

        with patch("src.provider.build_llm", return_value=mock_llm):
            result = await tool.execute(ctx, task="test")

        assert not result.is_error
        assert "no output" in result.content.lower()

    @pytest.mark.asyncio
    async def test_subagent_truncates_large_output(self, tool, ctx):
        large_text = "x" * 60_000
        response = AIMessage(content=large_text)
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 5, "output_tokens": 1}

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        async def _astream(messages):
            yield response

        mock_llm.astream = _astream

        with patch("src.provider.build_llm", return_value=mock_llm):
            result = await tool.execute(ctx, task="generate big output")

        assert not result.is_error
        assert "[output truncated]" in result.content
        assert len(result.content) < 60_000


# ---------------------------------------------------------------------------
# Integration with default registry
# ---------------------------------------------------------------------------

class TestSubagentRegistration:
    def test_subagent_in_default_registry(self):
        from src.tools import default_registry
        registry = default_registry()
        assert "subagent" in registry.names()

    def test_subagent_produces_langchain_tool(self):
        from src.tools import default_registry
        registry = default_registry()
        ctx = ToolContext(cwd=".", permission_mode=PermissionMode.AUTO)
        lc_tools = registry.as_langchain_tools(ctx)
        tool_names = [t.name for t in lc_tools]
        assert "subagent" in tool_names

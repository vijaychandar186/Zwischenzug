"""Tests for the enhanced subagent pool system."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.agent_pool import (
    AgentStatus,
    InterruptAgentTool,
    ListAgentsTool,
    ManagedAgent,
    MessageAgentTool,
    SpawnAgentTool,
    WaitAgentTool,
    _AGENT_POOLS,
    _get_pool,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-session",
        provider="groq",
        model="groq/llama-3.3-70b",
    )


@pytest.fixture(autouse=True)
def _clear_pools():
    _AGENT_POOLS.clear()
    yield
    _AGENT_POOLS.clear()


# ---------------------------------------------------------------------------
# SpawnAgentTool
# ---------------------------------------------------------------------------

class TestSpawnAgentMetadata:
    def test_name(self):
        assert SpawnAgentTool().name == "spawn_agent"

    def test_not_read_only(self):
        assert not SpawnAgentTool().is_read_only

    def test_schema_requires_task(self):
        schema = SpawnAgentTool().input_schema()
        assert "task" in schema["required"]


class TestSpawnAgentValidation:
    @pytest.mark.asyncio
    async def test_empty_task_returns_error(self, ctx):
        result = await SpawnAgentTool().execute(ctx, task="   ")
        assert result.is_error
        assert "empty" in result.content.lower()

    @pytest.mark.asyncio
    async def test_no_provider_returns_error(self, tmp_path):
        no_provider_ctx = ToolContext(cwd=str(tmp_path), session_id="x")
        result = await SpawnAgentTool().execute(no_provider_ctx, task="do something")
        assert result.is_error
        assert "provider" in result.content.lower()


class TestSpawnAgentExecution:
    @pytest.mark.asyncio
    async def test_spawn_creates_agent_in_pool(self, ctx):
        with patch("src.tools.agent_pool._run_child_agent", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "child output"
            result = await SpawnAgentTool().execute(ctx, task="Research something")

        assert not result.is_error
        assert "agent-" in result.content
        pool = _get_pool(ctx.session_id)
        assert len(pool) == 1

    @pytest.mark.asyncio
    async def test_spawn_respects_max_turns_cap(self, ctx):
        """The tool should clamp max_turns to 50 even if user asks for more."""
        captured_max_turns = None
        original_run = _run_child = None

        async def _fake_run(**kwargs):
            nonlocal captured_max_turns
            captured_max_turns = kwargs.get("max_turns")
            return "done"

        with patch("src.tools.agent_pool._run_child_agent", side_effect=_fake_run):
            result = await SpawnAgentTool().execute(ctx, task="work", max_turns=999)
            # Wait for the background task to run
            pool = _get_pool(ctx.session_id)
            for agent in pool.values():
                if agent._task_handle:
                    await asyncio.wait_for(agent._task_handle, timeout=5)

        assert captured_max_turns == 50


# ---------------------------------------------------------------------------
# MessageAgentTool
# ---------------------------------------------------------------------------

class TestMessageAgentTool:
    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self, ctx):
        result = await MessageAgentTool().execute(
            ctx, agent_id="nonexistent", message="hello"
        )
        assert result.is_error
        assert "unknown" in result.content.lower()

    @pytest.mark.asyncio
    async def test_message_completed_agent_returns_error(self, ctx):
        pool = _get_pool(ctx.session_id)
        pool["a1"] = ManagedAgent(agent_id="a1", task="t", status=AgentStatus.COMPLETED)
        result = await MessageAgentTool().execute(ctx, agent_id="a1", message="more work")
        assert result.is_error
        assert "completed" in result.content.lower()

    @pytest.mark.asyncio
    async def test_message_running_agent_queues(self, ctx):
        pool = _get_pool(ctx.session_id)
        q = asyncio.Queue()
        pool["a1"] = ManagedAgent(
            agent_id="a1", task="t", status=AgentStatus.RUNNING, _message_queue=q
        )
        result = await MessageAgentTool().execute(ctx, agent_id="a1", message="do more")
        assert not result.is_error
        assert not q.empty()


# ---------------------------------------------------------------------------
# WaitAgentTool
# ---------------------------------------------------------------------------

class TestWaitAgentTool:
    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self, ctx):
        result = await WaitAgentTool().execute(ctx, agent_id="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_wait_completed_agent_returns_output(self, ctx):
        pool = _get_pool(ctx.session_id)
        pool["a1"] = ManagedAgent(
            agent_id="a1", task="t", status=AgentStatus.COMPLETED,
            output=["result data"],
        )
        result = await WaitAgentTool().execute(ctx, agent_id="a1")
        assert not result.is_error
        assert "result data" in result.content

    def test_is_read_only(self):
        assert WaitAgentTool().is_read_only


# ---------------------------------------------------------------------------
# ListAgentsTool
# ---------------------------------------------------------------------------

class TestListAgentsTool:
    @pytest.mark.asyncio
    async def test_empty_pool(self, ctx):
        result = await ListAgentsTool().execute(ctx)
        assert "no agents" in result.content.lower()

    @pytest.mark.asyncio
    async def test_lists_agents(self, ctx):
        pool = _get_pool(ctx.session_id)
        pool["a1"] = ManagedAgent(agent_id="a1", task="task one", status=AgentStatus.RUNNING)
        pool["a2"] = ManagedAgent(agent_id="a2", task="task two", status=AgentStatus.COMPLETED)
        result = await ListAgentsTool().execute(ctx)
        assert "a1" in result.content
        assert "a2" in result.content
        assert "running" in result.content
        assert "completed" in result.content


# ---------------------------------------------------------------------------
# InterruptAgentTool
# ---------------------------------------------------------------------------

class TestInterruptAgentTool:
    @pytest.mark.asyncio
    async def test_unknown_agent_returns_error(self, ctx):
        result = await InterruptAgentTool().execute(ctx, agent_id="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_already_completed_is_noop(self, ctx):
        pool = _get_pool(ctx.session_id)
        pool["a1"] = ManagedAgent(agent_id="a1", task="t", status=AgentStatus.COMPLETED)
        result = await InterruptAgentTool().execute(ctx, agent_id="a1")
        assert not result.is_error
        assert "already" in result.content.lower()

    @pytest.mark.asyncio
    async def test_interrupt_running_agent(self, ctx):
        pool = _get_pool(ctx.session_id)

        async def _never_finish():
            await asyncio.sleep(9999)

        task = asyncio.create_task(_never_finish())
        pool["a1"] = ManagedAgent(
            agent_id="a1", task="t", status=AgentStatus.RUNNING,
            _task_handle=task,
        )
        result = await InterruptAgentTool().execute(ctx, agent_id="a1")
        assert not result.is_error
        assert pool["a1"].status == AgentStatus.INTERRUPTED


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_all_pool_tools_in_default_registry(self):
        from src.tools import default_registry
        reg = default_registry()
        for name in ["spawn_agent", "message_agent", "wait_agent", "list_agents", "interrupt_agent"]:
            assert reg.get(name) is not None, f"{name} not in registry"

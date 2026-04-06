"""Tests for background task control tools."""
from __future__ import annotations

import asyncio

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.background import (
    BackgroundTask,
    TaskOutputTool,
    TaskStartTool,
    TaskStatusTool,
    TaskStopTool,
    TaskStatus,
    _TASK_POOLS,
    _get_tasks,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-bg",
    )


@pytest.fixture(autouse=True)
def _clear_pools():
    _TASK_POOLS.clear()
    yield
    # Kill any remaining processes
    for pool in _TASK_POOLS.values():
        for task in pool.values():
            if task._process and task._process.returncode is None:
                try:
                    task._process.kill()
                except Exception:
                    pass
            if task._task_handle and not task._task_handle.done():
                task._task_handle.cancel()
    _TASK_POOLS.clear()


# ---------------------------------------------------------------------------
# TaskStartTool
# ---------------------------------------------------------------------------

class TestTaskStartMetadata:
    def test_name(self):
        assert TaskStartTool().name == "task_start"

    def test_not_read_only(self):
        assert not TaskStartTool().is_read_only

    def test_schema_requires_command(self):
        assert "command" in TaskStartTool().input_schema()["required"]


class TestTaskStart:
    @pytest.mark.asyncio
    async def test_empty_command(self, ctx):
        result = await TaskStartTool().execute(ctx, command="   ")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_start_task(self, ctx):
        result = await TaskStartTool().execute(ctx, command="echo hello && sleep 0.1")
        assert not result.is_error
        assert "task-" in result.content
        assert "PID" in result.content
        tasks = _get_tasks(ctx.session_id)
        assert len(tasks) == 1

    @pytest.mark.asyncio
    async def test_start_multiple_tasks(self, ctx):
        await TaskStartTool().execute(ctx, command="sleep 0.1")
        await TaskStartTool().execute(ctx, command="sleep 0.1")
        tasks = _get_tasks(ctx.session_id)
        assert len(tasks) == 2


# ---------------------------------------------------------------------------
# TaskOutputTool
# ---------------------------------------------------------------------------

class TestTaskOutput:
    @pytest.mark.asyncio
    async def test_unknown_task(self, ctx):
        result = await TaskOutputTool().execute(ctx, task_id="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_get_output(self, ctx):
        # Start a fast task
        start_result = await TaskStartTool().execute(ctx, command="echo test_output_line")
        task_id = start_result.content.split(":")[1].strip().split("\n")[0]
        # Wait for it to complete
        await asyncio.sleep(0.5)
        result = await TaskOutputTool().execute(ctx, task_id=task_id)
        assert not result.is_error
        assert "test_output_line" in result.content

    @pytest.mark.asyncio
    async def test_tail_output(self, ctx):
        tasks = _get_tasks(ctx.session_id)
        task = BackgroundTask(
            task_id="t1",
            command="test",
            status=TaskStatus.COMPLETED,
            output=["line1\n", "line2\n", "line3\n"],
        )
        tasks["t1"] = task
        result = await TaskOutputTool().execute(ctx, task_id="t1", tail=1)
        assert "line3" in result.content

    def test_is_read_only(self):
        assert TaskOutputTool().is_read_only


# ---------------------------------------------------------------------------
# TaskStatusTool
# ---------------------------------------------------------------------------

class TestTaskStatus:
    @pytest.mark.asyncio
    async def test_empty(self, ctx):
        result = await TaskStatusTool().execute(ctx)
        assert "no background" in result.content.lower()

    @pytest.mark.asyncio
    async def test_with_tasks(self, ctx):
        await TaskStartTool().execute(ctx, command="sleep 10")
        result = await TaskStatusTool().execute(ctx)
        assert "task-" in result.content
        assert "running" in result.content

    def test_is_read_only(self):
        assert TaskStatusTool().is_read_only


# ---------------------------------------------------------------------------
# TaskStopTool
# ---------------------------------------------------------------------------

class TestTaskStop:
    @pytest.mark.asyncio
    async def test_unknown_task(self, ctx):
        result = await TaskStopTool().execute(ctx, task_id="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_stop_running_task(self, ctx):
        start_result = await TaskStartTool().execute(ctx, command="sleep 999")
        task_id = start_result.content.split(":")[1].strip().split("\n")[0]
        result = await TaskStopTool().execute(ctx, task_id=task_id)
        assert not result.is_error
        assert "stopped" in result.content.lower()

    @pytest.mark.asyncio
    async def test_stop_already_completed(self, ctx):
        tasks = _get_tasks(ctx.session_id)
        tasks["t1"] = BackgroundTask(
            task_id="t1", command="done", status=TaskStatus.COMPLETED,
        )
        result = await TaskStopTool().execute(ctx, task_id="t1")
        assert not result.is_error
        assert "already" in result.content.lower()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestRegistryIntegration:
    def test_background_tools_in_default_registry(self):
        from src.tools import default_registry
        reg = default_registry()
        for name in ["task_start", "task_output", "task_status", "task_stop"]:
            assert reg.get(name) is not None, f"{name} not in registry"

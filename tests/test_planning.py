"""Tests for the structured planning tool."""
from __future__ import annotations

import json

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.planning import (
    PlanModeTool,
    PlanTool,
    _PLAN_STORE,
    get_session_plan,
    is_plan_mode_active,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-plan",
    )


@pytest.fixture
def tool() -> PlanTool:
    return PlanTool()


@pytest.fixture(autouse=True)
def _clear_store():
    _PLAN_STORE.clear()
    yield
    _PLAN_STORE.clear()


SAMPLE_PLAN = json.dumps({
    "title": "Add auth system",
    "phases": [
        {
            "name": "Phase 1: Setup",
            "steps": [
                {"id": "s1", "content": "Create user model"},
                {"id": "s2", "content": "Add auth middleware", "depends_on": ["s1"]},
            ],
        },
        {
            "name": "Phase 2: Testing",
            "steps": [
                {"id": "s3", "content": "Write unit tests", "depends_on": ["s2"]},
            ],
        },
    ],
})


class TestPlanToolMetadata:
    def test_name(self, tool):
        assert tool.name == "plan"

    def test_not_read_only(self, tool):
        assert not tool.is_read_only

    def test_schema_requires_action(self, tool):
        assert "action" in tool.input_schema()["required"]


class TestPlanCreate:
    @pytest.mark.asyncio
    async def test_create_valid_plan(self, tool, ctx):
        result = await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        assert not result.is_error
        assert "Add auth system" in result.content
        assert get_session_plan(ctx.session_id) is not None

    @pytest.mark.asyncio
    async def test_create_no_plan_json(self, tool, ctx):
        result = await tool.execute(ctx, action="create")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_create_invalid_json(self, tool, ctx):
        result = await tool.execute(ctx, action="create", plan="not json")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_create_missing_title(self, tool, ctx):
        result = await tool.execute(ctx, action="create", plan='{"phases": []}')
        assert result.is_error

    @pytest.mark.asyncio
    async def test_create_empty_phases(self, tool, ctx):
        result = await tool.execute(ctx, action="create", plan='{"title": "X", "phases": []}')
        assert result.is_error

    @pytest.mark.asyncio
    async def test_duplicate_step_ids(self, tool, ctx):
        plan = json.dumps({
            "title": "T",
            "phases": [{"name": "P", "steps": [
                {"id": "s1", "content": "a"},
                {"id": "s1", "content": "b"},
            ]}],
        })
        result = await tool.execute(ctx, action="create", plan=plan)
        assert result.is_error
        assert "duplicate" in result.content.lower()

    @pytest.mark.asyncio
    async def test_invalid_dependency(self, tool, ctx):
        plan = json.dumps({
            "title": "T",
            "phases": [{"name": "P", "steps": [
                {"id": "s1", "content": "a", "depends_on": ["nonexistent"]},
            ]}],
        })
        result = await tool.execute(ctx, action="create", plan=plan)
        assert result.is_error
        assert "unknown step" in result.content.lower()


class TestPlanUpdate:
    @pytest.mark.asyncio
    async def test_update_step_status(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        result = await tool.execute(
            ctx, action="update", step_id="s1", step_status="in_progress"
        )
        assert not result.is_error
        assert "◑" in result.content  # in_progress icon

    @pytest.mark.asyncio
    async def test_update_with_note(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        result = await tool.execute(
            ctx, action="update", step_id="s1", note="Started implementation"
        )
        assert not result.is_error
        assert "Started implementation" in result.content

    @pytest.mark.asyncio
    async def test_update_no_active_plan(self, tool, ctx):
        result = await tool.execute(ctx, action="update", step_id="s1", step_status="completed")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_update_unknown_step(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        result = await tool.execute(ctx, action="update", step_id="nope", step_status="completed")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_dependency_check_blocks_start(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        # s2 depends on s1, which is still pending
        result = await tool.execute(
            ctx, action="update", step_id="s2", step_status="in_progress"
        )
        assert result.is_error
        assert "dependency" in result.content.lower()

    @pytest.mark.asyncio
    async def test_dependency_allows_start_after_completion(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        await tool.execute(ctx, action="update", step_id="s1", step_status="completed")
        result = await tool.execute(
            ctx, action="update", step_id="s2", step_status="in_progress"
        )
        assert not result.is_error


class TestPlanStatus:
    @pytest.mark.asyncio
    async def test_status_no_plan(self, tool, ctx):
        result = await tool.execute(ctx, action="status")
        assert not result.is_error
        assert "no active plan" in result.content.lower()

    @pytest.mark.asyncio
    async def test_status_with_plan(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        result = await tool.execute(ctx, action="status")
        assert "Add auth system" in result.content
        assert "Progress:" in result.content


class TestPlanComplete:
    @pytest.mark.asyncio
    async def test_complete(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        result = await tool.execute(ctx, action="complete")
        assert not result.is_error
        assert "completed" in result.content.lower()

    @pytest.mark.asyncio
    async def test_abandon(self, tool, ctx):
        await tool.execute(ctx, action="create", plan=SAMPLE_PLAN)
        result = await tool.execute(ctx, action="abandon")
        assert not result.is_error
        assert "abandoned" in result.content.lower()


class TestPlanModeTool:
    @pytest.mark.asyncio
    async def test_enable_plan_mode(self, ctx):
        tool = PlanModeTool()
        result = await tool.execute(ctx, mode="on")
        assert not result.is_error
        assert is_plan_mode_active(ctx.session_id)

    @pytest.mark.asyncio
    async def test_disable_plan_mode(self, ctx):
        tool = PlanModeTool()
        await tool.execute(ctx, mode="on")
        result = await tool.execute(ctx, mode="off")
        assert not result.is_error
        assert not is_plan_mode_active(ctx.session_id)

    @pytest.mark.asyncio
    async def test_invalid_mode(self, ctx):
        result = await PlanModeTool().execute(ctx, mode="maybe")
        assert result.is_error

    def test_is_read_only(self):
        assert PlanModeTool().is_read_only


class TestUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self, tool, ctx):
        result = await tool.execute(ctx, action="explode")
        assert result.is_error


class TestRegistryIntegration:
    def test_plan_tools_in_default_registry(self):
        from src.tools import default_registry
        reg = default_registry()
        assert reg.get("plan") is not None
        assert reg.get("plan_mode") is not None

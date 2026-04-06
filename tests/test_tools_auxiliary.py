"""Tests for src/tools/auxiliary — TodoWriteTool, AskUserQuestionTool."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.auxiliary import (
    AskUserQuestionTool,
    TodoWriteTool,
    _render_todos,
    _TODO_STORE,
    get_session_todos,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO, session_id="test-session")


@pytest.fixture(autouse=True)
def clear_store():
    """Reset the global todo store between tests."""
    _TODO_STORE.clear()
    yield
    _TODO_STORE.clear()


# ── TodoWriteTool ─────────────────────────────────────────────────────────────

class TestTodoWriteTool:
    @property
    def tool(self):
        return TodoWriteTool()

    def test_name(self):
        assert self.tool.name == "todo_write"

    def test_is_not_read_only(self):
        assert self.tool.is_read_only is False

    def test_input_schema_has_todos_field(self):
        schema = self.tool.input_schema()
        assert "todos" in schema["properties"]

    @pytest.mark.asyncio
    async def test_stores_valid_todos(self, ctx):
        todos = json.dumps([
            {"id": "1", "content": "Do something", "status": "pending", "priority": "high"}
        ])
        result = await self.tool.execute(ctx, todos=todos)
        assert not result.is_error
        stored = get_session_todos(ctx.session_id)
        assert len(stored) == 1
        assert stored[0]["content"] == "Do something"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self, ctx):
        result = await self.tool.execute(ctx, todos="NOT JSON {{{")
        assert result.is_error
        assert "Invalid JSON" in result.content

    @pytest.mark.asyncio
    async def test_non_array_returns_error(self, ctx):
        result = await self.tool.execute(ctx, todos='{"key": "value"}')
        assert result.is_error
        assert "JSON array" in result.content

    @pytest.mark.asyncio
    async def test_missing_id_returns_error(self, ctx):
        todos = json.dumps([{"content": "x", "status": "pending"}])
        result = await self.tool.execute(ctx, todos=todos)
        assert result.is_error
        assert "'id'" in result.content

    @pytest.mark.asyncio
    async def test_missing_content_returns_error(self, ctx):
        todos = json.dumps([{"id": "1", "status": "pending"}])
        result = await self.tool.execute(ctx, todos=todos)
        assert result.is_error

    @pytest.mark.asyncio
    async def test_invalid_status_returns_error(self, ctx):
        todos = json.dumps([{"id": "1", "content": "x", "status": "done"}])
        result = await self.tool.execute(ctx, todos=todos)
        assert result.is_error
        assert "status" in result.content.lower()

    @pytest.mark.asyncio
    async def test_invalid_priority_returns_error(self, ctx):
        todos = json.dumps([{"id": "1", "content": "x", "status": "pending", "priority": "critical"}])
        result = await self.tool.execute(ctx, todos=todos)
        assert result.is_error
        assert "priority" in result.content.lower()

    @pytest.mark.asyncio
    async def test_empty_list_clears_todos(self, ctx):
        todos = json.dumps([{"id": "1", "content": "x", "status": "pending"}])
        await self.tool.execute(ctx, todos=todos)
        result = await self.tool.execute(ctx, todos="[]")
        assert not result.is_error
        assert get_session_todos(ctx.session_id) == []

    @pytest.mark.asyncio
    async def test_replaces_entire_list(self, ctx):
        todos_v1 = json.dumps([{"id": "1", "content": "old", "status": "pending"}])
        todos_v2 = json.dumps([{"id": "2", "content": "new", "status": "in_progress"}])
        await self.tool.execute(ctx, todos=todos_v1)
        await self.tool.execute(ctx, todos=todos_v2)
        stored = get_session_todos(ctx.session_id)
        assert len(stored) == 1
        assert stored[0]["content"] == "new"

    @pytest.mark.asyncio
    async def test_all_valid_statuses_accepted(self, ctx):
        for status in ("pending", "in_progress", "completed"):
            todos = json.dumps([{"id": "1", "content": "x", "status": status}])
            result = await self.tool.execute(ctx, todos=todos)
            assert not result.is_error, f"Status {status!r} should be valid"

    @pytest.mark.asyncio
    async def test_all_valid_priorities_accepted(self, ctx):
        for priority in ("high", "medium", "low"):
            todos = json.dumps([{"id": "1", "content": "x", "status": "pending", "priority": priority}])
            result = await self.tool.execute(ctx, todos=todos)
            assert not result.is_error, f"Priority {priority!r} should be valid"

    @pytest.mark.asyncio
    async def test_output_contains_todo_items(self, ctx):
        todos = json.dumps([
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second task", "status": "completed"},
        ])
        result = await self.tool.execute(ctx, todos=todos)
        assert "First task" in result.content
        assert "Second task" in result.content


# ── get_session_todos ─────────────────────────────────────────────────────────

class TestGetSessionTodos:
    def test_returns_empty_list_for_unknown_session(self):
        assert get_session_todos("unknown-session") == []

    def test_returns_stored_todos(self):
        _TODO_STORE["s1"] = [{"id": "1", "content": "x", "status": "pending"}]
        result = get_session_todos("s1")
        assert len(result) == 1


# ── _render_todos ─────────────────────────────────────────────────────────────

class TestRenderTodos:
    def test_empty_list_message(self):
        assert "empty" in _render_todos([]).lower()

    def test_shows_status_icon(self):
        todos = [{"id": "1", "content": "test", "status": "completed", "priority": "medium"}]
        output = _render_todos(todos)
        assert "●" in output

    def test_shows_content(self):
        todos = [{"id": "1", "content": "My task", "status": "pending", "priority": "high"}]
        output = _render_todos(todos)
        assert "My task" in output

    def test_shows_count(self):
        todos = [
            {"id": "1", "content": "a", "status": "pending", "priority": "low"},
            {"id": "2", "content": "b", "status": "pending", "priority": "low"},
        ]
        output = _render_todos(todos)
        assert "2" in output


# ── AskUserQuestionTool ───────────────────────────────────────────────────────

class TestAskUserQuestionTool:
    @property
    def tool(self):
        return AskUserQuestionTool()

    def test_name(self):
        assert self.tool.name == "ask_user"

    def test_is_not_read_only(self):
        assert self.tool.is_read_only is False

    def test_input_schema_requires_question(self):
        schema = self.tool.input_schema()
        assert "question" in schema["required"]

    @pytest.mark.asyncio
    async def test_returns_user_answer(self, ctx):
        with patch("src.tools.auxiliary._prompt_user", return_value="  my answer  "):
            result = await self.tool.execute(ctx, question="What do you want?")
        assert not result.is_error
        assert "my answer" in result.content

    @pytest.mark.asyncio
    async def test_empty_answer_returns_no_answer_provided(self, ctx):
        with patch("src.tools.auxiliary._prompt_user", return_value="   "):
            result = await self.tool.execute(ctx, question="What?")
        assert not result.is_error
        assert "no answer" in result.content.lower()

    @pytest.mark.asyncio
    async def test_eof_returns_error(self, ctx):
        with patch("src.tools.auxiliary._prompt_user", side_effect=EOFError):
            result = await self.tool.execute(ctx, question="What?")
        assert result.is_error
        assert "cancelled" in result.content.lower()

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_returns_error(self, ctx):
        with patch("src.tools.auxiliary._prompt_user", side_effect=KeyboardInterrupt):
            result = await self.tool.execute(ctx, question="What?")
        assert result.is_error

"""Tests for the worktree isolation tool."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.worktree import (
    WorktreeCreateTool,
    WorktreeListTool,
    WorktreeMergeTool,
    WorktreeRemoveTool,
    _WORKTREES,
    WorktreeInfo,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-wt",
    )


@pytest.fixture(autouse=True)
def _clear_worktrees():
    _WORKTREES.clear()
    yield
    _WORKTREES.clear()


class TestWorktreeCreateMetadata:
    def test_name(self):
        assert WorktreeCreateTool().name == "worktree_create"

    def test_not_read_only(self):
        assert not WorktreeCreateTool().is_read_only


class TestWorktreeCreateExecution:
    @pytest.mark.asyncio
    async def test_not_git_repo_returns_error(self, ctx):
        with patch("src.tools.worktree._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ("", 128)
            result = await WorktreeCreateTool().execute(ctx)
        assert result.is_error
        assert "not a git" in result.content.lower()

    @pytest.mark.asyncio
    async def test_create_worktree(self, ctx):
        with patch("src.tools.worktree._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.side_effect = [
                (".git", 0),      # rev-parse
                ("main", 0),      # branch --show-current
                ("Preparing worktree", 0),  # worktree add
            ]
            result = await WorktreeCreateTool().execute(ctx, branch_name="test-branch")
        assert not result.is_error
        assert "zwis-wt-test-branch" in result.content

    @pytest.mark.asyncio
    async def test_auto_generates_branch_name(self, ctx):
        with patch("src.tools.worktree._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.side_effect = [
                (".git", 0),
                ("main", 0),
                ("OK", 0),
            ]
            result = await WorktreeCreateTool().execute(ctx)
        assert not result.is_error
        assert "zwis-wt-" in result.content


class TestWorktreeList:
    def test_is_read_only(self):
        assert WorktreeListTool().is_read_only

    @pytest.mark.asyncio
    async def test_list_empty(self, ctx):
        with patch("src.tools.worktree._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ("", 0)
            result = await WorktreeListTool().execute(ctx)
        assert "no managed" in result.content.lower()

    @pytest.mark.asyncio
    async def test_list_with_worktrees(self, ctx):
        from src.tools.worktree import _get_worktrees
        wts = _get_worktrees(ctx.session_id)
        wts["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            path="/tmp/wt1",
            branch="zwis-wt-test",
            base_branch="main",
        )
        with patch("src.tools.worktree._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ("", 0)
            result = await WorktreeListTool().execute(ctx)
        assert "wt-1" in result.content
        assert "zwis-wt-test" in result.content


class TestWorktreeMerge:
    @pytest.mark.asyncio
    async def test_unknown_worktree(self, ctx):
        result = await WorktreeMergeTool().execute(ctx, worktree_id="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_missing_directory(self, ctx):
        from src.tools.worktree import _get_worktrees
        wts = _get_worktrees(ctx.session_id)
        wts["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            path="/nonexistent/path",
            branch="zwis-wt-test",
            base_branch="main",
        )
        result = await WorktreeMergeTool().execute(ctx, worktree_id="wt-1")
        assert result.is_error
        assert "missing" in result.content.lower()


class TestWorktreeRemove:
    @pytest.mark.asyncio
    async def test_unknown_worktree(self, ctx):
        result = await WorktreeRemoveTool().execute(ctx, worktree_id="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_remove_worktree(self, ctx):
        from src.tools.worktree import _get_worktrees
        wts = _get_worktrees(ctx.session_id)
        wts["wt-1"] = WorktreeInfo(
            worktree_id="wt-1",
            path="/tmp/fake-wt",
            branch="zwis-wt-x",
            base_branch="main",
        )
        with patch("src.tools.worktree._run_git", new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ("", 0)
            result = await WorktreeRemoveTool().execute(ctx, worktree_id="wt-1")
        assert not result.is_error
        assert "wt-1" not in wts


class TestRegistryIntegration:
    def test_worktree_tools_in_default_registry(self):
        from src.tools import default_registry
        reg = default_registry()
        for name in ["worktree_create", "worktree_list", "worktree_merge", "worktree_remove"]:
            assert reg.get(name) is not None, f"{name} not in registry"

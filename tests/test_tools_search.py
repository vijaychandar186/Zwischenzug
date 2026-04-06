"""
Tests for src/tools/search — GlobTool and GrepTool.
"""
from __future__ import annotations

import pytest

from src.tools.search import GlobTool, GrepTool
from src.tools import PermissionMode, ToolContext


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


@pytest.fixture
def workspace(tmp_path):
    """Create a small directory tree for search tests."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    print('hello')\n")
    (tmp_path / "src" / "utils.py").write_text("def helper():\n    return 42\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_hello():\n    assert True\n")
    (tmp_path / "README.md").write_text("# Project\nThis is a test project.\n")
    (tmp_path / "data.json").write_text('{"key": "value"}\n')
    return tmp_path


# ── GlobTool ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGlobTool:
    @pytest.fixture
    def tool(self):
        return GlobTool()

    async def test_is_read_only(self, tool):
        assert tool.is_read_only

    async def test_finds_python_files(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="**/*.py")
        assert not result.is_error
        assert "main.py" in result.content
        assert "utils.py" in result.content
        assert "test_main.py" in result.content

    async def test_finds_only_matching_extension(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="**/*.md")
        assert "README.md" in result.content
        assert ".py" not in result.content

    async def test_no_matches_returns_no_matches_message(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="**/*.nonexistent")
        assert not result.is_error
        assert "no matches" in result.content.lower()

    async def test_custom_path_parameter(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="*.py", path=str(workspace / "src"))
        assert "main.py" in result.content
        assert "utils.py" in result.content

    async def test_nonexistent_directory_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, pattern="*.py", path="/does/not/exist")
        assert result.is_error

    async def test_top_level_pattern(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="*.json")
        assert "data.json" in result.content

    async def test_input_schema_requires_pattern(self, tool):
        schema = tool.input_schema()
        assert "pattern" in schema["required"]


# ── GrepTool ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGrepTool:
    @pytest.fixture
    def tool(self):
        return GrepTool()

    async def test_is_read_only(self, tool):
        assert tool.is_read_only

    async def test_finds_matching_content(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="def main", output_mode="content")
        assert not result.is_error
        assert "main.py" in result.content
        assert "def main" in result.content

    async def test_files_mode_returns_only_paths(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="def ", output_mode="files")
        assert not result.is_error
        # Should have file paths, not code lines
        for line in result.content.splitlines():
            assert line.endswith(".py") or line == ""

    async def test_count_mode_returns_number(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="def ", output_mode="count")
        assert not result.is_error
        assert "matches" in result.content

    async def test_glob_filter_limits_files(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        # Only search test files
        result = await tool.execute(ctx, pattern="def test", glob="**/test_*.py", output_mode="content")
        assert not result.is_error
        assert "test_main.py" in result.content

    async def test_no_matches_returns_no_matches_message(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="DOES_NOT_EXIST_XYZZY")
        assert not result.is_error
        assert "no matches" in result.content.lower()

    async def test_case_insensitive_search(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="PROJECT", ignore_case=True, output_mode="content")
        assert not result.is_error
        assert "README.md" in result.content

    async def test_case_sensitive_misses(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="PROJECT", ignore_case=False, output_mode="files")
        # "project" is lowercase in README.md, so "PROJECT" should not match
        assert "(no matches)" in result.content or not result.content.strip()

    async def test_invalid_regex_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, pattern="[invalid regex")
        assert result.is_error
        assert "regex" in result.content.lower() or "invalid" in result.content.lower()

    async def test_context_lines_included(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="print", context=1, output_mode="content")
        assert not result.is_error
        # Context lines show adjacent lines with '-' separator
        lines = result.content.splitlines()
        assert len(lines) > 1  # More than just the matching line

    async def test_nonexistent_directory_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, pattern="foo", path="/no/such/dir")
        assert result.is_error

    async def test_skips_git_directory(self, tool, workspace):
        ctx = ToolContext(cwd=str(workspace))
        git_dir = workspace / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("SEARCHABLE_SENTINEL")
        result = await tool.execute(ctx, pattern="SEARCHABLE_SENTINEL", output_mode="files")
        # .git should be excluded
        assert ".git" not in result.content

    async def test_input_schema_requires_pattern(self, tool):
        schema = tool.input_schema()
        assert "pattern" in schema["required"]

    @pytest.mark.parametrize("mode", ["content", "files", "count"])
    async def test_all_output_modes_succeed(self, tool, workspace, mode):
        ctx = ToolContext(cwd=str(workspace))
        result = await tool.execute(ctx, pattern="def", output_mode=mode)
        assert not result.is_error

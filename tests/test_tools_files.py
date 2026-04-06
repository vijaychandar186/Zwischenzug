"""
Tests for src/tools/files — FileReadTool, FileWriteTool, FileEditTool.
"""
from __future__ import annotations

import pytest

from src.tools.files import FileEditTool, FileReadTool, FileWriteTool
from src.tools import PermissionMode, ToolContext


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


# ── FileReadTool ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFileReadTool:
    @pytest.fixture
    def tool(self):
        return FileReadTool()

    async def test_is_read_only(self, tool):
        assert tool.is_read_only

    async def test_reads_existing_file(self, tool, ctx, tmp_path):
        (tmp_path / "hello.txt").write_text("hello world")
        result = await tool.execute(ctx, path="hello.txt")
        assert not result.is_error
        assert "hello world" in result.content

    async def test_output_has_line_numbers(self, tool, ctx, tmp_path):
        (tmp_path / "lines.txt").write_text("first\nsecond\nthird\n")
        result = await tool.execute(ctx, path="lines.txt")
        assert "1\t" in result.content
        assert "2\t" in result.content
        assert "3\t" in result.content

    async def test_absolute_path_works(self, tool, ctx, tmp_path):
        p = tmp_path / "abs.txt"
        p.write_text("absolute")
        result = await tool.execute(ctx, path=str(p))
        assert not result.is_error
        assert "absolute" in result.content

    async def test_missing_file_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, path="nonexistent.txt")
        assert result.is_error
        assert "not found" in result.content.lower()

    async def test_directory_path_returns_error(self, tool, ctx, tmp_path):
        result = await tool.execute(ctx, path=str(tmp_path))
        assert result.is_error

    async def test_offset_skips_lines(self, tool, ctx, tmp_path):
        (tmp_path / "f.txt").write_text("a\nb\nc\nd\n")
        result = await tool.execute(ctx, path="f.txt", offset=3)
        assert not result.is_error
        assert "c" in result.content
        # Lines before offset should not appear
        assert "1\t" not in result.content

    async def test_limit_caps_lines(self, tool, ctx, tmp_path):
        content = "\n".join(str(i) for i in range(100))
        (tmp_path / "big.txt").write_text(content)
        result = await tool.execute(ctx, path="big.txt", limit=5)
        lines = [l for l in result.content.splitlines() if l.strip()]
        assert len(lines) <= 5

    async def test_empty_file_returns_empty_marker(self, tool, ctx, tmp_path):
        (tmp_path / "empty.txt").write_text("")
        result = await tool.execute(ctx, path="empty.txt")
        assert not result.is_error
        assert "empty" in result.content.lower()

    async def test_unicode_content(self, tool, ctx, tmp_path):
        (tmp_path / "unicode.txt").write_text("日本語\n中文\n한국어\n")
        result = await tool.execute(ctx, path="unicode.txt")
        assert not result.is_error
        assert "日本語" in result.content

    async def test_input_schema_has_required_path(self, tool):
        schema = tool.input_schema()
        assert "path" in schema["required"]


# ── FileWriteTool ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFileWriteTool:
    @pytest.fixture
    def tool(self):
        return FileWriteTool()

    async def test_is_not_read_only(self, tool):
        assert not tool.is_read_only

    async def test_creates_new_file(self, tool, ctx, tmp_path):
        result = await tool.execute(ctx, path="new.txt", content="brand new")
        assert not result.is_error
        assert (tmp_path / "new.txt").read_text() == "brand new"

    async def test_overwrites_existing_file(self, tool, ctx, tmp_path):
        (tmp_path / "existing.txt").write_text("old content")
        await tool.execute(ctx, path="existing.txt", content="new content")
        assert (tmp_path / "existing.txt").read_text() == "new content"

    async def test_creates_parent_directories(self, tool, ctx, tmp_path):
        result = await tool.execute(ctx, path="a/b/c.txt", content="nested")
        assert not result.is_error
        assert (tmp_path / "a" / "b" / "c.txt").read_text() == "nested"

    async def test_absolute_path_works(self, tool, ctx, tmp_path):
        p = tmp_path / "abs_write.txt"
        result = await tool.execute(ctx, path=str(p), content="abs content")
        assert not result.is_error
        assert p.read_text() == "abs content"

    async def test_reports_bytes_written(self, tool, ctx):
        result = await tool.execute(ctx, path="out.txt", content="hello")
        assert not result.is_error
        assert "5" in result.content  # 5 bytes

    async def test_writes_empty_content(self, tool, ctx, tmp_path):
        await tool.execute(ctx, path="empty.txt", content="")
        assert (tmp_path / "empty.txt").read_text() == ""

    async def test_writes_unicode_content(self, tool, ctx, tmp_path):
        await tool.execute(ctx, path="unicode.txt", content="γεια σου 🌍")
        assert (tmp_path / "unicode.txt").read_text() == "γεια σου 🌍"

    async def test_input_schema_requires_path_and_content(self, tool):
        schema = tool.input_schema()
        assert "path" in schema["required"]
        assert "content" in schema["required"]


# ── FileEditTool ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFileEditTool:
    @pytest.fixture
    def tool(self):
        return FileEditTool()

    async def test_is_not_read_only(self, tool):
        assert not tool.is_read_only

    async def test_replaces_unique_string(self, tool, ctx, tmp_path):
        (tmp_path / "code.py").write_text("def foo():\n    return 1\n")
        result = await tool.execute(ctx, path="code.py", old_string="return 1", new_string="return 42")
        assert not result.is_error
        assert (tmp_path / "code.py").read_text() == "def foo():\n    return 42\n"

    async def test_old_string_not_found_returns_error(self, tool, ctx, tmp_path):
        (tmp_path / "f.py").write_text("hello world")
        result = await tool.execute(ctx, path="f.py", old_string="not here", new_string="x")
        assert result.is_error
        assert "not found" in result.content.lower()

    async def test_ambiguous_string_returns_error(self, tool, ctx, tmp_path):
        (tmp_path / "f.py").write_text("foo foo foo")
        result = await tool.execute(ctx, path="f.py", old_string="foo", new_string="bar")
        assert result.is_error
        assert "3 times" in result.content or "times" in result.content

    async def test_missing_file_returns_error(self, tool, ctx):
        result = await tool.execute(ctx, path="missing.py", old_string="x", new_string="y")
        assert result.is_error
        assert "not found" in result.content.lower()

    async def test_only_first_occurrence_is_not_applied(self, tool, ctx, tmp_path):
        """Ambiguous match → error, not partial replacement."""
        (tmp_path / "f.txt").write_text("cat cat cat")
        result = await tool.execute(ctx, path="f.txt", old_string="cat", new_string="dog")
        assert result.is_error
        # File should be unchanged
        assert (tmp_path / "f.txt").read_text() == "cat cat cat"

    async def test_multiline_replacement(self, tool, ctx, tmp_path):
        code = "def greet():\n    print('hello')\n    print('world')\n"
        (tmp_path / "greet.py").write_text(code)
        result = await tool.execute(
            ctx, path="greet.py",
            old_string="    print('hello')\n    print('world')",
            new_string="    print('hi there')",
        )
        assert not result.is_error
        updated = (tmp_path / "greet.py").read_text()
        assert "hi there" in updated
        assert "hello" not in updated

    async def test_reports_replacement_count(self, tool, ctx, tmp_path):
        (tmp_path / "f.txt").write_text("unique string here")
        result = await tool.execute(ctx, path="f.txt", old_string="unique string", new_string="replaced")
        assert not result.is_error
        assert "1" in result.content

    async def test_input_schema_requires_all_three_fields(self, tool):
        schema = tool.input_schema()
        assert "path" in schema["required"]
        assert "old_string" in schema["required"]
        assert "new_string" in schema["required"]

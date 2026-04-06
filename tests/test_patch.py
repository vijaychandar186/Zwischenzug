"""Tests for the native patch editing tool."""
from __future__ import annotations

import os

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.patch import ApplyPatchTool, _parse_unified_diff


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


@pytest.fixture
def tool() -> ApplyPatchTool:
    return ApplyPatchTool()


class TestApplyPatchMetadata:
    def test_name(self, tool):
        assert tool.name == "apply_patch"

    def test_not_read_only(self, tool):
        assert not tool.is_read_only

    def test_schema_requires_patch(self, tool):
        assert "patch" in tool.input_schema()["required"]


class TestPatchParsing:
    def test_parse_simple_diff(self):
        diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 line 1
-old line
+new line
 line 3
"""
        patches = _parse_unified_diff(diff)
        assert len(patches) == 1
        assert patches[0]["path"] == "foo.py"
        assert len(patches[0]["hunks"]) == 1

    def test_parse_multi_file_diff(self):
        diff = """\
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-old
+new
--- a/b.py
+++ b/b.py
@@ -1,1 +1,1 @@
-old2
+new2
"""
        patches = _parse_unified_diff(diff)
        assert len(patches) == 2

    def test_parse_new_file(self):
        diff = """\
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,2 @@
+line 1
+line 2
"""
        patches = _parse_unified_diff(diff)
        assert len(patches) == 1
        assert patches[0]["is_new_file"]


class TestPatchExecution:
    @pytest.mark.asyncio
    async def test_empty_patch(self, tool, ctx):
        result = await tool.execute(ctx, patch="   ")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_apply_simple_patch(self, tool, ctx):
        # Create target file
        filepath = os.path.join(ctx.cwd, "test.py")
        with open(filepath, "w") as f:
            f.write("line 1\nold line\nline 3\n")

        patch = """\
--- a/test.py
+++ b/test.py
@@ -1,3 +1,3 @@
 line 1
-old line
+new line
 line 3
"""
        result = await tool.execute(ctx, patch=patch)
        assert not result.is_error
        assert "1/1" in result.content

        with open(filepath) as f:
            content = f.read()
        assert "new line" in content
        assert "old line" not in content

    @pytest.mark.asyncio
    async def test_apply_add_lines(self, tool, ctx):
        filepath = os.path.join(ctx.cwd, "add.py")
        with open(filepath, "w") as f:
            f.write("line 1\nline 2\n")

        patch = """\
--- a/add.py
+++ b/add.py
@@ -1,2 +1,4 @@
 line 1
+added 1
+added 2
 line 2
"""
        result = await tool.execute(ctx, patch=patch)
        assert not result.is_error

        with open(filepath) as f:
            content = f.read()
        assert "added 1" in content
        assert "added 2" in content

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool, ctx):
        patch = """\
--- a/nonexistent.py
+++ b/nonexistent.py
@@ -1,1 +1,1 @@
-old
+new
"""
        result = await tool.execute(ctx, patch=patch)
        assert result.is_error
        assert "not found" in result.content.lower()

    @pytest.mark.asyncio
    async def test_create_new_file(self, tool, ctx):
        patch = """\
--- /dev/null
+++ b/brand_new.py
@@ -0,0 +1,3 @@
+#!/usr/bin/env python
+print("hello")
+# end
"""
        result = await tool.execute(ctx, patch=patch)
        assert not result.is_error

        filepath = os.path.join(ctx.cwd, "brand_new.py")
        assert os.path.exists(filepath)
        with open(filepath) as f:
            content = f.read()
        assert 'print("hello")' in content

    @pytest.mark.asyncio
    async def test_context_mismatch_fails(self, tool, ctx):
        filepath = os.path.join(ctx.cwd, "mismatch.py")
        with open(filepath, "w") as f:
            f.write("totally different content\n")

        patch = """\
--- a/mismatch.py
+++ b/mismatch.py
@@ -1,1 +1,1 @@
-expected line that doesn't exist
+replacement
"""
        result = await tool.execute(ctx, patch=patch)
        assert result.is_error


class TestRegistryIntegration:
    def test_in_default_registry(self):
        from src.tools import default_registry
        assert default_registry().get("apply_patch") is not None

"""Tests for the NotebookEdit tool."""
from __future__ import annotations

import json
import os

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.notebook import NotebookEditTool


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(cwd=str(tmp_path), permission_mode=PermissionMode.AUTO)


@pytest.fixture
def tool() -> NotebookEditTool:
    return NotebookEditTool()


def _make_notebook(path: str, cells: list[dict] | None = None) -> str:
    """Create a minimal .ipynb file."""
    nb = {
        "cells": cells or [
            {
                "cell_type": "code",
                "metadata": {},
                "source": ["print('hello')\n"],
                "execution_count": 1,
                "outputs": [],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Title\n"],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.10.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    with open(path, "w") as f:
        json.dump(nb, f)
    return path


class TestNotebookEditMetadata:
    def test_name(self, tool):
        assert tool.name == "notebook_edit"

    def test_not_read_only(self, tool):
        assert not tool.is_read_only

    def test_schema_requires_path_and_action(self, tool):
        schema = tool.input_schema()
        assert "path" in schema["required"]
        assert "action" in schema["required"]


class TestNotebookRead:
    @pytest.mark.asyncio
    async def test_read_notebook(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(ctx, path=nb_path, action="read")
        assert not result.is_error
        assert "2 cells" in result.content
        assert "[0] code" in result.content
        assert "[1] markdown" in result.content

    @pytest.mark.asyncio
    async def test_read_nonexistent(self, tool, ctx):
        result = await tool.execute(ctx, path="nope.ipynb", action="read")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_read_invalid_json(self, tool, ctx):
        bad = os.path.join(ctx.cwd, "bad.ipynb")
        with open(bad, "w") as f:
            f.write("not json")
        result = await tool.execute(ctx, path=bad, action="read")
        assert result.is_error


class TestNotebookInsert:
    @pytest.mark.asyncio
    async def test_insert_code_cell(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="insert",
            cell_index=1, cell_type="code", content="x = 42",
        )
        assert not result.is_error
        assert "3 cells" in result.content

    @pytest.mark.asyncio
    async def test_insert_at_end(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="insert",
            cell_type="markdown", content="## End",
        )
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_insert_creates_new_notebook(self, tool, ctx):
        nb_path = os.path.join(ctx.cwd, "new.ipynb")
        result = await tool.execute(
            ctx, path=nb_path, action="insert",
            cell_type="code", content="print('new')",
        )
        assert not result.is_error
        assert os.path.exists(nb_path)

    @pytest.mark.asyncio
    async def test_insert_invalid_cell_type(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="insert",
            cell_type="invalid", content="x",
        )
        assert result.is_error


class TestNotebookReplace:
    @pytest.mark.asyncio
    async def test_replace_cell(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="replace",
            cell_index=0, content="print('replaced')",
        )
        assert not result.is_error

        # Verify content changed
        with open(nb_path) as f:
            nb = json.load(f)
        assert "replaced" in "".join(nb["cells"][0]["source"])

    @pytest.mark.asyncio
    async def test_replace_out_of_range(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="replace", cell_index=99, content="x",
        )
        assert result.is_error

    @pytest.mark.asyncio
    async def test_replace_no_index(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(ctx, path=nb_path, action="replace", content="x")
        assert result.is_error


class TestNotebookDelete:
    @pytest.mark.asyncio
    async def test_delete_cell(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="delete", cell_index=0,
        )
        assert not result.is_error
        assert "1 cells" in result.content

    @pytest.mark.asyncio
    async def test_delete_out_of_range(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(
            ctx, path=nb_path, action="delete", cell_index=99,
        )
        assert result.is_error

    @pytest.mark.asyncio
    async def test_delete_no_index(self, tool, ctx):
        nb_path = _make_notebook(os.path.join(ctx.cwd, "test.ipynb"))
        result = await tool.execute(ctx, path=nb_path, action="delete")
        assert result.is_error


class TestRegistryIntegration:
    def test_in_default_registry(self):
        from src.tools import default_registry
        assert default_registry().get("notebook_edit") is not None

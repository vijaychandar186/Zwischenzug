"""
NotebookEdit tool — edit Jupyter notebook cells.

Supports inserting, replacing, and deleting cells by index.
Handles both code and markdown cell types.
"""
from __future__ import annotations

import json
import os
from typing import Any

from . import Tool, ToolContext, ToolOutput


class NotebookEditTool(Tool):
    """Edit Jupyter notebook cells."""

    @property
    def name(self) -> str:
        return "notebook_edit"

    @property
    def description(self) -> str:
        return (
            "Edit Jupyter notebook (.ipynb) cells. Actions:\n"
            "- 'read': Read notebook structure and cell contents\n"
            "- 'insert': Insert a new cell at a given index\n"
            "- 'replace': Replace a cell's content at a given index\n"
            "- 'delete': Delete a cell at a given index\n"
            "Supports 'code' and 'markdown' cell types."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the .ipynb file.",
                },
                "action": {
                    "type": "string",
                    "description": "Action: 'read', 'insert', 'replace', 'delete'.",
                },
                "cell_index": {
                    "type": "integer",
                    "description": "0-based cell index for insert/replace/delete.",
                },
                "cell_type": {
                    "type": "string",
                    "description": "Cell type: 'code' or 'markdown' (default 'code').",
                },
                "content": {
                    "type": "string",
                    "description": "Cell content for insert/replace actions.",
                },
            },
            "required": ["path", "action"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        path = kwargs["path"]
        action = kwargs.get("action", "").strip().lower()

        if not os.path.isabs(path):
            path = os.path.join(ctx.cwd, path)

        if action == "read":
            return self._read(path)
        elif action == "insert":
            return self._insert(path, kwargs)
        elif action == "replace":
            return self._replace(path, kwargs)
        elif action == "delete":
            return self._delete(path, kwargs)
        else:
            return ToolOutput.error(
                f"Unknown action: {action!r}. Use: read, insert, replace, delete."
            )

    def _load_notebook(self, path: str) -> tuple[dict | None, str | None]:
        """Load notebook, returns (data, error_message)."""
        if not os.path.exists(path):
            return None, f"File not found: {path}"
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if "cells" not in data:
                return None, "Not a valid Jupyter notebook (no 'cells' key)."
            return data, None
        except json.JSONDecodeError as exc:
            return None, f"Invalid JSON in notebook: {exc}"

    def _save_notebook(self, path: str, data: dict) -> str | None:
        """Save notebook, returns error message or None."""
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=1, ensure_ascii=False)
                f.write("\n")
            return None
        except Exception as exc:
            return f"Failed to write notebook: {exc}"

    def _make_cell(self, cell_type: str, content: str) -> dict:
        """Create a new notebook cell."""
        source = content.splitlines(keepends=True)
        if source and not source[-1].endswith("\n"):
            source[-1] += "\n"

        cell = {
            "cell_type": cell_type,
            "metadata": {},
            "source": source,
        }
        if cell_type == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        return cell

    def _read(self, path: str) -> ToolOutput:
        data, err = self._load_notebook(path)
        if err:
            return ToolOutput.error(err)

        cells = data["cells"]
        lines = [f"Notebook: {os.path.basename(path)} ({len(cells)} cells)"]
        lines.append(f"Kernel: {data.get('metadata', {}).get('kernelspec', {}).get('display_name', 'unknown')}")
        lines.append("")

        for i, cell in enumerate(cells):
            ctype = cell.get("cell_type", "unknown")
            source = "".join(cell.get("source", []))
            preview = source[:200].replace("\n", "\\n")
            outputs_count = len(cell.get("outputs", []))

            lines.append(f"[{i}] {ctype}")
            lines.append(f"    {preview}")
            if outputs_count:
                lines.append(f"    ({outputs_count} outputs)")
            lines.append("")

        return ToolOutput.success("\n".join(lines))

    def _insert(self, path: str, kwargs: dict) -> ToolOutput:
        data, err = self._load_notebook(path)
        if data is None:
            # Create new notebook if it doesn't exist and path ends with .ipynb
            if err and "not found" in err.lower() and path.endswith(".ipynb"):
                data = {
                    "cells": [],
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
            else:
                return ToolOutput.error(err)

        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            cell_index = len(data["cells"])  # Append by default

        cell_type = kwargs.get("cell_type", "code")
        content = kwargs.get("content", "")

        if cell_type not in ("code", "markdown", "raw"):
            return ToolOutput.error(f"Invalid cell_type: {cell_type!r}")

        new_cell = self._make_cell(cell_type, content)

        cells = data["cells"]
        cell_index = max(0, min(cell_index, len(cells)))
        cells.insert(cell_index, new_cell)

        err = self._save_notebook(path, data)
        if err:
            return ToolOutput.error(err)

        return ToolOutput.success(
            f"Inserted {cell_type} cell at index {cell_index}. "
            f"Notebook now has {len(cells)} cells."
        )

    def _replace(self, path: str, kwargs: dict) -> ToolOutput:
        data, err = self._load_notebook(path)
        if err:
            return ToolOutput.error(err)

        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            return ToolOutput.error("'replace' requires 'cell_index'.")

        cells = data["cells"]
        if cell_index < 0 or cell_index >= len(cells):
            return ToolOutput.error(
                f"cell_index {cell_index} out of range (0-{len(cells) - 1})."
            )

        cell_type = kwargs.get("cell_type") or cells[cell_index].get("cell_type", "code")
        content = kwargs.get("content", "")

        cells[cell_index] = self._make_cell(cell_type, content)

        err = self._save_notebook(path, data)
        if err:
            return ToolOutput.error(err)

        return ToolOutput.success(f"Replaced cell {cell_index} ({cell_type}).")

    def _delete(self, path: str, kwargs: dict) -> ToolOutput:
        data, err = self._load_notebook(path)
        if err:
            return ToolOutput.error(err)

        cell_index = kwargs.get("cell_index")
        if cell_index is None:
            return ToolOutput.error("'delete' requires 'cell_index'.")

        cells = data["cells"]
        if cell_index < 0 or cell_index >= len(cells):
            return ToolOutput.error(
                f"cell_index {cell_index} out of range (0-{len(cells) - 1})."
            )

        removed = cells.pop(cell_index)
        err = self._save_notebook(path, data)
        if err:
            return ToolOutput.error(err)

        return ToolOutput.success(
            f"Deleted {removed.get('cell_type', 'unknown')} cell at index {cell_index}. "
            f"Notebook now has {len(cells)} cells."
        )

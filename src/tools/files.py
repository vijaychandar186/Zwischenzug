"""File tools — read, write, and edit files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import Tool, ToolContext, ToolOutput

MAX_READ_LINES = 2000
MICRO_COMPACT_THRESHOLD = 10_000  # chars


def _resolve(cwd: str, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else Path(cwd) / p


class FileReadTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read a file from disk and return its contents with 1-based line numbers. "
            "Use offset and limit to read a slice of large files."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative file path."},
                "offset": {"type": "integer", "description": "First line to return (1-based, default 1)."},
                "limit": {"type": "integer", "description": f"Max lines to return (default {MAX_READ_LINES})."},
            },
            "required": ["path"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        path_str: str = kwargs["path"]
        offset: int = int(kwargs.get("offset") or 1)
        limit: int = int(kwargs.get("limit") or MAX_READ_LINES)
        offset = max(1, offset)
        limit = max(1, limit)

        resolved = _resolve(ctx.cwd, path_str)
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ToolOutput.error(f"File not found: {path_str}")
        except IsADirectoryError:
            return ToolOutput.error(f"Path is a directory, not a file: {path_str}")
        except PermissionError:
            return ToolOutput.error(f"Permission denied: {path_str}")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Error reading {path_str}: {exc}")

        lines = text.splitlines(keepends=True)
        start = offset - 1
        end = start + limit
        slice_ = lines[start:end]

        numbered = "".join(
            f"{start + i + 1}\t{line}" for i, line in enumerate(slice_)
        )

        if not numbered:
            numbered = "(empty file)"

        if len(numbered) > MICRO_COMPACT_THRESHOLD:
            numbered = numbered[:MICRO_COMPACT_THRESHOLD] + "\n...[truncated]"

        return ToolOutput.success(numbered)


class FileWriteTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file, overwriting it completely if it already exists."

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write."},
                "content": {"type": "string", "description": "Content to write."},
            },
            "required": ["path", "content"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        path_str: str = kwargs["path"]
        content: str = kwargs["content"]

        resolved = _resolve(ctx.cwd, path_str)
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except PermissionError:
            return ToolOutput.error(f"Permission denied: {path_str}")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Error writing {path_str}: {exc}")

        return ToolOutput.success(f"Written {len(content)} bytes to {path_str}")


class FileEditTool(Tool):
    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Replace an exact string in a file. "
            "old_string must appear exactly once in the file. "
            "Fails if old_string is not found or appears multiple times."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit."},
                "old_string": {"type": "string", "description": "Exact text to replace (must be unique in file)."},
                "new_string": {"type": "string", "description": "Replacement text."},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        path_str: str = kwargs["path"]
        old_string: str = kwargs["old_string"]
        new_string: str = kwargs["new_string"]

        resolved = _resolve(ctx.cwd, path_str)
        try:
            original = resolved.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return ToolOutput.error(f"File not found: {path_str}")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Error reading {path_str}: {exc}")

        count = original.count(old_string)
        if count == 0:
            return ToolOutput.error(
                f"old_string not found in {path_str}. "
                "Ensure the string is copied exactly from the file."
            )
        if count > 1:
            return ToolOutput.error(
                f"old_string appears {count} times in {path_str}. "
                "Provide a more specific string to uniquely identify the edit location."
            )

        updated = original.replace(old_string, new_string, 1)
        try:
            resolved.write_text(updated, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Error writing {path_str}: {exc}")

        return ToolOutput.success(f"Replaced 1 occurrence in {path_str}")

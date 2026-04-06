"""Search tools — glob file matching and regex content search."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from . import Tool, ToolContext, ToolOutput

MAX_GLOB_RESULTS = 500
MAX_GREP_LINES = 200


def _resolve_dir(cwd: str, path: str | None) -> Path:
    if not path:
        return Path(cwd)
    p = Path(path)
    return p if p.is_absolute() else Path(cwd) / p


class GlobTool(Tool):
    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
            "Returns matching paths sorted by modification time."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match files against."},
                "path": {"type": "string", "description": "Directory to search in (default: cwd)."},
            },
            "required": ["pattern"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        pattern: str = kwargs["pattern"]
        search_dir = _resolve_dir(ctx.cwd, kwargs.get("path"))

        if not search_dir.is_dir():
            return ToolOutput.error(f"Directory not found: {search_dir}")

        try:
            matches = sorted(
                search_dir.glob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolOutput.error(f"Glob error: {exc}")

        if not matches:
            return ToolOutput.success("(no matches)")

        lines = [str(p) for p in matches[:MAX_GLOB_RESULTS]]
        suffix = f"\n...and {len(matches) - MAX_GLOB_RESULTS} more" if len(matches) > MAX_GLOB_RESULTS else ""
        return ToolOutput.success("\n".join(lines) + suffix)


class GrepTool(Tool):
    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents using a regex pattern. "
            "Output modes: 'content' (matching lines), 'files' (file paths only), 'count' (match counts). "
            "Filter by glob pattern and control context lines."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {"type": "string", "description": "Directory to search in (default: cwd)."},
                "glob": {"type": "string", "description": "Glob filter for files (e.g. '*.py')."},
                "output_mode": {
                    "type": "string",
                    "description": "One of: 'content' (default), 'files', 'count'.",
                },
                "context": {"type": "integer", "description": "Lines of context around each match."},
                "ignore_case": {"type": "boolean", "description": "Case-insensitive search."},
            },
            "required": ["pattern"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        pattern: str = kwargs["pattern"]
        search_dir = _resolve_dir(ctx.cwd, kwargs.get("path"))
        glob_filter: str | None = kwargs.get("glob")
        output_mode: str = (kwargs.get("output_mode") or "content").lower()
        context_lines: int = int(kwargs.get("context") or 0)
        ignore_case: bool = bool(kwargs.get("ignore_case") or False)

        if not search_dir.is_dir():
            return ToolOutput.error(f"Directory not found: {search_dir}")

        try:
            flags = re.IGNORECASE if ignore_case else 0
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return ToolOutput.error(f"Invalid regex: {exc}")

        # Collect files
        if glob_filter:
            files = list(search_dir.rglob(glob_filter))
        else:
            files = [p for p in search_dir.rglob("*") if p.is_file()]

        # Filter out binary-looking files and common non-text dirs
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "target"}
        files = [
            f for f in files
            if f.is_file() and not any(part in skip_dirs for part in f.parts)
        ]

        output_lines: list[str] = []
        matched_files: list[str] = []
        count_total = 0

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue

            lines = text.splitlines()
            file_has_match = False
            file_count = 0

            for lineno, line in enumerate(lines, start=1):
                if regex.search(line):
                    file_has_match = True
                    file_count += 1
                    count_total += 1
                    if output_mode == "content":
                        rel = str(fpath.relative_to(search_dir) if fpath.is_relative_to(search_dir) else fpath)
                        # Context lines before
                        for ci in range(max(0, lineno - 1 - context_lines), lineno - 1):
                            output_lines.append(f"{rel}:{ci+1}-{lines[ci]}")
                        output_lines.append(f"{rel}:{lineno}:{line}")
                        # Context lines after
                        for ci in range(lineno, min(len(lines), lineno + context_lines)):
                            output_lines.append(f"{rel}:{ci+1}-{lines[ci]}")

                        if len(output_lines) >= MAX_GREP_LINES:
                            break

            if file_has_match:
                matched_files.append(str(fpath))

            if len(output_lines) >= MAX_GREP_LINES:
                break

        if output_mode == "files":
            if not matched_files:
                return ToolOutput.success("(no matches)")
            return ToolOutput.success("\n".join(matched_files))

        if output_mode == "count":
            return ToolOutput.success(f"{count_total} matches in {len(matched_files)} files")

        if not output_lines:
            return ToolOutput.success("(no matches)")

        result = "\n".join(output_lines)
        if len(output_lines) >= MAX_GREP_LINES:
            result += f"\n...[results truncated at {MAX_GREP_LINES} lines]"
        return ToolOutput.success(result)

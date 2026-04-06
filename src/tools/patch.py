"""
Native patch editing tool — apply unified diff patches to files.

Supports standard unified diff format with context matching,
multi-file patches, and per-hunk success/failure reporting.
"""
from __future__ import annotations

import os
import re
from typing import Any

from . import Tool, ToolContext, ToolOutput


class ApplyPatchTool(Tool):
    """Apply a unified diff patch to one or more files."""

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Apply a unified diff patch to one or more files. "
            "The patch should be in standard unified diff format "
            "(as produced by 'git diff' or 'diff -u'). "
            "Supports multiple files in one patch. "
            "Reports success/failure per hunk."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": (
                        "The unified diff content. Example:\n"
                        "--- a/src/foo.py\n"
                        "+++ b/src/foo.py\n"
                        "@@ -10,3 +10,4 @@\n"
                        " context line\n"
                        "-old line\n"
                        "+new line\n"
                        "+added line\n"
                        " context line"
                    ),
                },
            },
            "required": ["patch"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        patch_text: str = kwargs["patch"]

        if not patch_text.strip():
            return ToolOutput.error("Patch content cannot be empty.")

        try:
            file_patches = _parse_unified_diff(patch_text)
        except ValueError as exc:
            return ToolOutput.error(f"Failed to parse patch: {exc}")

        if not file_patches:
            return ToolOutput.error("No file patches found in the diff.")

        results = []
        total_hunks = 0
        applied_hunks = 0

        for fp in file_patches:
            file_path = fp["path"]
            if not os.path.isabs(file_path):
                file_path = os.path.join(ctx.cwd, file_path)

            is_new_file = fp.get("is_new_file", False)

            if is_new_file:
                # New file creation
                try:
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    content_lines = []
                    for hunk in fp["hunks"]:
                        total_hunks += 1
                        for line in hunk["lines"]:
                            if line.startswith("+"):
                                content_lines.append(line[1:])
                        applied_hunks += 1
                    with open(file_path, "w") as f:
                        f.write("\n".join(content_lines))
                        if content_lines:
                            f.write("\n")
                    results.append(f"  ✓ Created {fp['path']} ({len(content_lines)} lines)")
                except Exception as exc:
                    results.append(f"  ✗ Failed to create {fp['path']}: {exc}")
                continue

            if not os.path.exists(file_path):
                results.append(f"  ✗ File not found: {fp['path']}")
                total_hunks += len(fp["hunks"])
                continue

            try:
                with open(file_path, "r") as f:
                    original_lines = f.readlines()
            except Exception as exc:
                results.append(f"  ✗ Cannot read {fp['path']}: {exc}")
                total_hunks += len(fp["hunks"])
                continue

            current_lines = list(original_lines)
            offset = 0
            file_ok = True

            for hi, hunk in enumerate(fp["hunks"]):
                total_hunks += 1
                try:
                    current_lines, delta = _apply_hunk(
                        current_lines, hunk, offset
                    )
                    offset += delta
                    applied_hunks += 1
                except PatchError as exc:
                    results.append(
                        f"  ✗ {fp['path']} hunk {hi + 1}: {exc}"
                    )
                    file_ok = False
                    continue

            if file_ok or applied_hunks > 0:
                try:
                    with open(file_path, "w") as f:
                        f.writelines(current_lines)
                    results.append(
                        f"  ✓ {fp['path']} "
                        f"({sum(1 for h in fp['hunks'])} hunks)"
                    )
                except Exception as exc:
                    results.append(f"  ✗ Failed to write {fp['path']}: {exc}")

        summary = f"Patch applied: {applied_hunks}/{total_hunks} hunks succeeded.\n"
        summary += "\n".join(results)

        if applied_hunks < total_hunks:
            return ToolOutput(content=summary, is_error=True)
        return ToolOutput.success(summary)


# ---------------------------------------------------------------------------
# Patch parsing
# ---------------------------------------------------------------------------

class PatchError(Exception):
    pass


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_unified_diff(text: str) -> list[dict]:
    """Parse unified diff into a list of file patches with hunks."""
    file_patches: list[dict] = []
    lines = text.splitlines(keepends=True)
    i = 0

    while i < len(lines):
        line = lines[i]

        # Look for --- a/path or --- /dev/null
        if line.startswith("--- "):
            old_path = _strip_prefix(line[4:].strip())
            i += 1
            if i >= len(lines) or not lines[i].startswith("+++ "):
                continue
            new_path = _strip_prefix(lines[i][4:].strip())
            i += 1

            is_new_file = old_path == "/dev/null"
            path = new_path if not is_new_file else new_path

            hunks: list[dict] = []
            while i < len(lines):
                m = _HUNK_HEADER.match(lines[i])
                if m:
                    old_start = int(m.group(1))
                    old_count = int(m.group(2)) if m.group(2) else 1
                    new_start = int(m.group(3))
                    new_count = int(m.group(4)) if m.group(4) else 1
                    i += 1

                    hunk_lines: list[str] = []
                    while i < len(lines):
                        hl = lines[i]
                        if hl.startswith(("--- ", "+++ ")) or _HUNK_HEADER.match(hl):
                            break
                        if hl.startswith((" ", "+", "-", "\\")):
                            hunk_lines.append(hl.rstrip("\n"))
                        elif hl.strip() == "":
                            hunk_lines.append(" ")
                        else:
                            break
                        i += 1

                    hunks.append({
                        "old_start": old_start,
                        "old_count": old_count,
                        "new_start": new_start,
                        "new_count": new_count,
                        "lines": hunk_lines,
                    })
                else:
                    break

            file_patches.append({
                "path": path,
                "is_new_file": is_new_file,
                "hunks": hunks,
            })
        else:
            i += 1

    return file_patches


def _strip_prefix(path: str) -> str:
    """Strip a/ or b/ prefix from diff paths."""
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _apply_hunk(lines: list[str], hunk: dict, offset: int) -> tuple[list[str], int]:
    """Apply a single hunk to file lines. Returns (new_lines, line_count_delta)."""
    target_line = hunk["old_start"] - 1 + offset  # 0-indexed

    # Collect old (context + removed) and new (context + added) lines
    old_lines: list[str] = []
    new_lines: list[str] = []

    for hl in hunk["lines"]:
        if hl.startswith("\\"):
            continue  # "No newline at end of file" marker
        if hl.startswith(" "):
            old_lines.append(hl[1:])
            new_lines.append(hl[1:])
        elif hl.startswith("-"):
            old_lines.append(hl[1:])
        elif hl.startswith("+"):
            new_lines.append(hl[1:])

    # Try exact match first, then fuzzy search nearby
    match_pos = _find_match(lines, old_lines, target_line)
    if match_pos is None:
        raise PatchError(
            f"Cannot find context match at line {target_line + 1} "
            f"(looking for {len(old_lines)} lines)"
        )

    # Replace the matched section
    result = lines[:match_pos]
    for nl in new_lines:
        result.append(nl + "\n" if not nl.endswith("\n") else nl)
    result.extend(lines[match_pos + len(old_lines):])

    delta = len(new_lines) - len(old_lines)
    return result, delta


def _find_match(
    lines: list[str], pattern: list[str], target: int, fuzz: int = 3
) -> int | None:
    """Find where pattern matches in lines, starting near target with fuzz range."""
    if not pattern:
        return target if 0 <= target <= len(lines) else None

    def _matches_at(pos: int) -> bool:
        if pos < 0 or pos + len(pattern) > len(lines):
            return False
        for pl, fl in zip(pattern, lines[pos:]):
            if pl.rstrip("\n") != fl.rstrip("\n"):
                return False
        return True

    # Exact position
    if _matches_at(target):
        return target

    # Search nearby
    for delta in range(1, fuzz + 1):
        if _matches_at(target + delta):
            return target + delta
        if _matches_at(target - delta):
            return target - delta

    return None

"""
Worktree isolation tool — git worktree management for safe experimentation.

Creates temporary worktree branches, runs work in isolation,
and merges results back or discards them.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.worktree")

# Session-scoped worktree tracking
_WORKTREES: dict[str, dict[str, "WorktreeInfo"]] = {}


@dataclass
class WorktreeInfo:
    """Tracks a managed worktree."""
    worktree_id: str
    path: str
    branch: str
    base_branch: str
    created_at: float = field(default_factory=time.time)


def _get_worktrees(session_id: str) -> dict[str, WorktreeInfo]:
    if session_id not in _WORKTREES:
        _WORKTREES[session_id] = {}
    return _WORKTREES[session_id]


async def _run_git(cmd: str, cwd: str) -> tuple[str, int]:
    """Run a git command and return (output, returncode)."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace").strip(), proc.returncode


class WorktreeCreateTool(Tool):
    """Create a git worktree for isolated work."""

    @property
    def name(self) -> str:
        return "worktree_create"

    @property
    def description(self) -> str:
        return (
            "Create a temporary git worktree for isolated experimentation. "
            "The worktree is a separate working directory on a new branch, "
            "so changes don't affect the main checkout. Returns the worktree path "
            "and branch name."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "branch_name": {
                    "type": "string",
                    "description": (
                        "Name for the worktree branch (default: auto-generated). "
                        "Will be prefixed with 'zwis-wt-' if not already."
                    ),
                },
                "base_ref": {
                    "type": "string",
                    "description": "Git ref to base the worktree on (default: HEAD).",
                },
            },
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        branch_name = kwargs.get("branch_name", "").strip()
        base_ref = kwargs.get("base_ref", "HEAD").strip()

        # Verify we're in a git repo
        _, rc = await _run_git("git rev-parse --git-dir", ctx.cwd)
        if rc != 0:
            return ToolOutput.error("Not a git repository.")

        if not branch_name:
            branch_name = f"zwis-wt-{uuid.uuid4().hex[:8]}"
        elif not branch_name.startswith("zwis-wt-"):
            branch_name = f"zwis-wt-{branch_name}"

        # Get current branch as base
        current_branch, _ = await _run_git("git branch --show-current", ctx.cwd)
        if not current_branch:
            current_branch = "HEAD"

        # Create worktree directory
        wt_dir = os.path.join(ctx.cwd, ".zwis", "worktrees", branch_name)
        os.makedirs(os.path.dirname(wt_dir), exist_ok=True)

        # Create the worktree
        out, rc = await _run_git(
            f"git worktree add -b {branch_name} {wt_dir} {base_ref}",
            ctx.cwd,
        )
        if rc != 0:
            return ToolOutput.error(f"Failed to create worktree: {out}")

        wt_id = f"wt-{uuid.uuid4().hex[:8]}"
        info = WorktreeInfo(
            worktree_id=wt_id,
            path=wt_dir,
            branch=branch_name,
            base_branch=current_branch,
        )
        _get_worktrees(ctx.session_id)[wt_id] = info

        return ToolOutput.success(
            f"Worktree created:\n"
            f"  ID: {wt_id}\n"
            f"  Path: {wt_dir}\n"
            f"  Branch: {branch_name}\n"
            f"  Based on: {base_ref}\n\n"
            f"Run commands with cwd={wt_dir} to work in isolation."
        )


class WorktreeListTool(Tool):
    """List all managed worktrees."""

    @property
    def name(self) -> str:
        return "worktree_list"

    @property
    def description(self) -> str:
        return "List all git worktrees managed by this session."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        worktrees = _get_worktrees(ctx.session_id)

        if not worktrees:
            return ToolOutput.success("No managed worktrees.")

        # Also get git's view
        out, _ = await _run_git("git worktree list --porcelain", ctx.cwd)

        lines = [f"Managed worktrees ({len(worktrees)}):"]
        for wt in worktrees.values():
            elapsed = time.time() - wt.created_at
            exists = os.path.isdir(wt.path)
            lines.append(
                f"  {wt.worktree_id}  [{wt.branch}]  "
                f"{'exists' if exists else 'MISSING'}  "
                f"{elapsed:.0f}s old  — {wt.path}"
            )

        return ToolOutput.success("\n".join(lines))


class WorktreeMergeTool(Tool):
    """Merge a worktree branch back and clean up."""

    @property
    def name(self) -> str:
        return "worktree_merge"

    @property
    def description(self) -> str:
        return (
            "Merge a worktree's changes back into the base branch and clean up. "
            "Commits any uncommitted changes first, then merges."
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "worktree_id": {
                    "type": "string",
                    "description": "The worktree ID to merge.",
                },
                "commit_message": {
                    "type": "string",
                    "description": "Commit message for uncommitted changes (if any).",
                },
            },
            "required": ["worktree_id"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        wt_id = kwargs["worktree_id"]
        commit_msg = kwargs.get("commit_message", "Worktree changes")

        worktrees = _get_worktrees(ctx.session_id)
        wt = worktrees.get(wt_id)
        if wt is None:
            return ToolOutput.error(f"Unknown worktree: {wt_id}")

        if not os.path.isdir(wt.path):
            del worktrees[wt_id]
            return ToolOutput.error(f"Worktree directory missing: {wt.path}")

        # Check for uncommitted changes and commit them
        status, _ = await _run_git("git status --porcelain", wt.path)
        if status.strip():
            await _run_git("git add -A", wt.path)
            out, rc = await _run_git(
                f'git commit -m "{commit_msg}"', wt.path
            )
            if rc != 0:
                return ToolOutput.error(f"Failed to commit in worktree: {out}")

        # Merge into base branch
        out, rc = await _run_git(
            f"git merge {wt.branch} --no-edit", ctx.cwd
        )
        if rc != 0:
            return ToolOutput.error(
                f"Merge failed (may have conflicts):\n{out}\n\n"
                f"Resolve manually, then use worktree_remove to clean up."
            )

        # Clean up worktree
        await _run_git(f"git worktree remove {wt.path} --force", ctx.cwd)
        await _run_git(f"git branch -d {wt.branch}", ctx.cwd)
        del worktrees[wt_id]

        return ToolOutput.success(
            f"Worktree {wt_id} merged into {wt.base_branch} and cleaned up."
        )


class WorktreeRemoveTool(Tool):
    """Discard a worktree without merging."""

    @property
    def name(self) -> str:
        return "worktree_remove"

    @property
    def description(self) -> str:
        return "Remove a worktree and its branch without merging changes."

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "worktree_id": {
                    "type": "string",
                    "description": "The worktree ID to remove.",
                },
            },
            "required": ["worktree_id"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        wt_id = kwargs["worktree_id"]

        worktrees = _get_worktrees(ctx.session_id)
        wt = worktrees.get(wt_id)
        if wt is None:
            return ToolOutput.error(f"Unknown worktree: {wt_id}")

        # Remove worktree
        if os.path.isdir(wt.path):
            await _run_git(f"git worktree remove {wt.path} --force", ctx.cwd)

        # Delete branch
        await _run_git(f"git branch -D {wt.branch}", ctx.cwd)

        del worktrees[wt_id]
        return ToolOutput.success(
            f"Worktree {wt_id} ({wt.branch}) removed and discarded."
        )

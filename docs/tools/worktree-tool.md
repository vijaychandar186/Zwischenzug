# Worktree Isolation Tool

## Overview

The worktree system (`src/tools/worktree.py`) provides git worktree management for safe experimentation. It creates temporary branches in isolated working directories, letting the agent make changes without affecting the main checkout.

---

## Tools

### `worktree_create`

Create a temporary git worktree.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `branch_name` | string | No | auto-generated | Branch name (auto-prefixed with `zwis-wt-`) |
| `base_ref` | string | No | HEAD | Git ref to base the worktree on |

### `worktree_list`

List all managed worktrees. Read-only. No parameters.

### `worktree_merge`

Merge a worktree's changes back into the base branch and clean up.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worktree_id` | string | Yes | ID of the worktree to merge |
| `commit_message` | string | No | Commit message for uncommitted changes |

### `worktree_remove`

Remove a worktree and its branch without merging.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `worktree_id` | string | Yes | ID of the worktree to remove |

---

## Workflow

```
1. worktree_create(branch_name="refactor-auth")
   → Creates .zwis/worktrees/zwis-wt-refactor-auth/
   → Returns worktree ID and path

2. bash(command="cd /path/to/worktree && make changes...")

3. worktree_merge(worktree_id="wt-abc123")
   → Commits uncommitted changes
   → Merges into base branch
   → Cleans up worktree and branch

   OR

   worktree_remove(worktree_id="wt-abc123")
   → Discards all changes and cleans up
```

---

## Notes

- Worktrees are stored in `.zwis/worktrees/`
- Branch names are auto-prefixed with `zwis-wt-` to avoid conflicts
- Merges that have conflicts will report the error and leave the worktree intact for manual resolution
- Worktrees are session-scoped — each session tracks its own worktrees

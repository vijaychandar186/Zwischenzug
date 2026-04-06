# Structured Planning Tool

## Overview

The planning system (`src/tools/planning.py`) provides structured implementation plans with phases, steps, dependencies, and plan mode enforcement. It goes beyond the `todo_write` tool by supporting hierarchical organization and dependency tracking.

---

## Tools

### `plan`

Create and manage structured implementation plans.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | `create`, `update`, `status`, `complete`, `abandon` |
| `plan` | string | No | JSON plan structure (for `create`) |
| `step_id` | string | No | Step ID (for `update`) |
| `step_status` | string | No | New status (for `update`) |
| `note` | string | No | Note to attach to step update |

### `plan_mode`

Toggle plan mode programmatically.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `mode` | string | Yes | `on` or `off` |

In plan mode, all write tools are blocked — only read and search tools are available.

---

## Plan Structure

```json
{
  "title": "Add authentication system",
  "phases": [
    {
      "name": "Phase 1: Setup",
      "steps": [
        {"id": "s1", "content": "Create user model"},
        {"id": "s2", "content": "Add auth middleware", "depends_on": ["s1"]}
      ]
    },
    {
      "name": "Phase 2: Testing",
      "steps": [
        {"id": "s3", "content": "Write unit tests", "depends_on": ["s2"]}
      ]
    }
  ]
}
```

---

## Step Statuses

| Status | Icon | Description |
|--------|------|-------------|
| `pending` | ○ | Not yet started |
| `in_progress` | ◑ | Currently working on |
| `completed` | ● | Finished |
| `blocked` | ⊘ | Blocked by dependency or issue |
| `skipped` | — | Intentionally skipped |

---

## Dependency Enforcement

When updating a step to `in_progress`, all steps listed in its `depends_on` array must be `completed`. This prevents out-of-order execution and ensures dependencies are respected.

---

## Plan Mode

Plan mode (`plan_mode(mode='on')`) sets the session to read-only. The LLM can analyze code, search, and plan without making any changes. Call `plan_mode(mode='off')` when ready to implement.

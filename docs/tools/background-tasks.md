# Background Task Control

## Overview

The background task system (`src/tools/background.py`) runs shell commands as background tasks with output streaming, status monitoring, and stop control. Use it for long-running processes like builds, test suites, or servers.

---

## Tools

### `task_start`

Start a command as a background task.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `command` | string | Yes | Shell command to run |

Returns a `task_id` for monitoring.

### `task_output`

Retrieve output from a background task. Read-only.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `task_id` | string | Yes | — | Task ID |
| `tail` | integer | No | all | Only show last N lines |

### `task_status`

List all background tasks and their status. Read-only. No parameters.

### `task_stop`

Stop a running background task. Sends SIGTERM, then SIGKILL if needed.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `task_id` | string | Yes | Task ID to stop |

---

## Task States

| State | Description |
|-------|-------------|
| `running` | Task is actively executing |
| `completed` | Exited with code 0 |
| `failed` | Exited with non-zero code |
| `stopped` | Terminated by task_stop |

---

## Example

```
1. task_start(command="npm run test -- --watch")  → task-abc12345
2. task_status()  → Shows task running, PID, elapsed time
3. task_output(task_id="task-abc12345", tail=20)  → Last 20 lines
4. task_stop(task_id="task-abc12345")  → Stopped
```

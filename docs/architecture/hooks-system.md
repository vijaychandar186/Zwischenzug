# Hooks System

## Overview

Hooks are shell commands that execute in response to lifecycle events during a Zwischenzug session. They provide extensibility without requiring code changes.

---

## Hook Events

| Event | When | Blocking |
|-------|------|----------|
| `PreToolUse` | Before a tool executes | Yes (non-zero exit blocks) |
| `PostToolUse` | After a tool completes | No |
| `PreQuery` | Before sending a message to the LLM | Yes |
| `PostQuery` | After receiving the LLM response | No |
| `SessionStart` | When a session begins | No |
| `SessionEnd` | When a session ends | No |
| `Stop` | When the agent stops | No |

Pre-hooks can block execution by exiting with a non-zero code. Post-hooks never block.

---

## Configuration

Hooks are configured in `.zwis/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash",
        "hooks": [{"type": "command", "command": "echo 'Running: $ZWIS_TOOL_NAME'"}]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "logger -t zwis 'tool completed'"}]
      }
    ],
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "echo 'Session started'"}]
      }
    ]
  }
}
```

### Matcher

The `matcher` field is a glob pattern matched against the tool name. Use `*` to match all tools.

### Hook Timeout

Each hook command has a 10-second timeout. If the command does not complete within that window, it is killed and treated as a failure.

---

## Environment Variables

Hook commands receive context via environment variables:

| Variable | Description |
|----------|-------------|
| `ZWIS_TOOL_NAME` | Name of the tool being executed |
| `ZWIS_SESSION_ID` | Current session identifier |
| `ZWIS_CWD` | Current working directory |
| `ZWIS_HOOK_EVENT` | The hook event type (PreToolUse, PostToolUse, etc.) |

---

## Integration with Agent

The hook runner is called from `src/core/agent.py` at the appropriate points in the agent loop:

1. Before tool execution: fire `PreToolUse` hooks
2. If any pre-hook exits non-zero: skip the tool, return error to LLM
3. Execute the tool
4. After tool execution: fire `PostToolUse` hooks (fire-and-forget)

Session-level hooks (`SessionStart`, `SessionEnd`) are fired from the REPL or main entry point.

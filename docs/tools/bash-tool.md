# Bash Tool

## Overview

The `BashTool` (`src/tools/bash.py`) executes shell commands asynchronously with timeout and output constraints.

---

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `command` | string | Yes | — | The shell command to execute |

---

## Behavior

1. Command is validated against permission rules
2. `PreToolUse` hooks are fired (can block execution)
3. Command is executed asynchronously via `asyncio.create_subprocess_shell`
4. stdout and stderr are captured
5. Output is capped at a configurable limit to prevent token overflow
6. Result includes exit code, stdout, and stderr

### Timeout

Commands have a default 30-second timeout. If the command does not complete within the timeout, it is killed and an error is returned.

### Output Cap

Output is truncated if it exceeds the configured maximum length. The truncation message indicates how much output was omitted.

---

## Permission Integration

The bash tool is the most sensitive tool from a permission standpoint:

- In `interactive` mode: every command requires user approval
- In `auto` mode: commands matching allow patterns run automatically; others require approval
- In `deny` mode: all commands are blocked
- Allow/deny rules support glob patterns: `Bash(npm run *)`, `Bash(git *)`

---

## Safety Considerations

- Commands that could be destructive (`rm -rf`, `sudo`, `curl | bash`) should be configured as deny rules
- The tool does not perform AST-level shell analysis — safety relies on the permission layer
- Network-accessing commands work without restriction unless blocked by permissions

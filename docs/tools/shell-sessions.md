# Persistent Shell Sessions

## Overview

The shell session system (`src/tools/shell_session.py`) provides named shell sessions that persist across tool calls. Unlike the `bash` tool which creates a new subprocess per command, shell sessions maintain environment variables, directory changes, and background processes.

---

## Tools

### `shell_create`

Create a new persistent shell session.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_name` | string | Yes | Unique name for the session (e.g., `build`, `test`) |

### `shell_exec`

Execute a command in an existing shell session.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `session_name` | string | Yes | — | Name of the session |
| `command` | string | Yes | — | Command to execute |
| `timeout` | number | No | 30 | Timeout in seconds |

### `shell_list`

List all active shell sessions and their status. Read-only. No parameters.

### `shell_close`

Close and terminate a persistent shell session.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_name` | string | Yes | Name of the session to close |

---

## Use Cases

- **Build environments**: Set up env vars once, run multiple build commands
- **Server management**: Start a dev server and interact with it across turns
- **Multi-step workflows**: `cd` into a directory and run several commands
- **Environment isolation**: Different sessions for different tasks

---

## Example

```
1. shell_create(session_name="dev")
2. shell_exec(session_name="dev", command="cd /app && export NODE_ENV=development")
3. shell_exec(session_name="dev", command="npm run build")
4. shell_exec(session_name="dev", command="npm test")
5. shell_close(session_name="dev")
```

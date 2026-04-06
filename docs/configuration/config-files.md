# Configuration Files

## Overview

The configuration system uses multiple sources merged in priority order. Higher-priority sources override lower-priority ones for the same key.

---

## Configuration Priority

From highest to lowest priority:

1. **CLI flags** — Flags passed at invocation time (`--provider`, `--model`, etc.)
2. **Environment variables** — `ZWISCHENZUG_PROVIDER`, `ZWISCHENZUG_MODEL`, API keys
3. **Project settings** — `.zwis/config.json` (project-specific)
4. **Hardcoded defaults** — Built-in defaults in application code

---

## MCP Configuration (`.zwis/mcp.json`, `~/.zwis/mcp.json`)

MCP server definitions are stored separately from the core agent config:

- Project scope: `.zwis/mcp.json`
- User scope: `~/.zwis/mcp.json`

Project scope overrides user scope when both define the same server name.

Example:

```json
{
  "version": 1,
  "servers": [
    {
      "name": "github",
      "transport": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer ${TOKEN}"
      },
      "enabled": true,
      "timeout_seconds": 30.0,
      "sse_read_timeout_seconds": 300.0
    }
  ]
}
```

Manage these files through the CLI:

```bash
zwis mcp add github --transport http --url https://api.githubcopilot.com/mcp/
zwis mcp list
zwis mcp get github --json
zwis mcp remove github
```

---

## Settings File (`.zwis/settings.json`)

Project-level settings for hooks and permissions:

```json
{
  "hooks": {
    "PreToolUse": [...],
    "PostToolUse": [...]
  },
  "permissions": {
    "allow": ["Bash(git *)"],
    "deny": ["Bash(rm -rf *)"]
  }
}
```

See [hooks-system.md](../architecture/hooks-system.md) and [permission-system.md](../permissions/permission-system.md) for details.

---

## Project Instructions (`ZWISCHENZUG.md`)

If a `ZWISCHENZUG.md` file exists in the project root, its contents are injected into the system prompt. This is the project-level instruction file — equivalent to a project-specific system prompt.

Use it to:
- Define coding conventions for the project
- Specify testing preferences
- Document architecture decisions the agent should know
- Set boundaries on what the agent should or shouldn't do

---

## Runtime Data (`.zwis/`)

The `.zwis/` directory at the project root stores all runtime data:

```
.zwis/
├── graph/
│   ├── graph.json       ← Serialized knowledge graph
│   └── meta.json        ← Build metadata + per-file mtimes
├── knowledge/           ← Generated knowledge files
├── docs/                ← Cached framework documentation
├── mcp.json             ← Project-level MCP server definitions
├── sessions/            ← Saved conversation sessions
├── skills/              ← Project-internal skills
└── settings.json        ← Hooks and permission rules
```

---

## User-Level Configuration

User-level settings are stored in `~/.zwis/`:

```
~/.zwis/
├── mcp.json             ← User-level MCP server definitions
├── settings.json        ← User-level hooks and permissions
├── memory/              ← Persistent memories
│   └── MEMORY.md        ← Memory index
└── skills/              ← User-level personal skills
```

---

## Config Resolution (`src/cli/config.py`)

The `resolve_config()` function in `src/cli/config.py` handles:

1. Parsing CLI arguments
2. Loading `.env` via python-dotenv
3. Reading `.zwis/config.json` if it exists
4. Merging all sources by priority
5. Returning a fully-resolved `AgentConfig` object

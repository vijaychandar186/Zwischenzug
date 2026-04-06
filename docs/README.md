# Zwischenzug — Technical Documentation

Technical documentation for Zwischenzug, a Python-based AI coding agent and Codebase Intelligence Engine powered by LangChain.

---

## Document Map

### System Overview
- [overview.md](overview.md) — Purpose, capabilities, entry points, technology stack, design principles

### Architecture
- [architecture/overview.md](architecture/overview.md) — Layered architecture, main entry point, REPL loop, agent engine, state management
- [architecture/session-lifecycle.md](architecture/session-lifecycle.md) — Session states, storage, restore, resume/continue support
- [architecture/system-prompt.md](architecture/system-prompt.md) — System prompt construction, components, graph context injection
- [architecture/hooks-system.md](architecture/hooks-system.md) — Lifecycle hooks, configuration, hook events, environment variables
- [architecture/model-system.md](architecture/model-system.md) — Provider system, model aliases, Groq/Gemini backends

### Graph Intelligence
- [graph/overview.md](graph/overview.md) — Knowledge graph engine, node/edge types, traversal, visualization
- [graph/learning-engine.md](graph/learning-engine.md) — Repository scanning, AST parsing, framework detection, incremental builds
- [graph/knowledge-files.md](graph/knowledge-files.md) — Generated knowledge files, format, system prompt injection

### Tools
- [tools/overview.md](tools/overview.md) — Tool interface, permission model, execution, tool registry
- [tools/bash-tool.md](tools/bash-tool.md) — BashTool: async execution, timeout, output cap
- [tools/file-tools.md](tools/file-tools.md) — FileRead, FileWrite, FileEdit, Glob, Grep
- [tools/web-tools.md](tools/web-tools.md) — WebFetch (httpx + html2text), WebSearch (DuckDuckGo)
- [tools/browser-tool.md](tools/browser-tool.md) — Browser automation: low-level `browser` tool and autonomous `browser_agent`
- [tools/mcp-tools.md](tools/mcp-tools.md) — MCP server configuration, dynamic tool loading, resource access
- [tools/graph-tools.md](tools/graph-tools.md) — Graph intelligence tools: search, explain, impact, trace, refs, map
- [tools/auxiliary-tools.md](tools/auxiliary-tools.md) — TodoWrite, AskUserQuestion
- [tools/agent-pool.md](tools/agent-pool.md) — Spawn, message, wait, list, interrupt child agents
- [tools/planning-tool.md](tools/planning-tool.md) — Structured implementation planning
- [tools/patch-tool.md](tools/patch-tool.md) — Apply unified diff patches
- [tools/shell-sessions.md](tools/shell-sessions.md) — Persistent named shell sessions
- [tools/sandbox-tool.md](tools/sandbox-tool.md) — Sandbox profiles for isolated execution
- [tools/notebook-tool.md](tools/notebook-tool.md) — Jupyter notebook cell editing
- [tools/worktree-tool.md](tools/worktree-tool.md) — Git worktree isolation
- [tools/background-tasks.md](tools/background-tasks.md) — Background task management
- [tools/plugin-system.md](tools/plugin-system.md) — External plugin management

### Skills
- [skills/overview.md](skills/overview.md) — Skill discovery, loading, precedence, frontmatter format, custom skills

### Games
- [games/overview.md](games/overview.md) — Built-in terminal games, commands, persistence, Flappy Bird behavior

### Permissions
- [permissions/permission-system.md](permissions/permission-system.md) — Permission modes, allow/deny rules, configuration
- [permissions/sandboxing.md](permissions/sandboxing.md) — Sandboxed execution model, isolation boundaries, bash integration

### Memory
- [memory/overview.md](memory/overview.md) — Memory types, persistent storage, MEMORY.md index, system prompt injection

### Configuration
- [configuration/environment.md](configuration/environment.md) — Environment variables, API key configuration
- [configuration/config-files.md](configuration/config-files.md) — Configuration priority, settings schema, ZWISCHENZUG.md project instructions
- [configuration/mcp.md](configuration/mcp.md) — MCP scopes, file formats, CLI management commands

### Development
- [development/plan.md](development/plan.md) — Production upgrade roadmap, architectural principles, phased implementation

---

## Key Behavioral Invariants

1. **Permission layers are independent**: Each permission layer is evaluated independently; any can deny regardless of what other layers return.

2. **Plan mode is absolute**: In plan mode, zero write operations are permitted under any circumstances.

3. **Tool concurrency is conservative**: Write tools are always serialized; parallel execution is only for read-only tools.

4. **Memory is not code**: Memory files store personal, cross-session context — not code patterns, architecture, or anything derivable from the current codebase.

5. **Permission escalation is impossible**: A tool cannot grant itself or other tools higher permissions than the current mode allows.

6. **Provider isolation is strict**: All LLM provider code lives in `src/provider/__init__.py` — no other file imports provider-specific libraries.

7. **Graph tools are read-only**: All knowledge graph tools are read-only and only registered when a graph exists (after `zwis learn`).

8. **Compaction is transparent**: After compaction, the session continues seamlessly; session memory preserves facts that cannot be reconstructed.

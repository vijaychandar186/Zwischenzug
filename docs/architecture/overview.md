# Architecture Overview

## System Layers

The system is organized in a layered hierarchy where data flows downward from user input to the LLM and results flow back up.

```
┌──────────────────────────────────────────────────────────┐
│                    CLI Entry (main.py)                     │
│  Argument parsing, config resolution, session routing     │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                    REPL (cli/repl.py)                      │
│  User input → slash commands or text → system prompt      │
└───────────────────────────┬──────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────┐
│                 Agent Engine (core/agent.py)               │
│  Streaming LLM calls, token counting, tool dispatch       │
└──────────┬────────────────┬────────────────┬─────────────┘
           │                │                │
  ┌────────▼──────┐ ┌───────▼──────┐ ┌──────▼──────────┐
  │  Tool System  │ │    Skills    │ │   Graph Engine  │
  │  (16 tools)   │ │  (11 skills) │ │  (knowledge DB) │
  └───────────────┘ └──────────────┘ └─────────────────┘
           │
┌──────────▼────────────────────────────────────────────────┐
│                    State Management                        │
│              SessionState (core/session.py)                │
└──────────────────────────────────────────────────────────┘
```

---

## Main Entry Point

`src/main.py` is the CLI entry point, registered as both `zwis` and `zwischenzug` console scripts via pyproject.toml.

### Argument Parser

The entry point uses `argparse` with subcommands organized into groups:

- **Agent**: `chat` (REPL), `run` (single prompt)
- **Discovery**: `summary`, `manifest`, `commands`, `tools`, `route`, `bootstrap`
- **Sessions**: `sessions`, `load-session`
- **Graph Intelligence**: `learn`, `map`, `explain`, `trace`, `impact-change`, `knowledge`

### Agent Construction

`_build_agent()` resolves configuration and constructs the agent:

1. Resolve config: CLI flags > env vars > `.zwis/config.json` > defaults
2. Build LLM via `src/provider/__init__.py` (provider-isolated)
3. Create `SessionState` (or restore from `--continue` / `--resume`)
4. Build system prompt (base + ZWISCHENZUG.md + memory + graph context)
5. Register tools (including graph tools if `.zwis/graph/graph.json` exists)
6. Enter REPL or run single prompt

---

## REPL Interactive Loop

`src/cli/repl.py` implements the interactive REPL with readline support.

### Input Processing

1. Read user input with readline (tab completion for slash commands)
2. Check if input starts with `/` — dispatch to slash command handler
3. Otherwise, submit as a user message to the agent engine
4. Stream the response with Rich formatting (colors, panels)
5. Display token stats on completion

### Slash Command Dispatch

Commands are split into:

- **Local commands**: Execute immediately without LLM (`/help`, `/tools`, `/session`, `/clear`, `/save`, `/exit`)
- **Skill commands**: Expand to a prompt template and submit to the agent (`/commit`, `/review`, etc.)
- **State commands**: Toggle agent state (`/plan`, `/auto`, `/compact`)
- **View commands**: Display information (`/status`, `/cost`, `/config`, `/memory`, `/graph`, `/knowledge`)

All skills (builtin + workspace) are auto-registered as slash commands at REPL startup.

---

## Agent Engine

`src/core/agent.py` implements the multi-turn agent loop:

1. Build system prompt via `build_system_prompt()`
2. Stream model response via LangChain
3. Collect `tool_use` blocks from the response
4. Execute tools via the tool orchestrator (respecting permissions)
5. Append `tool_result` messages to conversation history
6. Loop until `end_turn` or `max_turns` reached
7. Fire lifecycle hooks at each stage (PRE_TOOL_USE, POST_TOOL_USE, PRE_QUERY, POST_QUERY)

### Error Handling

The agent classifies errors and applies retry logic:
- Transient errors (rate limits, network): retry with backoff
- Permanent errors (invalid input, auth): surface to user
- Tool errors: append error result and let the LLM recover

### Token Budget

The agent tracks token usage per turn. When approaching the context limit, it can trigger automatic compaction via `src/compact/`.

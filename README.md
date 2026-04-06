# Zwischenzug CLI (Python)

AI coding agent and **Codebase Intelligence Engine** powered by LangChain via LiteLLM.

Builds a full knowledge graph of your repository and uses it to reason about architecture, dependencies, and safe edits — not just code generation.

## Quick Start

```bash
pip install zwischenzug
zwis --init            # interactive provider/model/api-key setup
zwis learn             # scan repo and build knowledge graph
zwis chat              # open REPL with full graph reasoning
```

**With browser automation:**

```bash
pip install "zwischenzug[browser]"
zwis setup-browser     # installs Chromium + VNC packages, starts VNC, launches zwis
# open http://localhost:6080/vnc.html to watch the browser live
```

> `zwis setup-browser` must be run once per session (e.g. after a Codespace restart) to start the VNC stack. Without it, browser tools still work — just headlessly with no visual.

## MCP Support

Zwischenzug can now load tools and resources from MCP servers and expose them directly to the agent in `zwis chat` and `zwis run`.

### Claude Code Equivalence

If you are used to Claude Code's MCP flow, `zwis` is intentionally similar:

```bash
# Claude Code
claude mcp add --transport http sentry https://mcp.sentry.dev/mcp
claude mcp add --transport http github https://api.githubcopilot.com/mcp/

# Zwischenzug
zwis mcp add sentry --transport http --url https://mcp.sentry.dev/mcp
zwis mcp add github --transport http --url https://api.githubcopilot.com/mcp/
```

```bash
# Claude Code
claude mcp add --transport stdio db -- npx -y @bytebase/dbhub \
  --dsn "postgresql://user:pass@host:5432/db"

# Zwischenzug
zwis mcp add db --transport stdio --command npx \
  --arg -y --arg @bytebase/dbhub --arg --dsn --arg "postgresql://user:pass@host:5432/db"
```

What matches:

- Add, list, inspect, and remove MCP servers from the CLI
- Support for `http`, `sse`, and `stdio` transports
- Automatic MCP tool loading into `zwis chat` and `zwis run`
- Natural-language use once the tools are registered

What is different today:

- No `/mcp` REPL status/authentication UI yet
- No built-in browser OAuth helper flow yet
- Config files are `.zwis/mcp.json` and `~/.zwis/mcp.json`, not `.mcp.json`
- CLI syntax uses `--url`, `--command`, and repeated `--arg` flags instead of Claude's positional `-- ...` form

### Configure servers

HTTP / remote MCP:

```bash
zwis mcp add github --transport http --url https://api.githubcopilot.com/mcp/
zwis mcp add sentry --transport http --url https://mcp.sentry.dev/mcp \
  --header "Authorization: Bearer $SENTRY_TOKEN"
```

Stdio / local MCP:

```bash
zwis mcp add db --transport stdio --command npx \
  --arg -y --arg @bytebase/dbhub --arg --dsn --arg "postgresql://user:pass@host:5432/db"
```

Management:

```bash
zwis mcp list
zwis mcp get github --json
zwis mcp remove github
```

Project-scoped servers are stored in `.zwis/mcp.json`. Use `--scope user` to save a server in `~/.zwis/mcp.json` instead.

### Scope Mapping

| Claude Code | Zwischenzug | Stored In | Shared |
|-------------|-------------|-----------|--------|
| `local` | `user` | `~/.zwis/mcp.json` | No |
| `project` | `project` | `.zwis/mcp.json` | Yes |
| `user` | `user` | `~/.zwis/mcp.json` | No |

`zwis` currently supports `project` and `user` scopes.

### Using MCP tools

Once configured, restart `zwis chat` or `zwis run`. MCP tools are registered automatically at startup using names like:

```text
mcp__github__search_issues
mcp__sentry__list_resources
mcp__sentry__read_resource
```

Then ask naturally:

```text
Show me the open GitHub issues labeled bug
Read the MCP resource for the production error dashboard
What are the most common Sentry errors in the last 24 hours?
Show me the schema for the orders table
```

### Sample MCP Servers To Test With

If you want a known-good MCP server to validate your `zwis` setup, these official reference servers are good starting points:

- `Time` — time and timezone conversion capabilities
- `Memory` — good for tools plus persistent state behavior
- `Filesystem` — useful for file/resource access testing
- `Git` — useful for repository-aware tool testing
- `Everything` — broad reference server with prompts, tools, and resources
- `Fetch` — useful for web/content-fetching scenarios

Quick examples:

```bash
# Time (Python-based server)
zwis mcp add time --transport stdio --command uvx \
  --arg mcp-server-time

# Memory
zwis mcp add memory --transport stdio -- npx -y @modelcontextprotocol/server-memory

# Filesystem
zwis mcp add filesystem --transport stdio -- npx -y @modelcontextprotocol/server-filesystem /workspaces/clawdco

# Git (Python-based server)
zwis mcp add git --transport stdio --command uvx \
  --arg mcp-server-git
```

After adding one, test it with:

```bash
zwis mcp list
zwis chat
```

Inside `zwis chat`, run `/tools` and look for names like:

```text
mcp__time__...
mcp__memory__...
mcp__filesystem__...
```

Then ask naturally:

```text
What time is it in Tokyo?
When it's 4 PM in New York, what time is it in London?
What memories are available in the MCP memory server?
List files in the project through the MCP filesystem server
Show me git status through the MCP server
```

If you have `uvx`, `time` is now a valid first test as well:

```bash
zwis mcp add time --transport stdio --command uvx --arg mcp-server-time
```

If you do not have `uvx`, use the Python module form after installing it:

```bash
pip install mcp-server-time
zwis mcp add time --transport stdio --command python --arg -m --arg mcp_server_time
```

`memory` and `filesystem` remain the safest `npx`-based examples from the official MCP examples page.

## Project Layout

```text
src/
├── main.py                  ← CLI entry point (zwis / zwischenzug)
├── provider/                ← LLM factory — single file to edit for new providers
├── core/
│   ├── agent.py             ← multi-turn loop, hooks, retry, graph context injection
│   ├── session.py           ← SessionState, resume/continue support
│   └── system_prompt.py     ← prompt builder (base + ZWISCHENZUG.md + memory + graph)
├── graph/                   ← Knowledge graph engine (pure Python, no external DB)
│   ├── __init__.py          ← GraphEngine — nodes, edges, BFS traversal
│   ├── schema.py            ← NodeType, EdgeType, GraphNode, GraphEdge, Reference
│   ├── storage.py           ← JSON persistence (.zwis/graph/graph.json + meta.json)
│   ├── traversal.py         ← impact_analysis(), trace_flow(), explain_module()
│   └── visualizer.py        ← ASCII architecture map, dependency trees, impact trees
├── learning/                ← Repository scanner and knowledge generator
│   ├── __init__.py          ← LearningEngine orchestrator
│   ├── ast_parser.py        ← Python AST parser — classes, methods, calls, line refs
│   ├── reference.py         ← ReferenceTracker — line-level symbol→[Reference] index
│   ├── frameworks.py        ← FrameworkDetector (20+ frameworks via importlib.metadata)
│   ├── knowledge.py         ← KnowledgeGenerator — writes .zwis/knowledge/*.md
│   └── docs_fetcher.py      ← Fetches framework docs to .zwis/docs/
├── tools/
│   ├── bash.py              ← BashTool (async, timeout, output cap)
│   ├── files.py             ← FileRead, FileWrite, FileEdit
│   ├── search.py            ← Glob, Grep
│   ├── web.py               ← WebFetch (httpx + html2text), WebSearch (DuckDuckGo)
│   ├── browser.py           ← Low-level browser tool (open, click, type, screenshot…)
│   ├── browser_agent.py     ← Autonomous browser agent (task → plan → execute)
│   ├── auxiliary.py         ← TodoWrite, AskUserQuestion
│   └── graph_tools.py       ← graph_search, graph_explain, graph_impact, graph_trace,
│                               graph_refs, graph_map  (all read-only LLM tools)
├── skills/
│   ├── __init__.py          ← SkillRegistry, YAML frontmatter parser
│   └── builtin/             ← /commit, /review, /init, /security-review, /dream, /advisor
├── hooks/                   ← Lifecycle hooks (PreToolUse, PostToolUse, PreQuery…)
├── memory/                  ← Persistent memory (~/.zwis/memory/)
├── permissions/             ← PermissionManager with allow/deny rules
├── compact/                 ← Token budget, TruncateStrategy
├── cli/
│   ├── config.py            ← AgentConfig, resolve_config(), load_settings()
│   └── repl.py              ← Full REPL — 17+ slash commands, skill dispatch, graph views
├── games/
│   └── flappy_bird.py       ← Built-in terminal game with .zwis score storage
├── catalog/                 ← Command/tool index, session store
├── modes/                   ← Connection mode stubs
└── ui/                      ← Animated terminal UI

skills/                      ← Workspace-root skills (highest precedence, drop .md files here)
├── graph-review.md          ← /graph-review — graph-driven code review before editing
├── safe-edit.md             ← /safe-edit — impact-first safe editing workflow
├── trace-flow.md            ← /trace-flow — trace and explain execution flows
├── learn-repo.md            ← /learn-repo — trigger a learning pass from the REPL
└── impact-report.md         ← /impact-report — full blast-radius report for refactoring

.zwis/                       ← Runtime data (project workspace)
├── graph/
│   ├── graph.json           ← Serialized knowledge graph
│   └── meta.json            ← Build metadata + per-file mtimes
├── knowledge/               ← Generated knowledge files (one per module + architecture.md)
├── docs/                    ← Cached framework documentation (from --fetch-docs)
├── games/                   ← Runtime game data (e.g. Flappy Bird high scores)
├── sessions/                ← Saved conversation sessions
├── skills/                  ← Project-internal skills
└── settings.json            ← Hooks and permission rules
```

## Setup

```bash
pip install -e .
zwis --init
```

`zwis --init` writes a `.env` and guides you through provider -> model -> API key selection.

You can still configure env vars manually. Set `ZWISCHENZUG_PROVIDER` and `ZWISCHENZUG_MODEL`, then export the matching provider key. Zwischenzug routes providers through LiteLLM via LangChain, so you can swap providers without changing application code. Examples:
```bash
export ZWISCHENZUG_PROVIDER=groq
export ZWISCHENZUG_MODEL=versatile
export GROQ_API_KEY=gsk_...

# or
export ZWISCHENZUG_PROVIDER=gemini
export ZWISCHENZUG_MODEL=flash
export GEMINI_API_KEY=...

# or
export ZWISCHENZUG_PROVIDER=openai
export ZWISCHENZUG_MODEL=nano
export OPENAI_API_KEY=sk-...

# or use a provider-scoped namespaced model ID
export ZWISCHENZUG_PROVIDER=anthropic
export ZWISCHENZUG_MODEL=anthropic/claude-3-5-sonnet-latest
export ANTHROPIC_API_KEY=...

# provider remains authoritative, even when the model contains slashes
export ZWISCHENZUG_PROVIDER=groq
export ZWISCHENZUG_MODEL=openai/gpt-oss-120b
export GROQ_API_KEY=gsk_...
```

For reasoning-capable models on supported providers, you can also opt into reasoning controls:

```bash
export ZWISCHENZUG_PROVIDER=groq
export ZWISCHENZUG_MODEL=openai/gpt-oss-120b
export ZWISCHENZUG_INCLUDE_REASONING=true
export ZWISCHENZUG_REASONING_EFFORT=high
```

CLI flags are available too:

```bash
zwis chat --provider groq --model openai/gpt-oss-120b \
  --include-reasoning \
  --reasoning-effort high
```

---

## Graph Intelligence

### Building the Knowledge Graph

```bash
zwis learn                   # scan repo, build graph, generate knowledge files
zwis learn --fetch-docs      # also fetch official framework documentation
zwis learn /path/to/repo     # scan a different directory
```

The learn command:
1. Scans all Python files with the stdlib `ast` module
2. Extracts classes, methods, functions, imports, and call sites with exact line numbers
3. Builds a program dependency graph (1200+ nodes on this repo in ~2.5s)
4. Detects frameworks (FastAPI, LangChain, SQLAlchemy, Pydantic, etc.)
5. Generates compressed knowledge files in `.zwis/knowledge/`
6. Optionally fetches framework docs to `.zwis/docs/`

### Graph CLI Commands

```bash
zwis map                          # ASCII architecture map of all modules
zwis map --max-files 20           # limit to top 20 files

zwis explain BashTool             # explain a class — structure, deps, callers
zwis explain src/core/agent.py    # explain by file path

zwis trace run_agent              # call graph trace from an entry point
zwis trace main --depth 3         # limit trace depth

zwis impact-change User           # blast radius: what breaks if User changes
zwis impact-change run_agent      # shows risk level: low / medium / high

zwis knowledge                    # list all .zwis/knowledge/ files
zwis knowledge architecture       # view architecture.md
zwis knowledge INDEX              # view the master index
```

### Graph Tools (in REPL / agent sessions)

After `zwis learn`, these tools are automatically registered and available to the LLM:

| Tool | Description |
|------|-------------|
| `graph_search` | Find nodes by name or type (file/class/function/method…) |
| `graph_explain` | Explain a module, class, or function — structure + deps |
| `graph_impact` | Blast-radius analysis before editing — risk level + affected files |
| `graph_trace` | Trace call chain from a function or entry point |
| `graph_refs` | Find every reference to a symbol (IDE "Find References") |
| `graph_map` | Bird's-eye architecture overview |

The agent uses these automatically during code tasks. You can also invoke them directly:

```
> what calls run_agent?
> show me the impact of changing GraphEngine
> trace the flow from main to tool execution
```

### Graph Node Types

| Type | Examples |
|------|---------|
| `file` | `src/tools/bash.py` |
| `class` | `BashTool`, `GraphEngine` |
| `function` | `run_agent`, `build_system_prompt` |
| `method` | `BashTool.execute`, `GraphEngine.bfs_reverse` |
| `model` | ORM/DB models |
| `route` | API endpoints |
| `external` | `asyncio`, `langchain_core` |

### Graph Edge Types

`IMPORTS` · `CALLS` · `EXTENDS` · `IMPLEMENTS` · `READS_DB` · `WRITES_DB` · `DEPENDS_ON` · `RETURNS` · `USES` · `DEFINES` · `CONTAINS`

---

## Agent Commands

### Interactive REPL

```bash
zwis                                     # requires a configured .env
zwis --init                              # run setup if .env is missing
zwis chat --provider groq --model versatile
zwis chat --permission interactive       # prompt before each write
zwis chat --plan                         # read-only mode (no writes)
zwis chat --continue                     # resume last saved session
zwis chat --resume session-1234567890    # resume specific session
```

### Single Prompt (headless)

```bash
zwis run "explain this codebase"
zwis run "what tests are failing?" --output-format json
echo "refactor utils.py" | zwis run
```

Shared agent flags: `--provider`, `--model`, `--system PROMPT`, `--permission auto|interactive|deny`, `--max-turns N`, `--temperature F`, `--max-tokens N`

### Games

```bash
zwis game flappy-bird
```

This also works inside the REPL as `/game/flappy-bird`.

---

## REPL Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands and registered skills |
| `/tools` | List available tools |
| `/skills` | List all skills with descriptions |
| `/session` | Show session stats (ID, turns, tokens) |
| `/status` | Model, provider, permission mode, CWD |
| `/cost` | Token usage + estimated cost |
| `/config` | Show current configuration |
| `/memory [name]` | List memories, or view a specific one |
| `/graph [map]` | Show knowledge graph stats or architecture map |
| `/knowledge [topic]` | List or view files in `.zwis/knowledge/` |
| `/game/flappy-bird` | Launch the built-in Flappy Bird game |
| `/compact` | Manually compress conversation context |
| `/clear` | Clear conversation history |
| `/save` | Save session to `.zwis/sessions/` |
| `/plan` | Switch to plan mode (read-only) |
| `/auto` | Return to auto mode |
| `/exit` `/quit` | Exit |

### Built-in Skills

| Skill | Description |
|-------|-------------|
| `/commit` | Generate and create a git commit |
| `/review` | Code review of recent changes |
| `/init` | Initialize/update ZWISCHENZUG.md |
| `/security-review` | OWASP Top 10 security review |
| `/dream` | Consolidate and clean up memory files |
| `/advisor` | Switch to read-only advisory mode |

### Graph-Aware Skills (workspace `skills/`)

| Skill | Description |
|-------|-------------|
| `/graph-review` | Review code using the knowledge graph — deps, impact, risks |
| `/safe-edit` | Impact analysis first, then safe edit with verification |
| `/trace-flow` | Trace and explain a complete execution flow |
| `/impact-report` | Full blast-radius report before a refactoring |
| `/learn-repo` | Trigger a repository learning pass from the REPL |

Add your own skills by dropping `.md` files in `skills/` (workspace root) — see **Custom Skills** below.

---

## Tools

| Tool | Read-only | Description |
|------|-----------|-------------|
| `bash` | No | Execute shell commands (async, 30s timeout) |
| `read_file` | Yes | Read file with line numbers, offset/limit |
| `write_file` | No | Write/overwrite a file |
| `edit_file` | No | Replace a unique string in a file |
| `glob` | Yes | Find files by pattern, sorted by mtime |
| `grep` | Yes | Regex search with context lines |
| `web_fetch` | Yes | Fetch URL → markdown / JSON / raw |
| `web_search` | Yes | DuckDuckGo search, no API key needed |
| `browser` | No | Low-level browser automation (open, click, type, screenshot, etc.) |
| `browser_agent` | No | Autonomous browser agent — give it a task in plain English |
| `todo_write` | No | Session todo list for tracking progress |
| `ask_user` | No | Pause and ask user a clarifying question |
| `graph_search` | Yes | Search knowledge graph by name/type |
| `graph_explain` | Yes | Explain a module/class/function |
| `graph_impact` | Yes | Impact analysis before editing |
| `graph_trace` | Yes | Trace execution call chain |
| `graph_refs` | Yes | Find all references to a symbol |
| `graph_map` | Yes | Architecture overview |

Graph tools are only registered when `.zwis/graph/graph.json` exists (i.e. after `zwis learn`).

---

## Browser Agent

The `browser_agent` tool gives a plain-English task to an autonomous browser-use Agent that navigates, clicks, types, scrolls, and extracts information on its own.

```
> use browser_agent to go to duckduckgo.com and search for OpenAI
```

The agent plans and executes browser actions autonomously — no need to manually issue open/click/type commands.

### Watching Live via noVNC

Run `zwis setup-browser` once per session. It installs everything needed, starts Xvfb + x11vnc + noVNC on port 6080, then launches `zwis` — all in one command.

```bash
zwis setup-browser
# open http://localhost:6080/vnc.html to watch the browser live
```

Without it, browser tools still work headlessly — you just won't see the browser.

**Linux / VM / Cloud:**

```bash
pip install "zwischenzug[browser]"
zwis setup-browser
# open http://localhost:6080/vnc.html
```

**Docker:**
```bash
docker run -it --rm --env-file .env -p 6080:6080 zwis
# open http://localhost:6080/vnc.html
```

### Configuration

Override the LLM that drives the browser agent:

```bash
# In .env
BROWSER_AGENT_MODEL=gemini-2.5-flash
```

If not set, it uses your main `ZWISCHENZUG_MODEL`.

### Low-Level Browser Tool

The `browser` tool is also available for manual step-by-step control:

```
browser(action="open", url="https://example.com")
browser(action="click", selector="button[type=submit]")
browser(action="content")
```

See [docs/tools/browser-tool.md](docs/tools/browser-tool.md) for full reference.

---

## Skills

Skills are Markdown files with YAML frontmatter. Discovery order — **later sources override earlier ones**:

1. `src/skills/builtin/` — bundled with the package
2. `~/.zwis/skills/` — user-level (personal)
3. `.zwis/skills/` — project-internal
4. `skills/` — **workspace root (highest priority)**

**Creating a custom skill** (`skills/deploy.md`):

```markdown
---
name: deploy
description: Deploy the application to staging
aliases: [d]
allowedTools: [bash, read_file]
context: inline
---
Deploy the application. Run the deploy script and confirm it succeeded.

{{{args}}}
```

Then use it: `/deploy` or `/d production`

**Creating a graph-aware skill** (`skills/my-analysis.md`):

```markdown
---
name: my-analysis
description: Analyse a module with the knowledge graph
allowedTools: [graph_search, graph_explain, graph_impact, read_file]
---
Use graph_search to find {{{args}}}, then graph_explain to understand it,
then graph_impact to assess change risk.
```

---

## Knowledge Files

After `zwis learn`, compressed knowledge files are written to `.zwis/knowledge/`:

| File | Contents |
|------|----------|
| `INDEX.md` | Master index of all knowledge files |
| `architecture.md` | Overall structure, frameworks, module list |
| `src-tools-bash-py.md` | Per-module: purpose, classes, functions, deps, risks |
| … | One file per module with substantial content |

Knowledge files follow this format: **Purpose · Key Components · Dependencies · Used By · Risks**

The LLM can read these directly, or they are referenced via the system prompt automatically.

---

## Hooks

Configure shell commands that run at lifecycle events in `.zwis/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "bash",
        "hooks": [{"type": "command", "command": "echo 'About to run: $ZWIS_TOOL_NAME'"}]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "logger -t zwis 'tool done'"}]
      }
    ],
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "npm install --silent 2>/dev/null || true"}]
      }
    ]
  }
}
```

Hook events: `PreToolUse`, `PostToolUse`, `PreQuery`, `PostQuery`, `SessionStart`, `SessionEnd`, `Stop`

Pre-hooks block execution if they exit non-zero. Post-hooks never block. Timeout: 10 seconds.

Hook environment variables: `ZWIS_TOOL_NAME`, `ZWIS_SESSION_ID`, `ZWIS_CWD`, `ZWIS_HOOK_EVENT`

---

## Permission Rules

Configure allow/deny rules in `.zwis/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(npm run *)",
      "Bash(git *)",
      "Bash(python -m pytest*)"
    ],
    "deny": [
      "Bash(rm -rf *)",
      "Bash(sudo *)",
      "Bash(curl * | bash)"
    ]
  }
}
```

Pattern syntax: `ToolName(glob)` where glob is matched against the primary input.
Deny rules always take precedence over allow rules.

---

## Memory

Persistent memories are stored in `~/.zwis/memory/` and injected into every session's system prompt via the `MEMORY.md` index.

```bash
zwis chat
# /memory                   — list all memories
# /memory my-preference     — view a specific memory
```

Memory files use YAML frontmatter:

```markdown
---
name: testing-preference
description: User prefers integration tests over unit tests
type: feedback
---
Always write integration tests that hit a real database rather than mocking.
Reason: mocked tests passed but prod migration failed.
```

Types: `user`, `feedback`, `project`, `reference`

---

## Provider Config

All provider logic lives in `src/provider/__init__.py`. To add a new provider:

1. Open `src/provider/__init__.py`
2. Copy the `_build_groq` function and create `_build_yourprovider`
3. Add `"yourprovider": _build_yourprovider` to the dispatch dict in `build_llm`
4. Add model aliases to `MODEL_ALIASES["yourprovider"]`
5. No other file needs editing

An OpenAI template is included as a commented-out example.

---

## Session Management

```bash
zwis sessions                            # list all saved sessions
zwis chat --continue                     # resume last session
zwis chat --resume session-1234567890    # resume specific session
zwis chat  # type /save                  # save current session
zwis load-session session-1234567890     # inspect a session
```

---

## Discovery Commands

```bash
zwis summary                         # workspace overview
zwis manifest                        # Python module manifest
zwis commands --limit 10             # list known commands
zwis tools --limit 10                # list known tools
zwis route "review code"             # match prompt to commands/tools
zwis bootstrap "fix the bug"         # route + execute one turn
```

---

## Docker

**Build:**

```bash
docker build -t zwis .
```

**Interactive REPL** (just `zwis`):

```bash
docker run -it --rm --env-file .env zwis
```

**Single command (headless):**

```bash
docker run --rm --env-file .env zwis zwis run "summarize this repo"
```

The container reads provider config from your `.env` file via `--env-file`. No need to mount the file — environment variables are picked up automatically.

**Managing the `.env` without `--env-file`:**

If you run without `--env-file`, `zwis --init` will create `/app/.env` inside the container. Because containers are ephemeral that file disappears when the container stops. There are two ways to persist it:

**Option 1 — Mount a local file (recommended):**

Create your `.env` once on the host, then mount it into every run:

```bash
# First-time setup: let zwis write the file to your host
docker run -it --rm -v $(pwd)/.env:/app/.env zwis zwis --init

# Every subsequent run picks up the same file
docker run -it --rm -v $(pwd)/.env:/app/.env zwis
```

Edit `/app/.env` on your host machine anytime — the next `docker run` picks up the changes automatically.

**Option 2 — Edit inside a running container:**

```bash
# Find the container name/ID
docker ps

# Open a shell in the running container
docker exec -it <container_id> sh

# Edit the file (vi is available in the image)
vi /app/.env
```

Changes take effect immediately for the current session. Remember to copy the file out before the container stops if you want to keep it:

```bash
docker cp <container_id>:/app/.env .env
```

**Watch the browser live (noVNC):**

The image starts Xvfb + noVNC on port 6080 internally. Map it to any host port you like with `-p`:

```bash
docker run -it --rm --env-file .env -p 6080:6080 zwis
```

Then open `http://localhost:6080/vnc.html` to watch Chrome in real time.

Use a different host port if 6080 is already taken (e.g. by a running devcontainer):

```bash
docker run -it --rm --env-file .env -p 6081:6080 zwis
# open http://localhost:6081/vnc.html
```

---

## Tests

```bash
python -m pytest tests/ -q
```

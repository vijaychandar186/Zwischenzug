# Zwischenzug — System Overview

## Purpose

Zwischenzug is a terminal-based AI coding agent and Codebase Intelligence Engine powered by LangChain. It provides an interactive REPL that accepts natural language instructions, executes multi-step tool-based workflows (file editing, shell commands, web access, code search, graph intelligence), and presents results through a rich terminal UI.

The system is designed to function as a coding assistant that builds a full knowledge graph of your repository and uses it to reason about architecture, dependencies, and safe edits — not just code generation.

---

## High-Level Capabilities

- **Conversational REPL**: Persistent session with streaming responses and full conversation history.
- **Knowledge Graph Engine**: Pure-Python in-memory graph built from AST analysis — nodes for files, classes, functions; edges for imports, calls, inheritance.
- **Graph Intelligence Tools**: 6 read-only LLM tools for searching, explaining, tracing, and impact-analyzing the codebase.
- **Tool Execution**: 16+ integrated tools including file read/write/edit, bash execution, web search/fetch, graph queries, browser automation, and more.
- **Browser Agent**: Autonomous browser automation via browser-use — give a task in plain English and watch the agent navigate, click, type, and extract information. Visible via VNC in Codespaces.
- **MCP Integration**: Configurable MCP servers whose tools and resources are loaded dynamically into `zwis chat` and `zwis run`.
- **Slash Commands**: 17+ built-in and extensible slash commands for configuration, session management, graph views, and skills.
- **Built-in Games**: Lightweight local terminal games exposed through the CLI and REPL.
- **Skill System**: Markdown-based instruction packages with YAML frontmatter, auto-registered as slash commands.
- **Permissions System**: Configurable allow/deny rules with glob patterns for tool invocations.
- **Memory System**: Persistent memories stored in `~/.zwis/memory/` with MEMORY.md index, injected into system prompt.
- **Hook System**: Shell commands that run at lifecycle events (PreToolUse, PostToolUse, PreQuery, PostQuery, etc.).
- **Context Compression**: Manual conversation compression to manage token budgets.
- **Session Management**: Save, list, resume, and continue conversation sessions.
- **Framework Detection**: Automatically detects 20+ frameworks (FastAPI, LangChain, SQLAlchemy, Pydantic, etc.) and optionally fetches their documentation.
- **LLM Provider Agnostic**: Uses LiteLLM through LangChain, with Groq and Gemini aliases built in and support for many additional providers by configuration.

---

## Entry Points

| Mode | CLI Command | Description |
|------|-------------|-------------|
| Interactive REPL | `zwis` or `zwis chat` | Full terminal UI, conversational loop |
| Single Prompt | `zwis run "prompt"` | Headless mode, stdout output |
| Continue | `zwis chat --continue` | Resumes last saved session |
| Resume | `zwis chat --resume <id>` | Resumes a specific session by ID |
| Learn | `zwis learn` | Scan repo, build knowledge graph |
| Map | `zwis map` | ASCII architecture map |
| Explain | `zwis explain <symbol>` | Explain a class/function/module |
| Trace | `zwis trace <function>` | Trace call chain from entry point |
| Impact | `zwis impact-change <symbol>` | Blast-radius analysis |
| Knowledge | `zwis knowledge [topic]` | View generated knowledge files |
| Games | `zwis game flappy-bird` | Launch a built-in terminal game |
| Discovery | `zwis summary\|manifest\|commands\|tools` | Workspace inspection |

---

## Repository Structure

```
src/
├── main.py                  ← CLI entry point (zwis / zwischenzug)
├── app_paths.py             ← All disk paths go through here
├── provider/                ← LLM factory — single file to edit for new providers
├── core/
│   ├── agent.py             ← Multi-turn loop, hooks, retry, graph context injection
│   ├── session.py           ← SessionState, resume/continue support
│   └── system_prompt.py     ← Prompt builder (base + ZWISCHENZUG.md + memory + graph)
├── graph/                   ← Knowledge graph engine (pure Python, no external DB)
│   ├── schema.py            ← NodeType, EdgeType, GraphNode, GraphEdge, Reference
│   ├── storage.py           ← JSON persistence (.zwis/graph/)
│   ├── traversal.py         ← impact_analysis(), trace_flow(), explain_module()
│   └── visualizer.py        ← ASCII architecture map, dependency trees
├── learning/                ← Repository scanner and knowledge generator
│   ├── ast_parser.py        ← Python AST parser — classes, methods, calls, line refs
│   ├── reference.py         ← ReferenceTracker — line-level symbol index
│   ├── frameworks.py        ← FrameworkDetector (20+ frameworks)
│   ├── knowledge.py         ← KnowledgeGenerator — writes .zwis/knowledge/*.md
│   └── docs_fetcher.py      ← Fetches framework docs to .zwis/docs/
├── mcp/                     ← MCP server config, discovery, and tool/resource proxies
│   ├── config.py            ← Project/user MCP config persistence
│   └── runtime.py           ← MCP session handling and dynamic tool registration
├── tools/                   ← Tool implementations
│   ├── bash.py              ← BashTool (async, timeout, output cap)
│   ├── files.py             ← FileRead, FileWrite, FileEdit
│   ├── search.py            ← Glob, Grep
│   ├── web.py               ← WebFetch, WebSearch
│   ├── browser.py           ← Low-level browser automation (open, click, type, etc.)
│   ├── browser_agent.py     ← Autonomous browser agent (task → plan → execute)
│   ├── auxiliary.py         ← TodoWrite, AskUserQuestion
│   └── graph_tools.py       ← 6 graph intelligence tools (all read-only)
├── skills/
│   ├── __init__.py          ← SkillRegistry, YAML frontmatter parser
│   └── builtin/             ← /commit, /review, /init, /security-review, /dream, /advisor
├── hooks/                   ← Lifecycle hooks (PreToolUse, PostToolUse, etc.)
├── memory/                  ← Persistent memory manager
├── permissions/             ← PermissionManager with allow/deny rules
├── compact/                 ← Token budget, TruncateStrategy
├── cli/
│   ├── config.py            ← AgentConfig, resolve_config(), load_settings()
│   └── repl.py              ← Full REPL — 17+ slash commands, skill dispatch
├── games/                   ← Built-in terminal games
│   └── flappy_bird.py       ← Local Flappy Bird implementation + score storage
└── ui/                      ← Animated terminal UI (Rich)

skills/                      ← Workspace-root skills (highest precedence)
.zwis/                       ← Runtime data (project workspace)
```

---

## Technology Stack

| Concern | Technology |
|---------|-----------|
| Language | Python 3.10+ |
| LLM Framework | LangChain / LangChain Core |
| LLM Providers | LiteLLM via langchain-litellm |
| HTTP Client | httpx |
| HTML Conversion | html2text |
| Web Search | ddgs |
| Browser Automation | browser-use + Playwright (Chromium) |
| MCP Client | mcp |
| Terminal UI | Rich |
| Data Validation | Pydantic |
| Config Parsing | PyYAML, python-dotenv |
| Package Manager | pip / pyproject.toml |

---

## Key Design Principles

1. **Provider isolation**: All LLM provider code lives in `src/provider/__init__.py`. Adding a new provider means editing one file — no other module imports provider-specific libraries.
2. **Async-first**: All I/O is async. Blocking operations use `asyncio.to_thread()`.
3. **Graph-driven reasoning**: The knowledge graph is not a gimmick — it powers impact analysis, safe edits, trace flows, and architecture understanding at the tool level.
4. **Layered permissions**: Every tool invocation passes through independent permission layers; any layer can deny or require approval.
5. **Concurrency safety**: Write tools are serialized. Read-only tools can run in parallel.
6. **Multi-source configuration**: Config is resolved from CLI flags > env vars > `.zwis/config.json` > defaults.
7. **Skill-based extensibility**: Drop a `.md` file in `skills/` and it becomes a slash command — no code changes needed.
8. **All paths through app_paths**: Every disk path goes through `src/app_paths.py` for consistency.

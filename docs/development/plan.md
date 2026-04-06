# Zwischenzug CLI — Production Upgrade Plan

## Context

The goal is to upgrade the Zwischenzug CLI from its current ~40% state to a full production-grade AI coding agent. The project is a Python CLI agent using LangChain with LiteLLM-backed model routing. The docs/ directory contains the full specification of what it should do.

The provider config must stay isolated in `src/provider/__init__.py` — the single file that needs editing to add new providers.

---

## Architectural Principles (non-negotiable)

1. Provider config: **only `src/provider/__init__.py`** imports the LangChain LiteLLM integration and handles provider-specific normalization
2. New tools: extend `src/tools/__init__.py:Tool`, register in `default_registry()`
3. All disk paths: go through `src/app_paths.py`
4. Settings: project at `.zwis/settings.json`, user at `~/.zwis/settings.json`
5. All I/O is async; blocking I/O uses `asyncio.to_thread`
6. Config resolution priority: CLI flags > env vars > `.zwis/config.json` > defaults

---

## New Dependencies (add to pyproject.toml)

```toml
"httpx>=0.27.0",           # WebFetch HTTP client
"html2text>=2024.2.26",    # HTML → markdown conversion
"ddgs>=7.0.0",              # WebSearch (no API key needed)
"PyYAML>=6.0",             # Skill frontmatter parsing
```

Optional extras (already in `dev`): pytest, pytest-asyncio

---

## Files to Create / Modify

### PHASE 1 — Foundation

#### 1. `src/app_paths.py` — extend with new path helpers

Add:
- `settings_files()` — `[Path.cwd()/.zwis/settings.json, Path.home()/.zwis/settings.json]`
- `skills_dirs()` — `[Path.cwd()/.zwis/skills/, Path.home()/.zwis/skills/]`
- `memory_dir()` — `Path.home()/.zwis/memory/`
- `memory_index_file()` — `memory_dir() / "MEMORY.md"`

#### 2. `src/provider/__init__.py` — model aliases + extensibility comments

Add:
- `MODEL_ALIASES` dict: `{"versatile": "llama-3.3-70b-versatile", "fast": "llama-3.1-8b-instant", "flash": "gemini-2.0-flash", "pro": "gemini-1.5-pro"}`
- `resolve_model(provider, model)` — expands aliases before passing to the factory
- Clear docstring showing how to add a new provider: copy `_build_groq`, add env key, add to `build_llm` dispatch
- Add `_build_openai` stub (commented out) as a reference template

---

### PHASE 2 — New Tools

#### 3. `src/tools/web.py` — NEW

**WebFetchTool**:
- Input schema: `url` (required), `format` ("markdown"|"json"|"raw", default "markdown")
- Uses `httpx.AsyncClient` with 30s timeout, User-Agent header
- Detects content-type: HTML → `html2text.html2text()`, JSON → pretty-print, other → raw text
- Max output: 50K chars (same cap as BashTool)
- `is_read_only = True`

**WebSearchTool**:
- Input schema: `query` (required), `max_results` (int, default 5)
- Uses `ddgs.DDGS().text()` wrapped in `asyncio.to_thread`
- Returns formatted list: `1. [Title](url)\n   snippet`
- Graceful fallback: if `ddgs` not installed → `ToolOutput.error("Install ddgs: pip install ddgs")`
- `is_read_only = True`

#### 4. `src/tools/auxiliary.py` — NEW

**TodoWriteTool**:
- Input: `todos` as JSON string (array of `{id, content, status, priority}`)
- Stores in a module-level dict keyed by session_id from `ToolContext`
- Returns formatted markdown table of todos
- `is_read_only = False` (writes session state)

**AskUserQuestionTool**:
- Input: `question` (required)
- Uses `asyncio.to_thread(input, ...)` to pause and wait for user input
- Returns the user's typed response as `ToolOutput.success(answer)`
- `is_read_only = False`

#### 5. `src/tools/__init__.py` — update `default_registry()`

Add WebFetchTool, WebSearchTool, TodoWriteTool, AskUserQuestionTool to default registry.

---

### PHASE 3 — Hooks System

#### 6. `src/hooks/__init__.py` — NEW

```python
class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_QUERY = "PreQuery"
    POST_QUERY = "PostQuery"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    STOP = "Stop"

@dataclass
class HookDef:
    command: str   # shell command
    timeout: float = 10.0

@dataclass
class HookEntry:
    matcher: str   # tool name or "*"
    hooks: list[HookDef]

class HookRunner:
    def __init__(self, hooks: dict[str, list[HookEntry]]): ...

    @classmethod
    def from_settings(cls, cwd: str) -> "HookRunner":
        # Read .zwis/settings.json and ~/.zwis/settings.json
        # Merge hook lists (project overrides user)
        ...

    async def run(
        self,
        event: HookEvent,
        matcher: str = "*",
        env_extra: dict[str, str] | None = None,
    ) -> bool:
        # Returns False if a pre-hook exits non-zero (blocking)
        # Post-hooks always return True
        # Pass ZWIS_TOOL_NAME, ZWIS_TOOL_INPUT, ZWIS_SESSION_ID, ZWIS_CWD as env
        ...
```

Settings format (`.zwis/settings.json`):
```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "bash", "hooks": [{"type": "command", "command": "echo 'running bash'"}]}
    ]
  },
  "permissions": {
    "allow": ["Bash(npm run *)", "Bash(git *)"],
    "deny": ["Bash(rm -rf *)"]
  }
}
```

---

### PHASE 4 — Permission System

#### 7. `src/permissions/__init__.py` — full rewrite

Keep existing `PermissionMode` and `ToolPermissionContext`. Add:

```python
@dataclass(frozen=True)
class PermissionRule:
    tool: str      # e.g. "Bash", "Read", "*"
    pattern: str   # glob pattern matched against primary input
    allow: bool    # True = allow, False = deny

class PermissionManager:
    mode: PermissionMode
    allow_rules: list[PermissionRule]
    deny_rules: list[PermissionRule]

    @classmethod
    def from_settings(cls, cwd: str, mode: PermissionMode) -> "PermissionManager":
        # Read .zwis/settings.json + ~/.zwis/settings.json
        # Parse "Bash(npm run *)" → PermissionRule(tool="Bash", pattern="npm run *")
        ...

    def check(self, tool_name: str, primary_input: str) -> Literal["allow", "deny", "ask"]:
        # Order: mode check → deny rules → allow rules → default by mode
        # mode=DENY → deny all writes
        # bypassPermissions → allow all
        # deny rules checked first (deny wins)
        # allow rules checked second
        # default: INTERACTIVE → ask, AUTO → allow for reads/deny for writes
        ...
```

Update `ToolOrchestrator` in `src/tools/__init__.py` to use `PermissionManager` when provided.

---

### PHASE 5 — Skills System

#### 8. `src/skills/__init__.py` — NEW

```python
@dataclass
class Skill:
    name: str
    description: str
    aliases: list[str]
    allowed_tools: list[str] | None   # None = all tools
    model: str | None                  # None = inherit session model
    context: Literal["inline", "fork"]  # default: "inline"
    prompt_template: str               # {{{args}}} placeholder
    source_path: Path

class SkillRegistry:
    @classmethod
    def discover(cls, cwd: str | None = None) -> "SkillRegistry":
        # Scan: bundled (src/skills/builtin/) → ~/.zwis/skills/ → .zwis/skills/
        # Later entries override earlier (project > user > bundled)
        # Parse YAML frontmatter with PyYAML, body is prompt_template
        ...

    def get(self, name: str) -> Skill | None:
        # Match by name or aliases
        ...

    def all(self) -> list[Skill]:
        ...

    def expand(self, skill: Skill, args: str) -> str:
        return skill.prompt_template.replace("{{{args}}}", args)
```

**Bundled skill files** (in `src/skills/builtin/`):

`commit.md`:
```markdown
---
name: commit
description: Generate and create a git commit for staged changes
aliases: [c]
allowedTools: [bash, glob, grep, read_file]
---
Create a git commit for the staged changes. Run `git diff --cached` to see what's staged. Write a concise commit message following conventional commits format. Then run `git commit -m "..."`.

{{{args}}}
```

`review.md`:
```markdown
---
name: review
description: Code review for current changes or a file
aliases: [r]
allowedTools: [bash, glob, grep, read_file]
---
Perform a thorough code review. Check for bugs, security issues, performance problems, and style issues.

{{{args}}}
```

`init.md`:
```markdown
---
name: init
description: Initialize ZWISCHENZUG.md project configuration
allowedTools: [bash, glob, read_file, write_file]
---
Create or update ZWISCHENZUG.md with project-specific instructions for this AI coding agent. Analyze the project structure and write concise instructions about conventions, architecture, and important context.

{{{args}}}
```

`security-review.md`:
```markdown
---
name: security-review
description: Security-focused code review checking for OWASP top 10 and common vulnerabilities
aliases: [sec]
allowedTools: [bash, glob, grep, read_file]
---
Perform a security review of the codebase. Check for: SQL injection, XSS, command injection, path traversal, hardcoded secrets, insecure dependencies, authentication/authorization issues, and OWASP top 10 vulnerabilities.

{{{args}}}
```

`dream.md`:
```markdown
---
name: dream
description: Consolidate and clean up memory files to reduce redundancy
allowedTools: [read_file, write_file, glob]
---
Review all memory files in the memory directory. Merge redundant entries, remove stale information, and organize memories by type. Keep entries concise and actionable.

{{{args}}}
```

---

### PHASE 6 — Memory System

#### 9. `src/memory/__init__.py` — NEW

```python
class MemoryType(str, Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"

@dataclass
class MemoryEntry:
    name: str
    description: str
    type: MemoryType
    content: str
    file_path: Path

class MemoryManager:
    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir

    def load_index(self) -> str:
        """Return MEMORY.md content (up to 200 lines)."""
        idx = self.memory_dir / "MEMORY.md"
        if not idx.exists():
            return ""
        lines = idx.read_text().splitlines()
        return "\n".join(lines[:200])

    def list_memories(self) -> list[MemoryEntry]:
        """Parse all .md files with frontmatter."""
        ...

    def get(self, name: str) -> MemoryEntry | None:
        ...

    def save(self, entry: MemoryEntry) -> None:
        """Write memory file and update MEMORY.md index."""
        ...

    def delete(self, name: str) -> bool:
        """Remove memory file and update index."""
        ...

    def render_list(self) -> str:
        """Rich table for /memory command."""
        ...
```

---

### PHASE 7 — System Prompt Builder

#### 10. `src/core/system_prompt.py` — NEW

```python
def build_system_prompt(
    base: str,
    memory_index: str | None = None,
    zwischenzug_md: str | None = None,
    skill_context: str | None = None,
) -> str:
    """
    Compose the final system prompt from all sources:
    1. base (from SessionConfig.system_prompt or DEFAULT_SYSTEM_PROMPT)
    2. ZWISCHENZUG.md content (project instructions)
    3. MEMORY.md index (persistent memory pointers)
    4. skill_context (when a skill is active)
    """
    ...

DEFAULT_SYSTEM_PROMPT = """You are Zwischenzug, an expert AI coding agent. You help with software engineering tasks: writing code, fixing bugs, refactoring, explaining code, running commands, and managing files.

Key behaviors:
- Read files before modifying them
- Verify assumptions with glob/grep before making changes
- Prefer editing existing files over creating new ones
- Ask for clarification when requirements are ambiguous
- Be concise in responses — lead with the action or answer
- Use bash for git operations, running tests, and system tasks
"""
```

---

### PHASE 8 — Core Agent Updates

#### 11. `src/core/agent.py` — integrate hooks + system prompt builder

Changes:
- Accept optional `HookRunner` parameter
- Before each tool execution batch: `await hook_runner.run(PRE_TOOL_USE, tool_name, env)`
- After each tool execution: `await hook_runner.run(POST_TOOL_USE, tool_name, env)`
- Before each API call: `await hook_runner.run(PRE_QUERY, env)`
- After each API response: `await hook_runner.run(POST_QUERY, env)`
- Import `build_system_prompt` from `src/core/system_prompt.py`
- Use `build_system_prompt(base, memory_index, zwischenzug_md)` instead of simple string concat
- Load `MemoryManager.load_index()` at session start, inject into system prompt

Signature change:
```python
async def run_agent(
    session: SessionState,
    llm,
    registry: ToolRegistry,
    orchestrator: ToolOrchestrator,
    on_event: EventCallback | None = None,
    hook_runner: "HookRunner | None" = None,  # NEW
) -> None:
```

---

### PHASE 9 — Session Resume

#### 12. `src/core/session.py` — add `from_dict` classmethod

Add:
```python
@classmethod
def from_dict(cls, data: dict, config: SessionConfig) -> "SessionState":
    """Restore a session from serialized dict (for --resume)."""
    ...
```

#### 13. `src/catalog/session_store.py` — verify `load_session` + add `list_sessions`

Ensure `load_session(session_id)` returns a `StoredSession` with enough data to restore `SessionState`. Add `list_sessions(cwd)` returning sessions sorted by timestamp (newest first).

---

### PHASE 10 — Config + Settings Loading

#### 14. `src/cli/config.py` — add settings.json loading

Add:
```python
def load_settings(cwd: str | None = None) -> dict:
    """
    Load and merge .zwis/settings.json (project) and ~/.zwis/settings.json (user).
    Project settings override user settings for conflicting keys.
    Returns merged dict.
    """
    ...
```

Expose `load_settings` for use by `HookRunner.from_settings` and `PermissionManager.from_settings`.

---

### PHASE 11 — REPL Overhaul

#### 15. `src/cli/repl.py` — full slash command expansion

**New slash commands** (beyond existing /help /tools /session /clear /save /exit):

| Command | Action |
|---------|--------|
| `/compact` | Trigger manual context compression (calls `session.compact()`, logs message count) |
| `/memory` | List all memory entries using `MemoryManager.render_list()` |
| `/memory <name>` | Show full content of a named memory |
| `/skills` | List all discovered skills with descriptions |
| `/cost` | Show token usage and estimated cost (groq: ~$0.0008/1M tokens; gemini: ~$0.0001/1M) |
| `/status` | Show model, provider, session ID, turns, permission mode, cwd |
| `/config` | Show current AgentConfig as formatted table |
| `/plan` | Switch permission_mode to DENY (read-only planning mode) |
| All skill names | E.g. `/commit`, `/review`, `/init` — auto-registered from SkillRegistry |

**Auto-register skills as slash commands**: In `run_repl`, after building `SkillRegistry`, iterate `.all()` and add each skill name + aliases to the command dispatch. Skill commands expand the prompt template and call `session.push_human(expanded_prompt)` then run the agent.

**Tab completion**: After `_setup_readline()`, register a completer that matches `/` commands from the known command list + skill names.

**REPL constructor changes**:
```python
def run_repl(
    session_config: SessionConfig,
    llm: Any,
    cwd: str | None = None,
    hook_runner: "HookRunner | None" = None,   # NEW
) -> int:
```

Build `SkillRegistry.discover(cwd)`, `MemoryManager`, and `HookRunner` inside `run_repl`. Run `SessionStart` hook at start, `SessionEnd` hook at end.

---

### PHASE 12 — Main Entry Point

#### 16. `src/main.py` — add --continue / --resume / --plan

In `_add_agent_args`:
```python
p.add_argument("--continue", "-c", action="store_true", dest="cont", help="Continue last session")
p.add_argument("--resume", "-r", metavar="ID", dest="resume_id", help="Resume session by ID")
p.add_argument("--plan", action="store_true", help="Start in plan mode (read-only)")
```

In the `chat` command handler:
- If `args.cont`: load most recent session from `sessions_dir`, restore `SessionState`
- If `args.resume_id`: call `load_session(args.resume_id)`, restore `SessionState`
- If `args.plan`: force `permission_mode = "deny"`

Also build `HookRunner.from_settings(cwd)` and pass to `run_repl`.

---

### PHASE 13 — Package Data + Dependencies

#### 17. `pyproject.toml`

Add to `dependencies`:
```toml
"httpx>=0.27.0",
"html2text>=2024.2.26",
"ddgs>=7.0.0",
"PyYAML>=6.0",
```

Add to `[tool.setuptools.package-data]`:
```toml
"src.skills" = ["builtin/*.md"]
```

---

### PHASE 14 — README + .env.example

#### 18. `README.md` — comprehensive update

Structure:
1. What it is / quick start
2. Installation
3. All CLI flags (chat, run, --continue, --resume, --plan, --permission)
4. Built-in slash commands table
5. Skills: how to create custom skills in `.zwis/skills/`
6. Hooks: settings.json format with examples
7. Permission rules: allow/deny pattern syntax
8. Memory: types and how to use
9. Provider config: how to add a new provider (one file to edit)
10. Tool reference table

#### 19. `.env.example` — update with all new vars

Add:
```
# Optional: override default memory location
ZWISCHENZUG_MEMORY_DIR=~/.zwis/memory

# Optional: override compact threshold (0.0–1.0)
ZWISCHENZUG_COMPACT_THRESHOLD=0.80

# Optional: disable auto-memory MEMORY.md injection
ZWISCHENZUG_DISABLE_MEMORY=false
```

---

## File Change Summary

| File | Action | Key Change |
|------|--------|------------|
| `src/app_paths.py` | Modify | Add settings_files, skills_dirs, memory_dir |
| `src/provider/__init__.py` | Modify | Model aliases, resolve_model(), extensibility docs |
| `src/tools/web.py` | **Create** | WebFetchTool, WebSearchTool |
| `src/tools/auxiliary.py` | **Create** | TodoWriteTool, AskUserQuestionTool |
| `src/tools/__init__.py` | Modify | Register 4 new tools in default_registry() |
| `src/hooks/__init__.py` | **Create** | HookRunner, settings.json loading |
| `src/permissions/__init__.py` | Modify | PermissionManager with allow/deny rules |
| `src/skills/__init__.py` | **Create** | SkillRegistry, skill discovery, expansion |
| `src/skills/builtin/commit.md` | **Create** | Built-in commit skill |
| `src/skills/builtin/review.md` | **Create** | Built-in review skill |
| `src/skills/builtin/init.md` | **Create** | Built-in init skill |
| `src/skills/builtin/security-review.md` | **Create** | Built-in security review skill |
| `src/skills/builtin/dream.md` | **Create** | Built-in memory consolidation skill |
| `src/memory/__init__.py` | **Create** | MemoryManager, MEMORY.md index |
| `src/core/system_prompt.py` | **Create** | build_system_prompt(), DEFAULT_SYSTEM_PROMPT |
| `src/core/agent.py` | Modify | Hook integration, system_prompt.py usage |
| `src/core/session.py` | Modify | from_dict() for session resume |
| `src/catalog/session_store.py` | Modify | list_sessions() helper |
| `src/cli/config.py` | Modify | load_settings() for settings.json |
| `src/cli/repl.py` | Modify | 10+ new commands, skill auto-register, tab complete |
| `src/main.py` | Modify | --continue, --resume, --plan flags |
| `pyproject.toml` | Modify | 4 new deps + skills package-data |
| `README.md` | Modify | Comprehensive rewrite |
| `.env.example` | Modify | New env vars |

---

## Integration Points (execution order)

```
main.py
  → resolve_config() (cli/config.py)
  → load_settings() (cli/config.py)          # NEW
  → HookRunner.from_settings() (hooks/)      # NEW
  → build_llm() (provider/)
  → run_repl() (cli/repl.py)
      → SkillRegistry.discover() (skills/)   # NEW
      → MemoryManager (memory/)              # NEW
      → hook_runner.run(SESSION_START)       # NEW
      → SessionState.new() / from_dict()     # MODIFIED
      → _repl_loop()
          → slash commands including skill commands
          → session.push_human(text)
          → run_agent()                      # MODIFIED
              → build_system_prompt()        # NEW
              → hook_runner.run(PRE_QUERY)   # NEW
              → llm.ainvoke()
              → hook_runner.run(POST_QUERY)  # NEW
              → hook_runner.run(PRE_TOOL_USE, tool_name)  # NEW
              → orchestrator.execute_batch()
              → hook_runner.run(POST_TOOL_USE, tool_name) # NEW
      → hook_runner.run(SESSION_END)         # NEW
```

---

## Verification

### Unit tests (run existing + new):
```bash
python -m pytest tests/ -q
```

### Integration smoke test:
```bash
# 1. Check all tools appear
zwis tools

# 2. Skills are discovered
zwis chat  # type /skills

# 3. Web tools work
zwis run "fetch https://httpbin.org/json and show the result"

# 4. Skills work
zwis chat  # type /commit

# 5. Memory loads
zwis chat  # type /memory

# 6. Hooks run (put echo in .zwis/settings.json)
# 7. Session resume
zwis chat  # /save
zwis chat --continue

# 8. Plan mode (read-only)
zwis chat --plan  # confirm write tools are denied
```

### Verify new imports don't break on missing optional deps:
```bash
python -c "from src.tools.web import WebFetchTool; print('ok')"
# ddgs missing → graceful error, not import crash
```

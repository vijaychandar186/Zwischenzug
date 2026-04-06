# Tool System Overview

## Tool Interface

Every tool in the system extends the `Tool` base class defined in `src/tools/__init__.py`:

```python
class Tool(ABC):
    name: str              # Unique tool identifier
    description: str       # Description shown to the model
    read_only: bool        # Whether tool only reads (never writes)

    async def execute(self, context: ToolContext, **kwargs) -> str:
        """Execute the tool and return a string result."""
        ...
```

### Tool Registration

Core tools are registered via `default_registry()` in `src/tools/__init__.py`. Graph tools are conditionally registered only when `.zwis/graph/graph.json` exists, and MCP tools are dynamically registered at REPL / single-run startup from configured MCP servers in `.zwis/mcp.json` and `~/.zwis/mcp.json`.

---

## Available Tools

| Tool | Module | Read-Only | Description |
|------|--------|-----------|-------------|
| `bash` | `tools/bash.py` | No | Execute shell commands (async, 30s timeout) |
| `read_file` | `tools/files.py` | Yes | Read file with line numbers, offset/limit |
| `write_file` | `tools/files.py` | No | Write/overwrite a file |
| `edit_file` | `tools/files.py` | No | Replace a unique string in a file |
| `glob` | `tools/search.py` | Yes | Find files by pattern, sorted by mtime |
| `grep` | `tools/search.py` | Yes | Regex search with context lines |
| `web_fetch` | `tools/web.py` | Yes | Fetch URL → markdown / JSON / raw |
| `web_search` | `tools/web.py` | Yes | DuckDuckGo search, no API key needed |
| `todo_write` | `tools/auxiliary.py` | No | Session todo list for tracking progress |
| `ask_user` | `tools/auxiliary.py` | No | Pause and ask user a clarifying question |
| `mcp__<server>__<tool>` | `mcp/runtime.py` | Depends | Dynamic MCP tool proxy loaded from configured servers |
| `mcp__<server>__list_resources` | `mcp/runtime.py` | Yes | List resources exposed by an MCP server |
| `mcp__<server>__read_resource` | `mcp/runtime.py` | Yes | Read one resource by URI from an MCP server |
| `graph_search` | `tools/graph_tools.py` | Yes | Search knowledge graph by name/type |
| `graph_explain` | `tools/graph_tools.py` | Yes | Explain a module/class/function |
| `graph_impact` | `tools/graph_tools.py` | Yes | Impact analysis before editing |
| `graph_trace` | `tools/graph_tools.py` | Yes | Trace execution call chain |
| `graph_refs` | `tools/graph_tools.py` | Yes | Find all references to a symbol |
| `graph_map` | `tools/graph_tools.py` | Yes | Architecture overview |
| `subagent` | `tools/subagent.py` | No | Spawn a child agent for a subtask |
| `spawn_agent` | `tools/agent_pool.py` | No | Launch a background child agent |
| `message_agent` | `tools/agent_pool.py` | No | Send follow-up message to a running agent |
| `wait_agent` | `tools/agent_pool.py` | Yes | Wait for an agent and get its output |
| `list_agents` | `tools/agent_pool.py` | Yes | List all spawned agents and status |
| `interrupt_agent` | `tools/agent_pool.py` | No | Cancel a running agent |
| `plan` | `tools/planning.py` | No | Create/update structured implementation plans |
| `plan_mode` | `tools/planning.py` | Yes | Toggle read-only plan mode on/off |
| `apply_patch` | `tools/patch.py` | No | Apply unified diff patches to files |
| `shell_create` | `tools/shell_session.py` | No | Create a persistent named shell |
| `shell_exec` | `tools/shell_session.py` | No | Execute command in a persistent shell |
| `shell_list` | `tools/shell_session.py` | Yes | List active shell sessions |
| `shell_close` | `tools/shell_session.py` | No | Close a persistent shell |
| `sandbox` | `tools/sandbox.py` | No | Configure sandbox profiles for isolation |
| `browser` | `tools/browser.py` | No | Low-level browser automation (open, click, type, etc.) |
| `browser_agent` | `tools/browser_agent.py` | No | Autonomous browser agent — give it a task in plain English |
| `notebook_edit` | `tools/notebook.py` | No | Edit Jupyter notebook cells |
| `worktree_create` | `tools/worktree.py` | No | Create a git worktree for isolation |
| `worktree_list` | `tools/worktree.py` | Yes | List managed worktrees |
| `worktree_merge` | `tools/worktree.py` | No | Merge worktree back and clean up |
| `worktree_remove` | `tools/worktree.py` | No | Discard worktree without merging |
| `task_start` | `tools/background.py` | No | Start a background task |
| `task_output` | `tools/background.py` | Yes | Get background task output |
| `task_status` | `tools/background.py` | Yes | List background tasks |
| `task_stop` | `tools/background.py` | No | Stop a running background task |
| `plugin` | `plugins/__init__.py` | No | Manage external plugins |

---

## Permission Model

Each tool invocation passes through the permission system:

1. Check if the tool is allowed by the current permission mode
2. Check against allow/deny rules in `.zwis/settings.json`
3. Fire `PreToolUse` hooks (can block execution)
4. Execute the tool
5. Fire `PostToolUse` hooks

Read-only tools are generally auto-approved. Write tools may require user confirmation depending on the permission mode.

---

## Execution

Tools are executed asynchronously. The tool orchestrator:

1. Validates input parameters
2. Checks permissions
3. Executes the tool (write tools serialized, read-only tools parallelizable)
4. Returns the result string to the agent for inclusion in conversation history

---

## Adding a New Tool

1. Create a new class extending `Tool` in the appropriate file under `src/tools/`
2. Implement `execute(context, **kwargs)` returning a string result
3. Register the tool in `default_registry()` in `src/tools/__init__.py`

For MCP-backed tools, add or update the server configuration instead of editing the core registry. The runtime will discover the server, list its tools/resources, and expose them under `mcp__...` names automatically.

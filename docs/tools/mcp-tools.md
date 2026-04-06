# MCP Tools

## Overview

Zwischenzug can connect to external MCP servers and expose their tools and resources directly to the agent at runtime.

MCP integration lives in:

- `src/mcp/config.py` — persistent server definitions
- `src/mcp/runtime.py` — session handling, discovery, tool proxies, resource readers

---

## How MCP Tools Are Loaded

When `zwis chat` or `zwis run` starts, the runtime:

1. Loads enabled MCP servers from `~/.zwis/mcp.json` and `.zwis/mcp.json`
2. Connects to each server over `stdio`, `http`, or `sse`
3. Calls `list_tools()` and `list_resources()`
4. Registers proxy tools into the in-memory tool registry

The generated tool names follow this pattern:

- `mcp__<server>__<tool>`
- `mcp__<server>__list_resources`
- `mcp__<server>__read_resource`

Examples:

- `mcp__github__search_issues`
- `mcp__sentry__list_resources`
- `mcp__sentry__read_resource`

---

## Resource Access

If a server exposes resources, Zwischenzug adds two helper tools:

- `mcp__<server>__list_resources` — lists resource names, URIs, and descriptions
- `mcp__<server>__read_resource` — reads a specific resource by URI

These helpers are always read-only.

---

## Read-Only vs Write Semantics

For proxied MCP tools, read-only behavior is inferred from the MCP tool annotations when the server provides them.

- `readOnlyHint = true` → treated as read-only
- otherwise → treated as write-capable for permission purposes

This means MCP tools automatically participate in the same permission flow as built-in tools.

---

## Failure Behavior

If one MCP server fails discovery:

- the CLI still starts
- the failure is logged
- other MCP servers can still register successfully

If a proxied MCP tool call fails, the tool result is returned as an error message instead of crashing the session.

# Graph Intelligence Tools

## Overview

Graph tools (`src/tools/graph_tools.py`) provide 6 read-only LLM tools for querying the knowledge graph. They are only registered when `.zwis/graph/graph.json` exists (i.e., after `zwis learn`).

All graph tools lazy-load the graph from disk on first access.

---

## GraphSearchTool

**Name**: `graph_search`

Search the knowledge graph by name or type.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `query` | string | Yes | Name or partial name to search for |
| `node_type` | string | No | Filter by type (file, class, function, method, etc.) |

Returns matching nodes with their type, file location, and line numbers.

---

## GraphExplainTool

**Name**: `graph_explain`

Explain a module, class, or function — its structure, dependencies, and callers.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Name of the symbol to explain |

Returns:
- Symbol type and location
- Structure (methods for classes, parameters for functions)
- Dependencies (what it imports/calls)
- Dependents (what calls/imports it)
- Summary

---

## GraphImpactTool

**Name**: `graph_impact`

Blast-radius analysis — what could break if a symbol changes.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Name of the symbol to analyze |

Returns:
- Risk level: `low`, `medium`, or `high`
- Affected files and symbols
- Impact tree visualization

---

## GraphTraceTool

**Name**: `graph_trace`

Trace the call chain from a function or entry point.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Entry point function name |
| `depth` | int | No | Maximum trace depth (default: 5) |

Returns a call graph trace showing what the function calls and what those functions call, recursively.

---

## GraphRefsTool

**Name**: `graph_refs`

Find every reference to a symbol (equivalent to IDE "Find All References").

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Symbol name to find references for |

Returns a list of references with file paths and line numbers.

---

## GraphMapTool

**Name**: `graph_map`

Bird's-eye architecture overview of the entire codebase.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `max_files` | int | No | Limit to top N files (default: all) |

Returns an ASCII architecture map showing modules and their relationships.

---

## CLI Equivalents

Each graph tool has a corresponding CLI command:

| Tool | CLI Command |
|------|-------------|
| `graph_search` | (available in REPL via natural language) |
| `graph_explain` | `zwis explain <symbol>` |
| `graph_impact` | `zwis impact-change <symbol>` |
| `graph_trace` | `zwis trace <function>` |
| `graph_refs` | (available in REPL via natural language) |
| `graph_map` | `zwis map` |

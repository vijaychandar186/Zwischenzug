# Knowledge Graph Engine

## Overview

Zwischenzug includes a pure-Python, in-memory knowledge graph engine that models the structure and dependencies of a codebase. The graph is built by AST analysis and stored as JSON — no external database required.

The graph engine lives in `src/graph/` and provides the data layer for all graph intelligence features.

---

## Core Components

### GraphEngine (`src/graph/__init__.py`)

The main orchestrator. Maintains:
- `nodes`: dict of `node_id → GraphNode`
- `edges`: dict of `edge_id → GraphEdge`

Key methods:
- `find_by_name_partial(query)` — Search nodes by partial name match
- `bfs_reverse(node_id)` — Find all callers/dependents (who calls this?)
- `bfs_forward(node_id)` — Find all callees/dependencies (what does this call?)
- `stats()` — Node/edge/reference counts
- `top_level_files()` — Most referenced files

### Schema (`src/graph/schema.py`)

#### Node Types

| Type | Examples |
|------|---------|
| `FILE` | `src/tools/bash.py` |
| `CLASS` | `BashTool`, `GraphEngine` |
| `FUNCTION` | `run_agent`, `build_system_prompt` |
| `METHOD` | `BashTool.execute`, `GraphEngine.bfs_reverse` |
| `VARIABLE` | Module-level constants |
| `MODEL` | ORM/DB models |
| `ROUTE` | API endpoints |
| `SERVICE` | Service classes |
| `TEST` | Test functions/classes |
| `EXTERNAL` | `asyncio`, `langchain_core` |

#### Edge Types

| Edge | Meaning |
|------|---------|
| `IMPORTS` | File imports another module |
| `CALLS` | Function/method calls another |
| `EXTENDS` | Class inherits from another |
| `IMPLEMENTS` | Class implements an interface |
| `READS_DB` | Code reads from database |
| `WRITES_DB` | Code writes to database |
| `DEPENDS_ON` | General dependency |
| `RETURNS` | Function returns a type |
| `USES` | Code uses a symbol |
| `DEFINES` | Module defines a symbol |
| `CONTAINS` | File contains a class/function |

#### Data Structures

- **GraphNode**: `id`, `type`, `name`, `file`, `start_line`, `end_line`, `summary`, `metadata`
- **GraphEdge**: `from_id`, `to_id`, `type`
- **Reference**: `file`, `line`, `symbol` (for line-level index)

### Storage (`src/graph/storage.py`)

The graph is persisted as two JSON files in `.zwis/graph/`:

- `graph.json` — Serialized nodes and edges
- `meta.json` — Build metadata including per-file modification times (for incremental builds)

### Traversal (`src/graph/traversal.py`)

Higher-level analysis functions:

- `impact_analysis(node_id)` — Blast-radius: what breaks if this changes? Returns risk level (low/medium/high) and affected files.
- `trace_flow(entry_point, depth)` — Call graph trace from an entry point.
- `explain_module(node_id)` — Structure, dependencies, callers, and summary of a module/class/function.

### Visualizer (`src/graph/visualizer.py`)

ASCII output generators:

- Architecture map (bird's-eye view of all modules)
- Dependency trees
- Impact trees (blast-radius visualization)

---

## Graph Lifecycle

1. **Build**: `zwis learn` triggers a full scan (or incremental rebuild if files haven't changed)
2. **Persist**: Graph is saved to `.zwis/graph/graph.json`
3. **Load**: Graph tools lazy-load from JSON when first accessed
4. **Query**: LLM tools and CLI commands query the in-memory graph
5. **Inject**: A graph context summary is injected into the system prompt

---

## Performance

The graph engine is designed for fast builds on medium-sized codebases:
- ~1200 nodes on this repo in ~2.5 seconds
- Incremental builds skip unchanged files using `meta.json` timestamps
- In-memory graph queries are sub-millisecond

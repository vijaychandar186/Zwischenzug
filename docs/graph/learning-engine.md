# Learning Engine

## Overview

The learning engine (`src/learning/`) is responsible for scanning a repository, parsing source files, building the knowledge graph, and generating knowledge files. It is triggered by the `zwis learn` CLI command.

---

## Components

### LearningEngine (`src/learning/__init__.py`)

The orchestrator that runs a full learning pass:

1. `scan_files()` — Find all Python files, skipping ignored directories
2. `parse_files()` — AST-parse each file to extract structure
3. `build_graph()` — Convert parsed files into nodes and edges
4. `track_references()` — Record line-level symbol usage
5. `detect_frameworks()` — Check pyproject.toml / requirements.txt
6. `generate_knowledge()` — Write `.zwis/knowledge/*.md` files
7. `fetch_docs()` — Optional framework documentation download

#### Skipped Directories

The scanner skips: `.git`, `.zwis`, `venv`, `__pycache__`, `node_modules`, `.tox`, `.mypy_cache`, `dist`, `build`, `*.egg-info`, and similar non-source directories.

### AST Parser (`src/learning/ast_parser.py`)

Uses Python's stdlib `ast` module to extract:
- Class definitions (name, bases, methods, line numbers)
- Function definitions (name, args, decorators, line numbers)
- Method definitions (bound to their class)
- Import statements (what is imported from where)
- Call sites (which functions call which, with line numbers)
- Variable assignments (module-level constants)

### Reference Tracker (`src/learning/reference.py`)

Builds a line-level index of symbol usage:
- Maps `symbol_name → [Reference(file, line, symbol)]`
- Enables "Find All References" functionality via `graph_refs` tool

### Framework Detector (`src/learning/frameworks.py`)

Detects 20+ frameworks by checking:
- `pyproject.toml` dependencies
- `requirements.txt` entries
- `importlib.metadata` installed packages

Detected frameworks include: FastAPI, Flask, Django, SQLAlchemy, Pydantic, LangChain, Celery, pytest, and many more.

### Knowledge Generator (`src/learning/knowledge.py`)

Writes compressed knowledge files to `.zwis/knowledge/`:
- One file per module with substantial content
- Architecture overview file
- Master index file

See [knowledge-files.md](knowledge-files.md) for format details.

### Docs Fetcher (`src/learning/docs_fetcher.py`)

When `--fetch-docs` is passed, downloads official documentation for detected frameworks to `.zwis/docs/`. This gives the LLM access to framework-specific reference material.

---

## CLI Usage

```bash
zwis learn                   # Full scan + graph build + knowledge generation
zwis learn --fetch-docs      # Also fetch framework documentation
zwis learn /path/to/repo     # Scan a different directory
```

---

## Incremental Builds

The learning engine supports incremental builds:

1. On first run: full scan of all files
2. On subsequent runs: checks `meta.json` for per-file modification times
3. Only re-parses files that have changed since the last build
4. Rebuilds affected portions of the graph

This makes repeated `zwis learn` calls fast on large codebases.

---

## LearningResult

The `scan()` method returns a `LearningResult` with statistics:
- `parsed_files`: Number of files parsed
- `total_nodes`: Number of graph nodes created
- `total_edges`: Number of graph edges created
- `frameworks`: List of detected frameworks
- `knowledge_files`: Number of knowledge files generated

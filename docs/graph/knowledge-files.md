# Knowledge Files

## Overview

After `zwis learn`, compressed knowledge files are written to `.zwis/knowledge/`. These provide the LLM with pre-digested summaries of the codebase that are more token-efficient than reading raw source.

---

## File Structure

```
.zwis/knowledge/
├── INDEX.md                    ← Master index of all knowledge files
├── architecture.md             ← Overall structure, frameworks, module list
├── src-tools-bash-py.md        ← Per-module: purpose, classes, functions, deps
├── src-core-agent-py.md        ← One file per module with substantial content
└── ...
```

---

## File Format

Knowledge files follow a consistent format:

### INDEX.md

Lists all generated knowledge files with one-line descriptions.

### architecture.md

- Detected frameworks and their roles
- Module dependency overview
- Top-level file list with purposes
- Key architectural patterns

### Per-Module Files

Each module file follows this structure:

```markdown
# module-name

## Purpose
Brief description of what the module does.

## Key Components
- Classes, functions, and their roles

## Dependencies
- What this module imports and depends on

## Used By
- What other modules depend on this one

## Risks
- What could break if this module is changed
```

---

## System Prompt Integration

Knowledge files are referenced in the system prompt in two ways:

1. **Graph context summary**: A brief overview is injected via `load_graph_context()` — total nodes, edges, frameworks, and architecture highlights
2. **On-demand reading**: The LLM can use `read_file` to access any knowledge file in `.zwis/knowledge/` when it needs deeper understanding

---

## CLI Access

```bash
zwis knowledge                    # List all knowledge files
zwis knowledge architecture       # View architecture.md
zwis knowledge INDEX              # View the master index
```

Inside the REPL:
```
/knowledge                        # List all knowledge files
/knowledge architecture           # View a specific file
```

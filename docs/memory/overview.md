# Memory System

## Overview

Zwischenzug supports persistent memories that survive across sessions. Memories store personal, cross-session context — user preferences, project decisions, feedback on approach — not code patterns or architecture (those belong in the knowledge graph).

---

## Memory Storage

Memories are stored as individual Markdown files with YAML frontmatter in `~/.zwis/memory/`:

```
~/.zwis/memory/
├── MEMORY.md                ← Index file (loaded into every session)
├── user_role.md             ← Individual memory file
├── feedback_testing.md      ← Individual memory file
└── project_auth_rewrite.md  ← Individual memory file
```

### MEMORY.md Index

`MEMORY.md` is the index file. Each entry is a one-line pointer to a memory file:

```markdown
# Memory Index

- [User Role](user_role.md) — Senior backend engineer, new to frontend
- [Testing Preference](feedback_testing.md) — Use real DB, not mocks
```

This index is injected into the system prompt so the agent knows what memories exist.

### Memory File Format

```markdown
---
name: testing-preference
description: User prefers integration tests over unit tests
type: feedback
---
Always write integration tests that hit a real database rather than mocking.

**Why:** Mocked tests passed but prod migration failed last quarter.
**How to apply:** When writing tests, default to integration tests with real DB.
```

---

## Memory Types

| Type | Purpose |
|------|---------|
| `user` | User's role, goals, preferences, knowledge level |
| `feedback` | Corrections and confirmations about approach |
| `project` | Ongoing work, decisions, deadlines, stakeholder context |
| `reference` | Pointers to external resources (Linear projects, dashboards, etc.) |

---

## System Prompt Injection

The `MEMORY.md` index is injected into the system prompt by `build_system_prompt()`. This gives the agent awareness of stored memories without loading all memory file contents.

When a memory is relevant, the agent can read the full memory file using `read_file`.

---

## REPL Commands

```
/memory              — List all memories
/memory <name>       — View a specific memory file
```

---

## What NOT to Store in Memory

- Code patterns, conventions, or architecture (use knowledge graph)
- Git history or recent changes (use `git log`)
- Debugging solutions (the fix is in the code)
- Ephemeral task details or current conversation context

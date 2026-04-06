# System Prompt Construction

## Overview

Before each agent turn, a system prompt is assembled from multiple sources. This document describes what goes into the system prompt and how it is constructed.

---

## System Prompt Components

The final system prompt is built by `build_system_prompt()` in `src/core/system_prompt.py`, concatenating these components in order:

### 1. Base Prompt

The default system prompt (`DEFAULT_SYSTEM_PROMPT`) defines:
- The assistant's persona and role as an AI coding agent
- Behavioral guidelines (how to approach tasks, tool use etiquette)
- Safety constraints
- Output format preferences
- Error handling guidance

### 2. Project Instructions (ZWISCHENZUG.md)

If a `ZWISCHENZUG.md` file exists in the project root, its contents are appended. This serves the same role as a project-level instruction file — teams can commit shared instructions that customize agent behavior for their codebase.

### 3. Memory Index (MEMORY.md)

If `~/.zwis/memory/MEMORY.md` exists, its contents are injected. This provides the agent with persistent cross-session context about the user, their preferences, and ongoing work.

### 4. Knowledge Graph Context

If a knowledge graph exists (`.zwis/graph/graph.json`), `load_graph_context()` generates a brief summary:
- Total node and edge counts
- Top-level file list
- Framework detection results
- Architecture overview snippet

This gives the LLM awareness of the codebase structure without consuming excessive tokens.

### 5. Skill Context

Active skills contribute their descriptions and capabilities to the system prompt, so the LLM knows what slash commands are available and what they do.

---

## Token Budget

The system prompt has a soft token budget. When the combined prompt exceeds the budget:
- Graph context is truncated first (least critical)
- Memory index is truncated next
- Base prompt and project instructions are never truncated

---

## Prompt Assembly Order

```
┌─────────────────────────────┐
│     DEFAULT_SYSTEM_PROMPT   │  ← Always present
├─────────────────────────────┤
│     ZWISCHENZUG.md          │  ← If exists in project root
├─────────────────────────────┤
│     MEMORY.md index         │  ← If exists in ~/.zwis/memory/
├─────────────────────────────┤
│     Graph context summary   │  ← If .zwis/graph/graph.json exists
├─────────────────────────────┤
│     Skill descriptions      │  ← Active skills
└─────────────────────────────┘
```

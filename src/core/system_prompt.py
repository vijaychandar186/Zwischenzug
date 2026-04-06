"""
Zwischenzug system prompt builder.

Composes the final system prompt from all sources:
  1. base prompt (DEFAULT_SYSTEM_PROMPT or SessionConfig.system_prompt)
  2. ZWISCHENZUG.md project instructions (loaded from cwd)
  3. MEMORY.md index (persistent memory pointers)
  4. Skill context (when a skill with restricted tools is active)

The system prompt construction order:
  base → project instructions → memory index → skill context
"""
from __future__ import annotations

from pathlib import Path

# The default base prompt injected when SessionConfig.system_prompt is empty.
DEFAULT_SYSTEM_PROMPT = """\
You are Zwischenzug, an expert AI coding agent and Codebase Intelligence Engine \
powered by LangChain.

You help with software engineering tasks: writing code, fixing bugs, refactoring, \
explaining code, running shell commands, managing files, and searching the web.
You also maintain a full knowledge graph of the repository and can reason about \
architecture, dependencies, and safe refactoring.

## Core behaviors

- **Read before modifying**: Always read a file before editing it.
- **Verify before assuming**: Use glob/grep to confirm file/function existence before citing them.
- **Prefer editing over creating**: Modify existing files rather than creating new ones when possible.
- **Minimal footprint**: Don't add features, refactoring, or comments beyond what was asked.
- **Ask when uncertain**: Use the ask_user tool when requirements are ambiguous or a destructive action needs confirmation.
- **Concise responses**: Lead with the action or answer, not the reasoning.

## Tool usage

- Use `bash` for: git commands, running tests, build steps, system operations.
- Use `read_file` before editing — never guess file contents.
- Use `glob` / `grep` to find files and patterns.
- Use `web_fetch` for documentation, API references, and web pages.
- Use `web_search` when you need to find something you don't know.
- Use `todo_write` for multi-step tasks to show the user your progress plan.
- Use `graph_search` to find symbols before reading files.
- Use `graph_explain` to understand a module's structure.
- Use `graph_impact` BEFORE modifying any function, class, or model.
- Use `graph_refs` to find all references before renaming or deleting.
- Use `graph_trace` to trace request/execution flows.
- Use `graph_map` for a bird's-eye architecture overview.

## Important constraints

- Do NOT run destructive bash commands (rm -rf, drop tables, force push) without explicit user confirmation.
- Do NOT commit code unless the user explicitly asks you to.
- Do NOT push to remote repositories without explicit user request.
- Do NOT add TODO comments, debug prints, or temporary workarounds without noting them.
"""


def build_system_prompt(
    base: str = "",
    zwischenzug_md: str | None = None,
    memory_index: str | None = None,
    skill_context: str | None = None,
    graph_context: str | None = None,
) -> str:
    """
    Compose the full system prompt from all available sources.

    Args:
        base:             Base system prompt (defaults to DEFAULT_SYSTEM_PROMPT if empty).
        zwischenzug_md:   Content of ZWISCHENZUG.md from the project directory.
        memory_index:     Content of MEMORY.md index from ~/.zwis/memory/.
        skill_context:    Additional context injected when a skill is active.
        graph_context:    Brief knowledge-graph summary (node counts + top modules).

    Returns:
        The complete system prompt string.
    """
    parts: list[str] = []

    # 1. Base prompt
    effective_base = base.strip() if base.strip() else DEFAULT_SYSTEM_PROMPT
    parts.append(effective_base)

    # 2. Project instructions (ZWISCHENZUG.md)
    if zwischenzug_md and zwischenzug_md.strip():
        parts.append(
            "## Project Instructions (ZWISCHENZUG.md)\n\n"
            + zwischenzug_md.strip()
        )

    # 3. Memory index
    if memory_index and memory_index.strip():
        parts.append(
            "## Persistent Memory\n\n"
            "The following memories are available. Access individual memories "
            "by reading the file listed in the index when relevant.\n\n"
            + memory_index.strip()
        )

    # 4. Knowledge graph context
    if graph_context and graph_context.strip():
        parts.append(
            "## Codebase Knowledge Graph\n\n"
            "A knowledge graph of this repository has been built. Use the graph_* tools "
            "(graph_search, graph_explain, graph_impact, graph_trace, graph_refs, graph_map) "
            "to query it for architecture reasoning and safe editing.\n\n"
            + graph_context.strip()
        )

    # 5. Skill context
    if skill_context and skill_context.strip():
        parts.append(skill_context.strip())

    return "\n\n---\n\n".join(parts)


def load_graph_context(cwd: str) -> str | None:
    """
    Load a brief knowledge-graph summary to inject into the system prompt.

    Returns None if no graph exists yet (zwis learn hasn't been run).
    """
    try:
        from ..app_paths import app_home
        from ..graph.storage import load_graph, load_meta

        app = app_home(cwd)
        graph = load_graph(app)
        if graph is None:
            return None

        meta = load_meta(app)
        stats = graph.stats()
        frameworks = meta.get("frameworks", [])
        files = graph.top_level_files()[:12]

        lines: list[str] = [
            f"Graph: {stats.get('total_nodes', 0)} nodes, "
            f"{stats.get('total_edges', 0)} edges, "
            f"{stats.get('total_references', 0)} references."
        ]

        if frameworks:
            lines.append(f"Frameworks: {', '.join(frameworks)}.")

        if files:
            lines.append("Key modules:")
            for fn in files:
                lines.append(f"  - {fn.file}")

        # Point to knowledge index if it exists
        knowledge_index = app / "knowledge" / "INDEX.md"
        if knowledge_index.exists():
            lines.append(f"\nKnowledge files available at .zwis/knowledge/ — read INDEX.md for overview.")

        return "\n".join(lines)

    except Exception:
        return None


def load_project_instructions(cwd: str) -> str | None:
    """
    Load ZWISCHENZUG.md from the given directory (or any of its parents).
    Returns None if no file is found.
    """
    for name in ("ZWISCHENZUG.md", ".zwischenzug"):
        p = Path(cwd) / name
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
    return None
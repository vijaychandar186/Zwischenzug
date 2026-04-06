"""
Knowledge file generator.

Creates compressed Markdown knowledge files in .zwis/knowledge/ that give
the LLM a dense, queryable overview of the repository — without needing to
parse source files every turn.

File format follows the Zwischenzug knowledge style:

    # Module: src/tools/bash.py
    ## Purpose
    ## Key Components
    ## Dependencies
    ## Used By
    ## Risks
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..graph import GraphEngine
from ..graph.schema import EdgeType, NodeType
from .frameworks import FrameworkInfo


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class KnowledgeGenerator:
    """Generates .zwis/knowledge/*.md files from the knowledge graph."""

    def __init__(self, cwd: str, engine: GraphEngine) -> None:
        self._cwd = Path(cwd)
        self._g = engine
        self._knowledge_dir = self._cwd / ".zwis" / "knowledge"

    def generate_all(self, frameworks: list[FrameworkInfo]) -> list[str]:
        """
        Generate all knowledge files.  Returns list of created paths.
        """
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        created: list[str] = []

        # 1. architecture.md — overall structure
        p = self._write("architecture.md", self._architecture_doc(frameworks))
        created.append(p)

        # 2. Per-file knowledge (only files with substantial content)
        for file_node in self._g.find_by_type(NodeType.FILE):
            classes = [n for n in self._g.find_by_file(file_node.file) if n.type == NodeType.CLASS]
            fns = [n for n in self._g.find_by_file(file_node.file) if n.type == NodeType.FUNCTION]
            methods = [n for n in self._g.find_by_file(file_node.file) if n.type == NodeType.METHOD]

            if not (classes or fns or methods):
                continue  # empty/trivial file

            slug = _file_slug(file_node.file)
            p = self._write(f"{slug}.md", self._module_doc(file_node, classes, fns, methods))
            created.append(p)

        # 3. INDEX.md — master index
        p = self._write("INDEX.md", self._index_doc(frameworks, created))
        created.append(p)

        return created

    # ------------------------------------------------------------------
    # Architecture document
    # ------------------------------------------------------------------

    def _architecture_doc(self, frameworks: list[FrameworkInfo]) -> str:
        g = self._g
        stats = g.stats()

        lines: list[str] = [
            "# Architecture Overview\n",
            f"*Generated: {_now()}*\n",
            "## Purpose",
            "This document summarises the repository structure as understood by "
            "the knowledge graph engine.\n",
        ]

        # Frameworks
        if frameworks:
            lines.append("## Frameworks & Libraries")
            for fw in frameworks:
                ver = f" {fw.version}" if fw.version else ""
                lines.append(f"- **{fw.display}**{ver} — {fw.doc_url}")
            lines.append("")

        # Top-level modules
        files = sorted(g.find_by_type(NodeType.FILE), key=lambda n: n.file)
        if files:
            lines.append("## Modules")
            for fn in files:
                classes = [n for n in g.find_by_file(fn.file) if n.type == NodeType.CLASS]
                fns = [n for n in g.find_by_file(fn.file) if n.type == NodeType.FUNCTION]
                label_parts: list[str] = []
                if classes:
                    names = ", ".join(c.name for c in classes[:3])
                    suffix = " …" if len(classes) > 3 else ""
                    label_parts.append(f"classes: {names}{suffix}")
                if fns:
                    label_parts.append(f"{len(fns)} functions")
                detail = f"  ({'; '.join(label_parts)})" if label_parts else ""
                lines.append(f"- `{fn.file}`{detail}")
            lines.append("")

        # Routes (if any)
        routes = g.find_by_type(NodeType.ROUTE)
        if routes:
            lines.append("## API Routes")
            for r in routes[:20]:
                lines.append(f"- `{r.name}`  ({r.file}:{r.start_line})")
            lines.append("")

        # Models (if any)
        models = g.find_by_type(NodeType.MODEL)
        if models:
            lines.append("## Data Models")
            for m in models[:20]:
                lines.append(f"- `{m.name}`  ({m.file}:{m.start_line})")
            lines.append("")

        # Stats
        lines.append("## Graph Stats")
        lines.append(f"- Nodes: {stats.get('total_nodes', 0)}")
        lines.append(f"- Edges: {stats.get('total_edges', 0)}")
        lines.append(f"- Line references: {stats.get('total_references', 0)}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Per-module document
    # ------------------------------------------------------------------

    def _module_doc(
        self,
        file_node: Any,
        classes: list[Any],
        fns: list[Any],
        methods: list[Any],
    ) -> str:
        g = self._g
        lines: list[str] = [
            f"# Module: `{file_node.file}`\n",
            f"*Generated: {_now()}*\n",
        ]

        # Purpose from summary
        if file_node.summary:
            lines.append("## Purpose")
            lines.append(file_node.summary)
            lines.append("")

        # Key components
        lines.append("## Key Components")
        for cls in sorted(classes, key=lambda n: n.start_line):
            lines.append(f"\n### Class `{cls.name}`  (line {cls.start_line})")
            if cls.summary:
                lines.append(cls.summary)
            cls_methods = [
                m for m in methods
                if m.id.startswith(f"{file_node.file}::{cls.name}::")
            ]
            if cls_methods:
                lines.append("**Methods:**")
                for m in sorted(cls_methods, key=lambda n: n.start_line):
                    suffix = " *(async)*" if m.metadata.get("is_async") else ""
                    lines.append(f"- `{m.name}()`  line {m.start_line}{suffix}")

        for fn in sorted(fns, key=lambda n: n.start_line):
            suffix = " *(async)*" if fn.metadata.get("is_async") else ""
            lines.append(f"\n### Function `{fn.name}()`  (line {fn.start_line}){suffix}")
            if fn.summary:
                lines.append(fn.summary)

        lines.append("")

        # Dependencies
        dep_ids = [
            e.to_id for e in g.outgoing_edges(file_node.id)
            if e.relationship in (EdgeType.IMPORTS, EdgeType.DEPENDS_ON)
        ]
        if dep_ids:
            lines.append("## Dependencies")
            for dep_id in dep_ids[:15]:
                dep = g.get_node(dep_id)
                if dep:
                    lines.append(f"- `{dep.name}`")
            lines.append("")

        # Used by
        user_ids = [
            e.from_id for e in g.incoming_edges(file_node.id)
            if e.relationship in (EdgeType.IMPORTS, EdgeType.DEPENDS_ON)
        ]
        if user_ids:
            lines.append("## Used By")
            for uid in user_ids[:10]:
                src = g.get_node(uid)
                if src:
                    lines.append(f"- `{src.file or src.name}`")
            lines.append("")

        # Risks (heuristic)
        risks = _heuristic_risks(file_node, classes, fns, g)
        if risks:
            lines.append("## Risks")
            for r in risks:
                lines.append(f"- {r}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # INDEX
    # ------------------------------------------------------------------

    def _index_doc(self, frameworks: list[FrameworkInfo], created: list[str]) -> str:
        lines: list[str] = [
            "# Knowledge Index\n",
            f"*Generated: {_now()}*\n",
            "This directory contains compressed knowledge files for the repository.\n",
            "## Files",
        ]
        for p in sorted(created):
            name = Path(p).name
            lines.append(f"- [{name}]({name})")

        if frameworks:
            lines.append("\n## Detected Frameworks")
            for fw in frameworks:
                ver = f" ({fw.version})" if fw.version else ""
                lines.append(f"- {fw.display}{ver}: {fw.doc_url}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _write(self, filename: str, content: str) -> str:
        p = self._knowledge_dir / filename
        p.write_text(content, encoding="utf-8")
        return str(p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_slug(file_path: str) -> str:
    """Convert a file path to a safe filename slug."""
    slug = file_path.replace("/", "-").replace("\\", "-").replace(".", "-")
    # Remove leading dashes
    slug = slug.lstrip("-")
    # Collapse multiple dashes
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _now() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _heuristic_risks(
    file_node: Any,
    classes: list[Any],
    fns: list[Any],
    g: GraphEngine,
) -> list[str]:
    """Generate heuristic risk notes for a module."""
    risks: list[str] = []

    # High fan-in = many dependents = risky to change
    in_count = len(g.incoming_edges(file_node.id))
    if in_count >= 5:
        risks.append(f"High fan-in: {in_count} modules depend on this file — changes here are high-risk.")
    elif in_count >= 2:
        risks.append(f"Shared dependency: {in_count} modules import this file.")

    # Files with "auth", "security", "permission" in path need care
    fp_lower = file_node.file.lower()
    if any(kw in fp_lower for kw in ("auth", "security", "permission", "token", "secret", "password")):
        risks.append("Security-sensitive: contains auth/security logic — review changes carefully.")

    # Files with DB models
    db_edges = [
        e for e in g.outgoing_edges(file_node.id)
        if e.relationship in (EdgeType.READS_DB, EdgeType.WRITES_DB)
    ]
    if db_edges:
        risks.append("Database interaction: verify migrations when changing models.")

    return risks

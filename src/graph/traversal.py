"""
Graph traversal and reasoning — impact analysis, flow tracing, module explanation.

All methods are read-only.  They consume a GraphEngine and return structured
results or formatted strings ready for LLM context or CLI display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import GraphEngine, _DEPENDENCY_EDGES
from .schema import EdgeType, GraphNode, NodeType


# ---------------------------------------------------------------------------
# Impact report
# ---------------------------------------------------------------------------

@dataclass
class ImpactReport:
    """Result of an impact-change analysis for one symbol."""

    symbol: str
    root_node: GraphNode | None

    # Nodes reachable via incoming edges (things that USE this symbol)
    direct_dependents: list[GraphNode] = field(default_factory=list)   # depth 1
    transitive_dependents: list[GraphNode] = field(default_factory=list)  # depth 2+

    affected_files: list[str] = field(default_factory=list)
    risk_level: str = "low"   # "low" | "medium" | "high"

    # Extra context
    line_references: list[Any] = field(default_factory=list)   # Reference objects

    def total_affected(self) -> int:
        return len(self.direct_dependents) + len(self.transitive_dependents)

    def summary_line(self) -> str:
        n = self.total_affected()
        files = len(self.affected_files)
        return (
            f"Changing '{self.symbol}' affects {n} node(s) across {files} file(s) "
            f"[risk: {self.risk_level}]"
        )


# ---------------------------------------------------------------------------
# Traversal engine
# ---------------------------------------------------------------------------

class GraphTraversal:
    """High-level reasoning queries on a GraphEngine."""

    def __init__(self, engine: GraphEngine) -> None:
        self._g = engine

    # ------------------------------------------------------------------
    # Explain
    # ------------------------------------------------------------------

    def explain_module(self, name: str) -> str:
        """
        Return a multi-line explanation of a file/module.

        Tries to match `name` as a file path, module name, or partial path.
        """
        # Locate the file node
        file_node = self._resolve_file(name)
        if file_node is None:
            # Try as a class or function name
            nodes = self._g.find_by_name_partial(name)
            if not nodes:
                return f"No module or symbol found matching '{name}'."
            file_node = nodes[0]

        lines: list[str] = []
        lines.append(f"## {file_node.name}")
        if file_node.summary:
            lines.append(f"\n{file_node.summary}\n")

        # Classes defined in this file
        classes = [
            n for n in self._g.find_by_file(file_node.file or file_node.id)
            if n.type == NodeType.CLASS
        ]
        if classes:
            lines.append("### Classes")
            for cls in sorted(classes, key=lambda n: n.start_line):
                suffix = f" (line {cls.start_line})" if cls.start_line else ""
                lines.append(f"  - **{cls.name}**{suffix}")
                # Methods of this class
                methods = [
                    n for n in self._g.find_by_file(file_node.file or file_node.id)
                    if n.type == NodeType.METHOD
                    and n.id.startswith(f"{file_node.file or file_node.id}::{cls.name}::")
                ]
                for m in sorted(methods, key=lambda n: n.start_line):
                    lines.append(f"    - `{m.name}()` (line {m.start_line})")

        # Top-level functions
        fns = [
            n for n in self._g.find_by_file(file_node.file or file_node.id)
            if n.type == NodeType.FUNCTION
        ]
        if fns:
            lines.append("### Functions")
            for fn in sorted(fns, key=lambda n: n.start_line):
                suffix = f" (line {fn.start_line})" if fn.start_line else ""
                lines.append(f"  - `{fn.name}()`{suffix}")

        # Outgoing imports / dependencies
        deps: list[str] = []
        for edge in self._g.outgoing_edges(file_node.id):
            if edge.relationship in (EdgeType.IMPORTS, EdgeType.DEPENDS_ON):
                target = self._g.get_node(edge.to_id)
                if target:
                    deps.append(target.name)
        if deps:
            lines.append("### Dependencies")
            for d in sorted(set(deps)):
                lines.append(f"  - {d}")

        # Incoming: who uses this module?
        users: list[str] = []
        for edge in self._g.incoming_edges(file_node.id):
            src = self._g.get_node(edge.from_id)
            if src and src.type == NodeType.FILE:
                users.append(src.name)
        if users:
            lines.append("### Used by")
            for u in sorted(set(users)):
                lines.append(f"  - {u}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Impact analysis
    # ------------------------------------------------------------------

    def impact_analysis(self, symbol: str, max_depth: int = 5) -> ImpactReport:
        """
        Find all code that would break if `symbol` is changed.

        Performs reverse-BFS from the symbol node, collecting all nodes
        that (transitively) depend on it.
        """
        # Resolve symbol to a node
        root = self._resolve_symbol(symbol)
        refs = self._g.find_references(symbol)

        if root is None:
            return ImpactReport(
                symbol=symbol,
                root_node=None,
                line_references=refs,
            )

        # BFS reverse — who depends on this node?
        # Use semantic BFS to exclude structural edges like CONTAINS
        all_dependents = self._g.bfs_reverse_semantic(root.id, max_depth=max_depth)

        direct: list[GraphNode] = []
        transitive: list[GraphNode] = []

        # Separate depth-1 (direct) from deeper — only dependency edges
        depth_1_ids = {
            edge.from_id
            for edge in self._g.incoming_edges(root.id)
            if edge.relationship in _DEPENDENCY_EDGES
        }

        for node in all_dependents:
            if node.id in depth_1_ids:
                direct.append(node)
            else:
                transitive.append(node)

        affected_files = sorted({
            n.file for n in (direct + transitive) if n.file
        })

        total = len(direct) + len(transitive)
        if total == 0:
            risk = "low"
        elif total <= 3:
            risk = "medium"
        else:
            risk = "high"

        return ImpactReport(
            symbol=symbol,
            root_node=root,
            direct_dependents=direct,
            transitive_dependents=transitive,
            affected_files=affected_files,
            risk_level=risk,
            line_references=refs,
        )

    # ------------------------------------------------------------------
    # Flow trace
    # ------------------------------------------------------------------

    def trace_flow(self, entry_point: str, max_depth: int = 5) -> str:
        """
        Trace the call graph starting from `entry_point`.

        Returns an ASCII diagram of the call chain.
        """
        root = self._resolve_symbol(entry_point)
        if root is None:
            return f"Symbol '{entry_point}' not found in the knowledge graph."

        lines: list[str] = [f"Flow trace from: {root.name}"]
        lines.append(f"  ({root.type.value} in {root.file}, line {root.start_line})\n")

        visited: set[str] = set()
        self._trace_recursive(root.id, 0, max_depth, visited, lines, prefix="")
        return "\n".join(lines)

    def _trace_recursive(
        self,
        node_id: str,
        depth: int,
        max_depth: int,
        visited: set[str],
        lines: list[str],
        prefix: str,
    ) -> None:
        if depth >= max_depth or node_id in visited:
            if node_id in visited:
                node = self._g.get_node(node_id)
                name = node.name if node else node_id
                lines.append(f"{prefix}  ↺ {name} (already visited)")
            return

        visited.add(node_id)
        outgoing = self._g.outgoing_edges(node_id)

        call_edges = [e for e in outgoing if e.relationship == EdgeType.CALLS]

        for i, edge in enumerate(call_edges):
            is_last = i == len(call_edges) - 1
            connector = "└─" if is_last else "├─"
            child = self._g.get_node(edge.to_id)
            if child is None:
                continue

            location = f"  ({child.file}:{child.start_line})" if child.start_line else ""
            lines.append(f"{prefix}{connector} {child.name}(){location}")

            extension = "   " if is_last else "│  "
            self._trace_recursive(
                child.id, depth + 1, max_depth, visited, lines, prefix + extension
            )

    # ------------------------------------------------------------------
    # Module overview
    # ------------------------------------------------------------------

    def module_overview(self, max_files: int = 30) -> str:
        """Return a structured overview of top-level files with dependency counts."""
        files = self._g.top_level_files()[:max_files]

        if not files:
            return "No modules found. Run 'zwis learn' to build the knowledge graph."

        lines: list[str] = ["# Repository Module Overview\n"]

        for fnode in files:
            deps_out = len(self._g.outgoing_edges(fnode.id))
            deps_in = len(self._g.incoming_edges(fnode.id))

            classes = [
                n for n in self._g.find_by_file(fnode.file)
                if n.type == NodeType.CLASS
            ]
            fns = [
                n for n in self._g.find_by_file(fnode.file)
                if n.type == NodeType.FUNCTION
            ]

            label_parts = []
            if classes:
                label_parts.append(f"{len(classes)} class{'es' if len(classes) > 1 else ''}")
            if fns:
                label_parts.append(f"{len(fns)} function{'s' if len(fns) > 1 else ''}")

            detail = f"  [{', '.join(label_parts)}]" if label_parts else ""
            arrow = f"  ← {deps_in}" if deps_in else ""
            arrow += f"  → {deps_out}" if deps_out else ""

            lines.append(f"  {fnode.file}{detail}{arrow}")

        return "\n".join(lines)

    def find_callers(self, symbol: str) -> list[Any]:
        """Return all references that call `symbol`."""
        return [
            r for r in self._g.find_references(symbol)
            if r.relationship == EdgeType.CALLS
        ]

    def find_importers(self, module_name: str) -> list[GraphNode]:
        """Return all file nodes that import the given module."""
        target_nodes = self._g.find_by_name(module_name)
        importers: list[GraphNode] = []
        for tnode in target_nodes:
            for edge in self._g.incoming_edges(tnode.id):
                if edge.relationship == EdgeType.IMPORTS:
                    src = self._g.get_node(edge.from_id)
                    if src:
                        importers.append(src)
        return importers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_file(self, name: str) -> GraphNode | None:
        """Try to find a FILE node matching the given name (path or stem)."""
        # Exact ID match
        node = self._g.get_node(name)
        if node and node.type == NodeType.FILE:
            return node

        name_lower = name.lower()
        for fnode in self._g.find_by_type(NodeType.FILE):
            if (
                fnode.file.lower() == name_lower
                or fnode.file.lower().endswith(f"/{name_lower}.py")
                or fnode.file.lower().endswith(f"/{name_lower}")
                or fnode.name.lower() == name_lower
            ):
                return fnode

        return None

    def _resolve_symbol(self, symbol: str) -> GraphNode | None:
        """
        Resolve a symbol string to a GraphNode.

        Tries in order:
        1. Exact node ID
        2. Exact name match
        3. Partial name match (returns most specific / deepest)
        """
        node = self._g.get_node(symbol)
        if node:
            return node

        exact = self._g.find_by_name(symbol)
        if exact:
            # Prefer method > function > class > file
            priority = {
                NodeType.METHOD: 0,
                NodeType.FUNCTION: 1,
                NodeType.CLASS: 2,
                NodeType.FILE: 3,
            }
            return sorted(exact, key=lambda n: priority.get(n.type, 9))[0]

        partial = self._g.find_by_name_partial(symbol)
        if partial:
            return partial[0]

        return None

"""
ASCII visualization of the knowledge graph.

All output is plain text / ASCII art suitable for terminal display.
"""
from __future__ import annotations

from . import GraphEngine
from .schema import EdgeType, NodeType
from .traversal import GraphTraversal, ImpactReport


class GraphVisualizer:
    """Renders graph structures as ASCII art."""

    def __init__(self, engine: GraphEngine) -> None:
        self._g = engine
        self._traversal = GraphTraversal(engine)

    # ------------------------------------------------------------------
    # Architecture map — file-level
    # ------------------------------------------------------------------

    def architecture_map(self, max_files: int = 40) -> str:
        """
        High-level map showing files and their dependency relationships.

        Example output:

            src/core/agent.py
              → src/tools/__init__.py  [IMPORTS]
              → src/core/session.py    [IMPORTS]

            src/tools/__init__.py
              ← src/core/agent.py      [IMPORTS]  (2 callers)
        """
        files = sorted(
            self._g.find_by_type(NodeType.FILE),
            key=lambda n: n.file,
        )[:max_files]

        if not files:
            return "No modules in graph.  Run 'zwis learn' first."

        lines: list[str] = ["# Architecture Map\n"]

        for fnode in files:
            out_edges = self._g.outgoing_edges(fnode.id)
            in_edges = self._g.incoming_edges(fnode.id)

            # Only IMPORTS / DEPENDS_ON at file level
            imports = [
                e for e in out_edges
                if e.relationship in (EdgeType.IMPORTS, EdgeType.DEPENDS_ON)
            ]
            callers = [
                e for e in in_edges
                if e.relationship in (EdgeType.IMPORTS, EdgeType.DEPENDS_ON)
            ]

            if not imports and not callers:
                continue  # isolated file — skip in map

            lines.append(f"{fnode.file}")

            for edge in imports[:6]:
                target = self._g.get_node(edge.to_id)
                if target:
                    label = edge.relationship.value
                    lines.append(f"  ─→  {target.file or target.name}  [{label}]")

            if len(imports) > 6:
                lines.append(f"  ─→  … {len(imports) - 6} more")

            if callers:
                caller_names = []
                for edge in callers[:3]:
                    src = self._g.get_node(edge.from_id)
                    if src:
                        caller_names.append(src.file or src.name)
                if caller_names:
                    lines.append(f"  ←   used by: {', '.join(caller_names)}")
                if len(callers) > 3:
                    lines.append(f"  ←   … {len(callers) - 3} more")

            lines.append("")

        stats = self._g.stats()
        lines.append(
            f"  Nodes: {stats['total_nodes']}  "
            f"Edges: {stats['total_edges']}  "
            f"References: {stats['total_references']}"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Dependency tree — single node
    # ------------------------------------------------------------------

    def dependency_tree(self, node_id: str, max_depth: int = 3) -> str:
        """
        ASCII tree showing what a node depends on (outgoing).

        Example:
            BashTool.execute()
            ├─ asyncio.create_subprocess_shell()
            └─ asyncio.wait_for()
        """
        root = self._g.get_node(node_id)
        if root is None:
            return f"Node '{node_id}' not found."

        lines: list[str] = [f"{root.name}"]
        visited: set[str] = {node_id}
        self._tree_recurse(node_id, max_depth, 0, visited, lines, "")
        return "\n".join(lines)

    def _tree_recurse(
        self,
        node_id: str,
        max_depth: int,
        depth: int,
        visited: set[str],
        lines: list[str],
        prefix: str,
    ) -> None:
        if depth >= max_depth:
            return

        children = [
            (e, self._g.get_node(e.to_id))
            for e in self._g.outgoing_edges(node_id)
            if self._g.get_node(e.to_id) is not None
        ]

        for i, (edge, child) in enumerate(children):
            if child is None:
                continue
            is_last = i == len(children) - 1
            connector = "└─ " if is_last else "├─ "
            marker = " ↺" if child.id in visited else ""
            label = f"  [{edge.relationship.value}]" if depth == 0 else ""
            loc = f"  :{child.start_line}" if child.start_line else ""
            lines.append(f"{prefix}{connector}{child.name}{loc}{label}{marker}")

            if child.id not in visited:
                visited.add(child.id)
                extension = "   " if is_last else "│  "
                self._tree_recurse(
                    child.id, max_depth, depth + 1, visited, lines, prefix + extension
                )

    # ------------------------------------------------------------------
    # Impact tree
    # ------------------------------------------------------------------

    def impact_tree(self, report: ImpactReport) -> str:
        """
        Render an impact report as an ASCII tree.

        Example:
            IMPACT: User model  [risk: high]
            ├─ AuthService  (src/services/auth.py)
            │  └─ JWTGenerator  (src/utils/jwt.py)
            └─ SignupController  (src/controllers/signup.py)
        """
        if report.root_node is None:
            return (
                f"Symbol '{report.symbol}' not found in graph.\n"
                + self._format_refs(report)
            )

        lines: list[str] = [
            f"IMPACT: {report.root_node.name}  [risk: {report.risk_level.upper()}]"
        ]

        if report.summary_line():
            lines.append(f"  {report.summary_line()}")

        if report.direct_dependents:
            lines.append("\nDirect dependents:")
            for i, node in enumerate(report.direct_dependents):
                is_last = i == len(report.direct_dependents) - 1 and not report.transitive_dependents
                conn = "└─" if is_last else "├─"
                loc = f"  ({node.file})" if node.file else ""
                lines.append(f"  {conn} {node.name}{loc}")

        if report.transitive_dependents:
            lines.append("\nTransitive dependents:")
            for node in report.transitive_dependents[:10]:
                loc = f"  ({node.file})" if node.file else ""
                lines.append(f"     {node.name}{loc}")
            if len(report.transitive_dependents) > 10:
                lines.append(f"     … {len(report.transitive_dependents) - 10} more")

        if report.affected_files:
            lines.append("\nAffected files:")
            for f in report.affected_files:
                lines.append(f"  • {f}")

        lines.append(self._format_refs(report))
        return "\n".join(lines)

    def _format_refs(self, report: ImpactReport) -> str:
        refs = report.line_references
        if not refs:
            return ""
        out = ["\nLine-level references:"]
        for ref in refs[:8]:
            out.append(
                f"  {ref.source_file}:{ref.source_line}  "
                f"{ref.relationship.value}  {ref.target_symbol}"
            )
        if len(refs) > 8:
            out.append(f"  … {len(refs) - 8} more")
        return "\n".join(out)

    # ------------------------------------------------------------------
    # Quick stats
    # ------------------------------------------------------------------

    def stats_summary(self) -> str:
        s = self._g.stats()
        rows: list[str] = ["# Knowledge Graph Stats\n"]
        rows.append(f"  Total nodes      : {s.get('total_nodes', 0)}")
        rows.append(f"  Total edges      : {s.get('total_edges', 0)}")
        rows.append(f"  Total references : {s.get('total_references', 0)}")
        rows.append("")
        rows.append("  Node breakdown:")
        for key, val in sorted(s.items()):
            if key.startswith("nodes."):
                rows.append(f"    {key[6:]:12s} : {val}")
        rows.append("")
        rows.append("  Edge breakdown:")
        for key, val in sorted(s.items()):
            if key.startswith("edges."):
                rows.append(f"    {key[6:]:14s} : {val}")
        return "\n".join(rows)

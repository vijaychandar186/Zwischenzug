"""
GraphEngine — in-memory knowledge graph with BFS traversal.

Storage is pure Python (dicts + lists); persistence is handled separately
by src/graph/storage.py.  No external graph-library dependency.

Node IDs follow the convention:
  file node:       "src/tools/bash.py"
  class node:      "src/tools/bash.py::BashTool"
  function node:   "src/tools/bash.py::execute"
  method node:     "src/tools/bash.py::BashTool::execute"
  external node:   "ext::subprocess"
"""
from __future__ import annotations

from collections import deque
from typing import Iterator

from .schema import EdgeType, GraphEdge, GraphNode, NodeType, Reference

# Edge types that represent semantic dependencies (not structural containment).
# Used by bfs_reverse_semantic() to compute meaningful impact analysis.
_DEPENDENCY_EDGES = frozenset({
    EdgeType.IMPORTS,
    EdgeType.CALLS,
    EdgeType.EXTENDS,
    EdgeType.IMPLEMENTS,
    EdgeType.DEPENDS_ON,
    EdgeType.USES,
})


class GraphEngine:
    """
    Central knowledge graph.

    Maintains three parallel data stores:
      - nodes:      id → GraphNode
      - edges:      list of GraphEdge  (also indexed by from/to for fast lookup)
      - references: list of Reference  (line-level, indexed by target_symbol)
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._references: list[Reference] = []

        # Adjacency indexes — rebuilt lazily via _ensure_index()
        self._outgoing: dict[str, list[GraphEdge]] = {}   # from_id → edges
        self._incoming: dict[str, list[GraphEdge]] = {}   # to_id   → edges
        self._ref_index: dict[str, list[Reference]] = {}  # target_symbol → refs
        self._dirty = True

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        self._dirty = True

    def add_edge(self, edge: GraphEdge) -> None:
        # Deduplicate: same (from, to, relationship) is idempotent
        key = (edge.from_id, edge.to_id, edge.relationship)
        for existing in self._edges:
            if (existing.from_id, existing.to_id, existing.relationship) == key:
                return
        self._edges.append(edge)
        self._dirty = True

    def add_reference(self, ref: Reference) -> None:
        self._references.append(ref)
        self._dirty = True

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._references.clear()
        self._outgoing.clear()
        self._incoming.clear()
        self._ref_index.clear()
        self._dirty = False

    def remove_file(self, file_path: str) -> None:
        """Remove all nodes, edges, and references belonging to a file."""
        ids_to_remove = {n.id for n in self._nodes.values() if n.file == file_path}
        # Also remove the file node itself
        ids_to_remove.add(file_path)

        for nid in ids_to_remove:
            self._nodes.pop(nid, None)

        self._edges = [
            e for e in self._edges
            if e.from_id not in ids_to_remove and e.to_id not in ids_to_remove
        ]
        self._references = [
            r for r in self._references
            if r.source_file != file_path
        ]
        self._dirty = True

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _ensure_index(self) -> None:
        if not self._dirty:
            return
        self._outgoing = {}
        self._incoming = {}
        self._ref_index = {}

        for edge in self._edges:
            self._outgoing.setdefault(edge.from_id, []).append(edge)
            self._incoming.setdefault(edge.to_id, []).append(edge)

        for ref in self._references:
            self._ref_index.setdefault(ref.target_symbol, []).append(ref)

        self._dirty = False

    # ------------------------------------------------------------------
    # Lookup — nodes
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def find_by_name(self, name: str, node_type: NodeType | None = None) -> list[GraphNode]:
        """Case-insensitive name search, optionally filtered by type."""
        name_lower = name.lower()
        results: list[GraphNode] = []
        for node in self._nodes.values():
            if node.name.lower() == name_lower or node.name.lower().endswith(f".{name_lower}"):
                if node_type is None or node.type == node_type:
                    results.append(node)
        return results

    def find_by_name_partial(self, fragment: str, node_type: NodeType | None = None) -> list[GraphNode]:
        """Substring search on node name or id."""
        frag = fragment.lower()
        results: list[GraphNode] = []
        for node in self._nodes.values():
            if frag in node.name.lower() or frag in node.id.lower():
                if node_type is None or node.type == node_type:
                    results.append(node)
        return results

    def find_by_file(self, file_path: str) -> list[GraphNode]:
        """Return all nodes that belong to a given file."""
        return [n for n in self._nodes.values() if n.file == file_path]

    def find_by_type(self, node_type: NodeType) -> list[GraphNode]:
        return [n for n in self._nodes.values() if n.type == node_type]

    def all_nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    def all_edges(self) -> list[GraphEdge]:
        return list(self._edges)

    # ------------------------------------------------------------------
    # Lookup — edges
    # ------------------------------------------------------------------

    def outgoing_edges(self, node_id: str) -> list[GraphEdge]:
        self._ensure_index()
        return self._outgoing.get(node_id, [])

    def incoming_edges(self, node_id: str) -> list[GraphEdge]:
        self._ensure_index()
        return self._incoming.get(node_id, [])

    def neighbors_out(self, node_id: str) -> list[tuple[GraphNode, EdgeType]]:
        """Return (node, relationship) tuples for nodes this node points to."""
        result = []
        for edge in self.outgoing_edges(node_id):
            target = self._nodes.get(edge.to_id)
            if target:
                result.append((target, edge.relationship))
        return result

    def neighbors_in(self, node_id: str) -> list[tuple[GraphNode, EdgeType]]:
        """Return (node, relationship) tuples for nodes pointing to this node."""
        result = []
        for edge in self.incoming_edges(node_id):
            source = self._nodes.get(edge.from_id)
            if source:
                result.append((source, edge.relationship))
        return result

    # ------------------------------------------------------------------
    # Traversal — BFS
    # ------------------------------------------------------------------

    def bfs_forward(
        self, start_id: str, max_depth: int = 5,
        edge_types: frozenset[EdgeType] | None = None,
    ) -> list[GraphNode]:
        """BFS following outgoing edges — what this node depends on."""
        return self._bfs(start_id, direction="out", max_depth=max_depth, edge_types=edge_types)

    def bfs_reverse(
        self, start_id: str, max_depth: int = 5,
        edge_types: frozenset[EdgeType] | None = None,
    ) -> list[GraphNode]:
        """BFS following incoming edges — what depends on this node (impact)."""
        return self._bfs(start_id, direction="in", max_depth=max_depth, edge_types=edge_types)

    def bfs_reverse_semantic(self, start_id: str, max_depth: int = 5) -> list[GraphNode]:
        """Impact-oriented reverse BFS — follows only dependency edges, excludes CONTAINS/DEFINES/RETURNS."""
        return self._bfs(start_id, direction="in", max_depth=max_depth, edge_types=_DEPENDENCY_EDGES)

    def _bfs(
        self, start_id: str, direction: str, max_depth: int,
        edge_types: frozenset[EdgeType] | None = None,
    ) -> list[GraphNode]:
        self._ensure_index()
        visited: set[str] = {start_id}
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])
        result: list[GraphNode] = []

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            edges = (
                self._outgoing.get(current_id, [])
                if direction == "out"
                else self._incoming.get(current_id, [])
            )

            for edge in edges:
                if edge_types is not None and edge.relationship not in edge_types:
                    continue
                neighbour_id = edge.to_id if direction == "out" else edge.from_id
                if neighbour_id in visited:
                    continue
                visited.add(neighbour_id)
                node = self._nodes.get(neighbour_id)
                if node:
                    result.append(node)
                    queue.append((neighbour_id, depth + 1))

        return result

    def path_between(self, from_id: str, to_id: str, max_depth: int = 8) -> list[GraphNode]:
        """BFS shortest path from from_id to to_id (following outgoing edges)."""
        self._ensure_index()
        if from_id == to_id:
            node = self._nodes.get(from_id)
            return [node] if node else []

        visited: set[str] = {from_id}
        # queue stores (current_id, path_so_far)
        queue: deque[tuple[str, list[str]]] = deque([(from_id, [from_id])])

        while queue:
            current_id, path = queue.popleft()
            if len(path) > max_depth:
                continue
            for edge in self._outgoing.get(current_id, []):
                nid = edge.to_id
                if nid in visited:
                    continue
                new_path = path + [nid]
                if nid == to_id:
                    return [self._nodes[p] for p in new_path if p in self._nodes]
                visited.add(nid)
                queue.append((nid, new_path))

        return []

    # ------------------------------------------------------------------
    # References
    # ------------------------------------------------------------------

    def find_references(self, symbol: str) -> list[Reference]:
        """Return all references that target the given symbol (exact or suffix match)."""
        self._ensure_index()
        exact = self._ref_index.get(symbol, [])
        if exact:
            return exact
        # Try suffix match: e.g. "execute" matches "BashTool.execute"
        sym_lower = symbol.lower()
        results: list[Reference] = []
        for target, refs in self._ref_index.items():
            if target.lower().endswith(sym_lower) or target.lower() == sym_lower:
                results.extend(refs)
        return results

    def all_references(self) -> list[Reference]:
        return list(self._references)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        type_counts: dict[str, int] = {}
        for node in self._nodes.values():
            type_counts[node.type.value] = type_counts.get(node.type.value, 0) + 1

        edge_counts: dict[str, int] = {}
        for edge in self._edges:
            edge_counts[edge.relationship.value] = edge_counts.get(edge.relationship.value, 0) + 1

        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "total_references": len(self._references),
            **{f"nodes.{k}": v for k, v in type_counts.items()},
            **{f"edges.{k}": v for k, v in edge_counts.items()},
        }

    def top_level_files(self) -> list[GraphNode]:
        """Return all FILE-type nodes, sorted by file path."""
        files = self.find_by_type(NodeType.FILE)
        return sorted(files, key=lambda n: n.file)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges],
            "references": [r.to_dict() for r in self._references],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GraphEngine":
        engine = cls()
        for nd in data.get("nodes", []):
            try:
                engine.add_node(GraphNode.from_dict(nd))
            except Exception:
                pass
        for ed in data.get("edges", []):
            try:
                engine.add_edge(GraphEdge.from_dict(ed))
            except Exception:
                pass
        for rd in data.get("references", []):
            try:
                engine.add_reference(Reference.from_dict(rd))
            except Exception:
                pass
        return engine

    # ------------------------------------------------------------------
    # Iteration helpers
    # ------------------------------------------------------------------

    def iter_nodes(self) -> Iterator[GraphNode]:
        return iter(self._nodes.values())

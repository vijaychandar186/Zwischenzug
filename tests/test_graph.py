"""
Tests for src/graph — GraphEngine, BFS, serialization, and impact analysis.
"""
from __future__ import annotations

import pytest

from src.graph import GraphEngine, _DEPENDENCY_EDGES
from src.graph.schema import EdgeType, GraphEdge, GraphNode, NodeType, Reference
from src.graph.traversal import GraphTraversal


# ── helpers ──────────────────────────────────────────────────────────────────

def _file_node(fid: str, name: str | None = None) -> GraphNode:
    return GraphNode(id=fid, type=NodeType.FILE, name=name or fid.split("/")[-1], file=fid)


def _func_node(fid: str, fname: str, file: str, line: int = 1) -> GraphNode:
    return GraphNode(id=fid, type=NodeType.FUNCTION, name=fname, file=file, start_line=line)


def _class_node(cid: str, cname: str, file: str, line: int = 1) -> GraphNode:
    return GraphNode(id=cid, type=NodeType.CLASS, name=cname, file=file, start_line=line)


def _method_node(mid: str, mname: str, file: str, line: int = 1) -> GraphNode:
    return GraphNode(id=mid, type=NodeType.METHOD, name=mname, file=file, start_line=line)


def _edge(from_id: str, to_id: str, rel: EdgeType) -> GraphEdge:
    return GraphEdge(from_id=from_id, to_id=to_id, relationship=rel)


# ── GraphEngine basics ───────────────────────────────────────────────────────

class TestGraphEngineBasics:
    def test_add_node_and_get(self):
        g = GraphEngine()
        node = _file_node("a.py")
        g.add_node(node)
        assert g.get_node("a.py") is node
        assert g.get_node("nonexistent") is None

    def test_edge_dedup(self):
        g = GraphEngine()
        g.add_node(_file_node("a.py"))
        g.add_node(_file_node("b.py"))
        edge = _edge("a.py", "b.py", EdgeType.IMPORTS)
        g.add_edge(edge)
        g.add_edge(_edge("a.py", "b.py", EdgeType.IMPORTS))  # duplicate
        assert len(g.all_edges()) == 1

    def test_edge_different_relationship_not_dedup(self):
        g = GraphEngine()
        g.add_node(_file_node("a.py"))
        g.add_node(_file_node("b.py"))
        g.add_edge(_edge("a.py", "b.py", EdgeType.IMPORTS))
        g.add_edge(_edge("a.py", "b.py", EdgeType.DEPENDS_ON))
        assert len(g.all_edges()) == 2

    def test_remove_file(self):
        g = GraphEngine()
        g.add_node(_file_node("a.py"))
        g.add_node(_func_node("a.py::foo", "foo", "a.py"))
        g.add_node(_file_node("b.py"))
        g.add_edge(_edge("a.py", "a.py::foo", EdgeType.CONTAINS))
        g.add_edge(_edge("a.py::foo", "b.py", EdgeType.CALLS))
        g.add_reference(Reference(
            source_file="a.py", source_line=10,
            source_symbol="foo", target_symbol="b.py",
            relationship=EdgeType.CALLS,
        ))

        g.remove_file("a.py")

        assert g.get_node("a.py") is None
        assert g.get_node("a.py::foo") is None
        assert g.get_node("b.py") is not None
        assert len(g.all_edges()) == 0
        assert len(g.all_references()) == 0

    def test_find_by_name(self):
        g = GraphEngine()
        g.add_node(_func_node("a.py::foo", "foo", "a.py"))
        g.add_node(_func_node("b.py::foo", "foo", "b.py"))
        g.add_node(_func_node("c.py::bar", "bar", "c.py"))
        results = g.find_by_name("foo")
        assert len(results) == 2
        assert all(n.name == "foo" for n in results)

    def test_find_by_name_partial(self):
        g = GraphEngine()
        g.add_node(_func_node("a.py::run_agent", "run_agent", "a.py"))
        g.add_node(_func_node("b.py::run_tests", "run_tests", "b.py"))
        results = g.find_by_name_partial("run_")
        assert len(results) == 2


# ── BFS ──────────────────────────────────────────────────────────────────────

class TestBFS:
    def _build_chain(self) -> GraphEngine:
        """Build A→B→C via CALLS edges."""
        g = GraphEngine()
        g.add_node(_func_node("a", "a", "f.py"))
        g.add_node(_func_node("b", "b", "f.py"))
        g.add_node(_func_node("c", "c", "f.py"))
        g.add_edge(_edge("a", "b", EdgeType.CALLS))
        g.add_edge(_edge("b", "c", EdgeType.CALLS))
        return g

    def test_bfs_forward(self):
        g = self._build_chain()
        result = g.bfs_forward("a")
        ids = {n.id for n in result}
        assert ids == {"b", "c"}

    def test_bfs_reverse(self):
        g = self._build_chain()
        result = g.bfs_reverse("c")
        ids = {n.id for n in result}
        assert ids == {"a", "b"}

    def test_bfs_max_depth(self):
        g = self._build_chain()
        result = g.bfs_forward("a", max_depth=1)
        ids = {n.id for n in result}
        assert ids == {"b"}

    def test_bfs_reverse_semantic_excludes_contains(self):
        """CONTAINS edges should NOT be followed by semantic BFS."""
        g = GraphEngine()
        file_node = _file_node("agent.py")
        func_node = _func_node("agent.py::run_agent", "run_agent", "agent.py")
        caller_node = _func_node("main.py::main", "main", "main.py")

        g.add_node(file_node)
        g.add_node(func_node)
        g.add_node(caller_node)

        # file CONTAINS function (structural)
        g.add_edge(_edge("agent.py", "agent.py::run_agent", EdgeType.CONTAINS))
        # main CALLS run_agent (semantic dependency)
        g.add_edge(_edge("main.py::main", "agent.py::run_agent", EdgeType.CALLS))

        # Semantic reverse BFS from run_agent should find caller, NOT the file
        result = g.bfs_reverse_semantic("agent.py::run_agent")
        ids = {n.id for n in result}
        assert "main.py::main" in ids
        assert "agent.py" not in ids, "CONTAINS edge should not be traversed"

    def test_bfs_edge_type_filter(self):
        """Explicit edge_types filter restricts traversal."""
        g = GraphEngine()
        g.add_node(_func_node("a", "a", "f.py"))
        g.add_node(_func_node("b", "b", "f.py"))
        g.add_node(_func_node("c", "c", "f.py"))
        g.add_edge(_edge("a", "b", EdgeType.CALLS))
        g.add_edge(_edge("a", "c", EdgeType.CONTAINS))

        # Only follow CALLS
        result = g.bfs_forward("a", edge_types=frozenset({EdgeType.CALLS}))
        ids = {n.id for n in result}
        assert ids == {"b"}

    def test_path_between(self):
        g = self._build_chain()
        path = g.path_between("a", "c")
        ids = [n.id for n in path]
        assert ids == ["a", "b", "c"]

    def test_path_between_no_path(self):
        g = self._build_chain()
        path = g.path_between("c", "a")  # no reverse path via outgoing
        assert path == []


# ── Serialization ────────────────────────────────────────────────────────────

class TestSerialization:
    def test_roundtrip(self):
        g = GraphEngine()
        g.add_node(_file_node("a.py"))
        g.add_node(_func_node("a.py::foo", "foo", "a.py", line=10))
        g.add_edge(_edge("a.py", "a.py::foo", EdgeType.CONTAINS))
        g.add_reference(Reference(
            source_file="a.py", source_line=10,
            source_symbol="foo", target_symbol="bar",
            relationship=EdgeType.CALLS,
        ))

        data = g.to_dict()
        g2 = GraphEngine.from_dict(data)

        assert g2.get_node("a.py") is not None
        assert g2.get_node("a.py::foo") is not None
        assert g2.get_node("a.py::foo").start_line == 10
        assert len(g2.all_edges()) == 1
        assert len(g2.all_references()) == 1
        assert g2.all_references()[0].target_symbol == "bar"


# ── Impact analysis ──────────────────────────────────────────────────────────

class TestImpactAnalysis:
    def test_excludes_container_file(self):
        """Impact of a function should NOT include its own file via CONTAINS."""
        g = GraphEngine()
        g.add_node(_file_node("agent.py"))
        g.add_node(_func_node("agent.py::run_agent", "run_agent", "agent.py"))
        g.add_node(_func_node("main.py::main", "main", "main.py"))
        g.add_node(_file_node("main.py"))

        g.add_edge(_edge("agent.py", "agent.py::run_agent", EdgeType.CONTAINS))
        g.add_edge(_edge("main.py::main", "agent.py::run_agent", EdgeType.CALLS))

        traversal = GraphTraversal(g)
        report = traversal.impact_analysis("run_agent")

        dependent_ids = {n.id for n in report.direct_dependents + report.transitive_dependents}
        assert "main.py::main" in dependent_ids
        assert "agent.py" not in dependent_ids, (
            "Container file should not appear as dependent"
        )

    def test_risk_levels(self):
        g = GraphEngine()
        target = _func_node("t", "target", "t.py")
        g.add_node(target)

        # 0 dependents → low
        traversal = GraphTraversal(g)
        assert traversal.impact_analysis("target").risk_level == "low"

        # 2 dependents → medium
        for i in range(2):
            n = _func_node(f"d{i}", f"dep{i}", f"d{i}.py")
            g.add_node(n)
            g.add_edge(_edge(n.id, "t", EdgeType.CALLS))
        assert traversal.impact_analysis("target").risk_level == "medium"

        # add 3 more (total 5) → high
        for i in range(2, 5):
            n = _func_node(f"d{i}", f"dep{i}", f"d{i}.py")
            g.add_node(n)
            g.add_edge(_edge(n.id, "t", EdgeType.CALLS))
        assert traversal.impact_analysis("target").risk_level == "high"

    def test_impact_affected_files(self):
        g = GraphEngine()
        g.add_node(_func_node("a.py::foo", "foo", "a.py"))
        g.add_node(_func_node("b.py::bar", "bar", "b.py"))
        g.add_node(_func_node("c.py::baz", "baz", "c.py"))
        g.add_edge(_edge("b.py::bar", "a.py::foo", EdgeType.CALLS))
        g.add_edge(_edge("c.py::baz", "b.py::bar", EdgeType.CALLS))

        traversal = GraphTraversal(g)
        report = traversal.impact_analysis("foo")
        assert set(report.affected_files) == {"b.py", "c.py"}


# ── References ───────────────────────────────────────────────────────────────

class TestReferences:
    def test_find_references_exact_and_suffix(self):
        g = GraphEngine()
        # Exact match
        g.add_reference(Reference(
            source_file="a.py", source_line=5,
            source_symbol="caller", target_symbol="BashTool.execute",
            relationship=EdgeType.CALLS,
        ))
        # Different target
        g.add_reference(Reference(
            source_file="b.py", source_line=10,
            source_symbol="other", target_symbol="other_func",
            relationship=EdgeType.CALLS,
        ))

        # Exact match works
        refs = g.find_references("BashTool.execute")
        assert len(refs) == 1
        assert refs[0].source_file == "a.py"

        # Suffix match: "execute" should match "BashTool.execute"
        refs = g.find_references("execute")
        assert len(refs) == 1
        assert refs[0].target_symbol == "BashTool.execute"

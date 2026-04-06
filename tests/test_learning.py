"""
Tests for src/learning — LearningEngine, two-pass resolution, AST parser.

Uses synthetic source files written to tmp_path to avoid depending
on the real repository layout.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.graph import GraphEngine
from src.graph.schema import EdgeType, NodeType
from src.learning import LearningEngine
from src.learning.ast_parser import PythonASTParser
from src.learning.reference import ReferenceTracker


# ── helpers ──────────────────────────────────────────────────────────────────

def _write(tmp: Path, rel: str, source: str) -> Path:
    """Write a source file under tmp and return its path."""
    p = tmp / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source)
    return p


def _build_graph(tmp: Path) -> GraphEngine:
    """Run a full learn() pass on the tmp directory and return the graph."""
    graph = GraphEngine()
    engine = LearningEngine(str(tmp), graph)
    asyncio.run(engine.learn())
    return graph


# ── AST parser ───────────────────────────────────────────────────────────────

class TestASTParser:
    def test_classes_functions_imports(self):
        source = '''
"""Module doc."""
import os
from pathlib import Path

class Foo:
    """A class."""
    def bar(self):
        pass

def baz():
    os.getcwd()
'''
        parser = PythonASTParser()
        result = parser.parse_source(source, "test.py")

        assert result.docstring == "Module doc."
        assert len(result.imports) == 2
        assert result.imports[0].module == "os"
        assert result.imports[1].module == "pathlib"
        assert len(result.classes) == 1
        assert result.classes[0].name == "Foo"
        assert "bar" in result.classes[0].methods
        assert len(result.functions) == 1
        assert result.functions[0].name == "baz"

    def test_parse_all_methods_includes_class_methods(self):
        source = '''
class A:
    def method_a(self):
        pass

def top_level():
    pass
'''
        parser = PythonASTParser()
        fns = parser.parse_all_methods(source, "test.py")
        names = {f.name for f in fns}
        assert names == {"method_a", "top_level"}
        method = next(f for f in fns if f.name == "method_a")
        assert method.class_name == "A"
        assert method.is_method is True


# ── Two-pass resolution ─────────────────────────────────────────────────────

class TestTwoPassResolution:
    def test_cross_file_call_resolves_to_internal_node(self, tmp_path):
        """File A calls a function defined in file B — the edge should point to B's node, not ext::."""
        _write(tmp_path, "a.py", '''
def caller():
    helper()
''')
        _write(tmp_path, "b.py", '''
def helper():
    pass
''')
        graph = _build_graph(tmp_path)

        # The function node for helper should exist
        helper_node = graph.get_node("b.py::helper")
        assert helper_node is not None, "b.py::helper node should exist"

        # The edge from caller to helper should point to b.py::helper, not ext::helper
        edges = graph.outgoing_edges("a.py::caller")
        call_edges = [e for e in edges if e.relationship == EdgeType.CALLS]
        assert len(call_edges) >= 1

        target_ids = {e.to_id for e in call_edges}
        assert "b.py::helper" in target_ids, (
            f"Expected edge to b.py::helper, got targets: {target_ids}"
        )
        assert not any(t.startswith("ext::") and "helper" in t for t in target_ids), (
            "helper should NOT be classified as external"
        )

    def test_self_method_call_resolves_to_same_class(self, tmp_path):
        """self.foo() inside class A should resolve to A's method, not ext::."""
        _write(tmp_path, "mod.py", '''
class MyClass:
    def foo(self):
        pass

    def bar(self):
        self.foo()
''')
        graph = _build_graph(tmp_path)

        bar_edges = graph.outgoing_edges("mod.py::MyClass::bar")
        call_edges = [e for e in bar_edges if e.relationship == EdgeType.CALLS]
        target_ids = {e.to_id for e in call_edges}

        # Should resolve to the method node, not ext::self.foo
        assert "mod.py::MyClass::foo" in target_ids, (
            f"Expected edge to mod.py::MyClass::foo, got targets: {target_ids}"
        )

    def test_external_imports_remain_external(self, tmp_path):
        """import os should stay ext::os, not resolve to an internal node."""
        _write(tmp_path, "x.py", '''
import os

def f():
    os.getcwd()
''')
        graph = _build_graph(tmp_path)

        file_edges = graph.outgoing_edges("x.py")
        import_edges = [e for e in file_edges if e.relationship == EdgeType.IMPORTS]
        targets = {e.to_id for e in import_edges}

        assert "ext::os" in targets, f"os should be external, got: {targets}"

    def test_reference_tracker_stores_resolved_ids(self, tmp_path):
        """After learn(), reference target_symbol should contain node IDs, not raw names."""
        _write(tmp_path, "lib.py", '''
def utility():
    pass
''')
        _write(tmp_path, "app.py", '''
def main():
    utility()
''')
        graph = _build_graph(tmp_path)

        refs = graph.find_references("lib.py::utility")
        # Should find at least one reference from app.py
        app_refs = [r for r in refs if r.source_file == "app.py"]
        assert len(app_refs) >= 1, (
            f"Expected a reference from app.py to lib.py::utility. "
            f"All refs: {[(r.source_file, r.target_symbol) for r in graph.all_references()]}"
        )


# ── Incremental update ──────────────────────────────────────────────────────

class TestIncrementalUpdate:
    def test_update_file_refreshes_nodes(self, tmp_path):
        """update_file should remove old nodes and add new ones."""
        _write(tmp_path, "m.py", '''
def old_func():
    pass
''')
        graph = GraphEngine()
        engine = LearningEngine(str(tmp_path), graph)
        asyncio.run(engine.learn())

        assert graph.get_node("m.py::old_func") is not None

        # Rewrite the file with a different function
        _write(tmp_path, "m.py", '''
def new_func():
    pass
''')
        engine.update_file("m.py")

        assert graph.get_node("m.py::old_func") is None, "old_func should be removed"
        assert graph.get_node("m.py::new_func") is not None, "new_func should be added"

    def test_incremental_resolves_against_existing_graph(self, tmp_path):
        """After update_file, edges from the new file should resolve against existing nodes."""
        _write(tmp_path, "base.py", '''
def shared():
    pass
''')
        _write(tmp_path, "user.py", '''
def use_shared():
    pass
''')
        graph = GraphEngine()
        engine = LearningEngine(str(tmp_path), graph)
        asyncio.run(engine.learn())

        # Now update user.py to call shared()
        _write(tmp_path, "user.py", '''
def use_shared():
    shared()
''')
        engine.update_file("user.py")

        edges = graph.outgoing_edges("user.py::use_shared")
        call_edges = [e for e in edges if e.relationship == EdgeType.CALLS]
        target_ids = {e.to_id for e in call_edges}
        assert "base.py::shared" in target_ids, (
            f"Incremental update should resolve shared() to base.py::shared, got: {target_ids}"
        )

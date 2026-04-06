"""
Line-level reference tracker.

Builds a searchable index of *where* each symbol is used — analogous to
an IDE's "Find All References" feature.  Stored as part of the graph so
it persists between sessions.
"""
from __future__ import annotations

from ..graph import GraphEngine
from ..graph.schema import EdgeType, Reference


class ReferenceTracker:
    """
    Wraps a GraphEngine to provide reference-oriented queries.

    References are stored directly inside the GraphEngine; this class
    provides convenience query methods on top of that storage.
    """

    def __init__(self, engine: GraphEngine) -> None:
        self._g = engine

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def record(
        self,
        source_file: str,
        source_line: int,
        source_symbol: str,
        target_symbol: str,
        relationship: EdgeType,
    ) -> None:
        ref = Reference(
            source_file=source_file,
            source_line=source_line,
            source_symbol=source_symbol,
            target_symbol=target_symbol,
            relationship=relationship,
        )
        self._g.add_reference(ref)

    def record_call(
        self,
        source_file: str,
        source_line: int,
        caller_qualname: str,
        callee_name: str,
    ) -> None:
        self.record(
            source_file=source_file,
            source_line=source_line,
            source_symbol=caller_qualname,
            target_symbol=callee_name,
            relationship=EdgeType.CALLS,
        )

    def record_import(
        self,
        source_file: str,
        source_line: int,
        imported_module: str,
    ) -> None:
        self.record(
            source_file=source_file,
            source_line=source_line,
            source_symbol=source_file,
            target_symbol=imported_module,
            relationship=EdgeType.IMPORTS,
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def find(self, symbol: str) -> list[Reference]:
        """Return all references whose target matches `symbol`."""
        return self._g.find_references(symbol)

    def find_calls(self, symbol: str) -> list[Reference]:
        return [r for r in self.find(symbol) if r.relationship == EdgeType.CALLS]

    def find_imports(self, module: str) -> list[Reference]:
        return [r for r in self.find(module) if r.relationship == EdgeType.IMPORTS]

    def refs_in_file(self, file_path: str) -> list[Reference]:
        """Return all references originating from a given file."""
        return [r for r in self._g.all_references() if r.source_file == file_path]

    def all(self) -> list[Reference]:
        return self._g.all_references()

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_refs(self, symbol: str) -> str:
        """Human-readable reference list for a symbol."""
        refs = self.find(symbol)
        if not refs:
            return f"No references found for '{symbol}'."

        lines: list[str] = [f"References to '{symbol}' ({len(refs)} total):\n"]
        for ref in sorted(refs, key=lambda r: (r.source_file, r.source_line)):
            lines.append(
                f"  {ref.source_file}:{ref.source_line}  "
                f"[{ref.relationship.value}]  in {ref.source_symbol}"
            )
        return "\n".join(lines)

"""
Graph schema — pure data definitions, no I/O.

Nodes represent code entities; edges represent relationships between them;
references track exact source locations where a symbol is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    FILE     = "file"
    CLASS    = "class"
    FUNCTION = "function"
    METHOD   = "method"
    VARIABLE = "variable"
    MODEL    = "model"     # ORM / DB model
    ROUTE    = "route"     # API route / endpoint
    SERVICE  = "service"
    TEST     = "test"
    EXTERNAL = "external"  # third-party package / symbol


# ---------------------------------------------------------------------------
# Edge types
# ---------------------------------------------------------------------------

class EdgeType(str, Enum):
    IMPORTS    = "IMPORTS"
    CALLS      = "CALLS"
    EXTENDS    = "EXTENDS"
    IMPLEMENTS = "IMPLEMENTS"
    READS_DB   = "READS_DB"
    WRITES_DB  = "WRITES_DB"
    DEPENDS_ON = "DEPENDS_ON"
    RETURNS    = "RETURNS"
    USES       = "USES"
    DEFINES    = "DEFINES"
    CONTAINS   = "CONTAINS"


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    """A single entity in the knowledge graph."""

    id: str            # Unique: "src/tools/bash.py::BashTool::execute"
    type: NodeType
    name: str
    file: str = ""
    start_line: int = 0
    end_line: int = 0
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "file": self.file,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "summary": self.summary,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GraphNode":
        return cls(
            id=d["id"],
            type=NodeType(d["type"]),
            name=d["name"],
            file=d.get("file", ""),
            start_line=d.get("start_line", 0),
            end_line=d.get("end_line", 0),
            summary=d.get("summary", ""),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

@dataclass
class GraphEdge:
    """A directed relationship between two nodes."""

    from_id: str
    to_id: str
    relationship: EdgeType
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "relationship": self.relationship.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GraphEdge":
        return cls(
            from_id=d["from_id"],
            to_id=d["to_id"],
            relationship=EdgeType(d["relationship"]),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Reference  (line-level)
# ---------------------------------------------------------------------------

@dataclass
class Reference:
    """
    Tracks exactly which source line references which symbol.

    Example:
        src/core/agent.py : 42  CALLS  ToolOrchestrator.execute
    """

    source_file: str
    source_line: int
    source_symbol: str   # enclosing function / class where the call lives
    target_symbol: str   # symbol being referenced
    relationship: EdgeType

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_line": self.source_line,
            "source_symbol": self.source_symbol,
            "target_symbol": self.target_symbol,
            "relationship": self.relationship.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Reference":
        return cls(
            source_file=d["source_file"],
            source_line=d["source_line"],
            source_symbol=d.get("source_symbol", ""),
            target_symbol=d["target_symbol"],
            relationship=EdgeType(d["relationship"]),
        )

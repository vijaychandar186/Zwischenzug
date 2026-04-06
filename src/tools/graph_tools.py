"""
Graph tools — LLM-accessible knowledge-graph query tools.

These tools allow the agent to interrogate the program knowledge graph
during a conversation, enabling architecture reasoning, impact analysis,
and flow tracing without re-reading source files every turn.

All tools are read-only (is_read_only = True).

Registration:
    Call register_graph_tools(registry, cwd) to add them to a ToolRegistry.
    They load the graph lazily (on first call) from .zwis/graph/graph.json.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import Tool, ToolContext, ToolOutput

logger = logging.getLogger("zwischenzug.tools.graph")


# ---------------------------------------------------------------------------
# Lazy graph loader
# ---------------------------------------------------------------------------

def _load_graph(cwd: str):
    """Load the graph from .zwis/graph/graph.json, or return None."""
    from ..app_paths import app_home
    from ..graph.storage import load_graph
    return load_graph(app_home(cwd))


def _no_graph_msg() -> ToolOutput:
    return ToolOutput.error(
        "No knowledge graph found. Run 'zwis learn' first to build the graph."
    )


# ---------------------------------------------------------------------------
# graph_search — find nodes by name / type
# ---------------------------------------------------------------------------

class GraphSearchTool(Tool):
    """Search the knowledge graph for nodes by name or type."""

    @property
    def name(self) -> str:
        return "graph_search"

    @property
    def description(self) -> str:
        return (
            "Search the repository knowledge graph for code symbols. "
            "Finds functions, classes, methods, files, or routes matching a query. "
            "Use this to locate where a symbol is defined before reasoning about it."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Name or partial name of the symbol to find",
                },
                "node_type": {
                    "type": "string",
                    "description": (
                        "Optional filter by node type. "
                        "One of: file, class, function, method, variable, model, route, service, test, external"
                    ),
                },
            },
            "required": ["query"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        graph = _load_graph(ctx.cwd)
        if graph is None:
            return _no_graph_msg()

        query = kwargs.get("query", "").strip()
        node_type_str = (kwargs.get("node_type") or "").strip().lower()

        from ..graph.schema import NodeType
        node_type = None
        if node_type_str:
            try:
                node_type = NodeType(node_type_str)
            except ValueError:
                pass

        nodes = graph.find_by_name_partial(query, node_type)

        if not nodes:
            return ToolOutput.success(f"No nodes found matching '{query}'.")

        lines = [f"Found {len(nodes)} node(s) matching '{query}':\n"]
        for node in nodes[:20]:
            loc = f"  {node.file}:{node.start_line}" if node.start_line else f"  {node.file}"
            lines.append(f"  [{node.type.value}] {node.name}{loc}")
            if node.summary:
                lines.append(f"    {node.summary[:100]}")

        if len(nodes) > 20:
            lines.append(f"\n  … {len(nodes) - 20} more results")

        return ToolOutput.success("\n".join(lines))


# ---------------------------------------------------------------------------
# graph_explain — explain a module, class, or function
# ---------------------------------------------------------------------------

class GraphExplainTool(Tool):
    """Explain a module, class, or function using the knowledge graph."""

    @property
    def name(self) -> str:
        return "graph_explain"

    @property
    def description(self) -> str:
        return (
            "Explain a module, class, or function using the knowledge graph. "
            "Shows its components, dependencies, and what depends on it. "
            "More efficient than reading source files for architectural understanding."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": (
                        "Name or file path of the module/class/function to explain. "
                        "Examples: 'BashTool', 'src/tools/bash.py', 'run_agent'"
                    ),
                },
            },
            "required": ["symbol"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        graph = _load_graph(ctx.cwd)
        if graph is None:
            return _no_graph_msg()

        symbol = kwargs.get("symbol", "").strip()
        from ..graph.traversal import GraphTraversal
        traversal = GraphTraversal(graph)
        explanation = traversal.explain_module(symbol)
        return ToolOutput.success(explanation)


# ---------------------------------------------------------------------------
# graph_impact — impact analysis for a symbol
# ---------------------------------------------------------------------------

class GraphImpactTool(Tool):
    """Analyse the blast radius of changing a symbol."""

    @property
    def name(self) -> str:
        return "graph_impact"

    @property
    def description(self) -> str:
        return (
            "Analyse the impact of changing a code symbol. "
            "Shows which files, classes, and functions would be affected, "
            "and rates the risk level. Run this BEFORE modifying any symbol."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol (class, function, method, or file) to analyse",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Max dependency traversal depth (default 5)",
                },
            },
            "required": ["symbol"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        graph = _load_graph(ctx.cwd)
        if graph is None:
            return _no_graph_msg()

        symbol = kwargs.get("symbol", "").strip()
        max_depth = int(kwargs.get("max_depth") or 5)

        from ..graph.traversal import GraphTraversal
        from ..graph.visualizer import GraphVisualizer
        traversal = GraphTraversal(graph)
        viz = GraphVisualizer(graph)

        report = traversal.impact_analysis(symbol, max_depth=max_depth)
        return ToolOutput.success(viz.impact_tree(report))


# ---------------------------------------------------------------------------
# graph_trace — trace execution flow
# ---------------------------------------------------------------------------

class GraphTraceTool(Tool):
    """Trace execution flow from a function or entry point."""

    @property
    def name(self) -> str:
        return "graph_trace"

    @property
    def description(self) -> str:
        return (
            "Trace the call graph starting from a function or entry point. "
            "Shows what functions are called, in what order, and where they live. "
            "Useful for understanding request flows, startup sequences, etc."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "properties": {
                "entry_point": {
                    "type": "string",
                    "description": "Function or method name to trace from",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum call depth to trace (default 5)",
                },
            },
            "required": ["entry_point"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        graph = _load_graph(ctx.cwd)
        if graph is None:
            return _no_graph_msg()

        entry = kwargs.get("entry_point", "").strip()
        depth = int(kwargs.get("max_depth") or 5)

        from ..graph.traversal import GraphTraversal
        traversal = GraphTraversal(graph)
        trace = traversal.trace_flow(entry, max_depth=depth)
        return ToolOutput.success(trace)


# ---------------------------------------------------------------------------
# graph_refs — find all references to a symbol
# ---------------------------------------------------------------------------

class GraphRefsTool(Tool):
    """Find all references to a symbol across the codebase."""

    @property
    def name(self) -> str:
        return "graph_refs"

    @property
    def description(self) -> str:
        return (
            "Find all places in the codebase that reference a symbol. "
            "Returns file paths and line numbers — equivalent to IDE 'Find References'. "
            "Essential before renaming or deleting a symbol."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Symbol name to find references to",
                },
            },
            "required": ["symbol"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        graph = _load_graph(ctx.cwd)
        if graph is None:
            return _no_graph_msg()

        symbol = kwargs.get("symbol", "").strip()
        from ..learning.reference import ReferenceTracker
        tracker = ReferenceTracker(graph)
        formatted = tracker.format_refs(symbol)
        return ToolOutput.success(formatted)


# ---------------------------------------------------------------------------
# graph_map — architecture overview
# ---------------------------------------------------------------------------

class GraphMapTool(Tool):
    """Show the repository architecture map."""

    @property
    def name(self) -> str:
        return "graph_map"

    @property
    def description(self) -> str:
        return (
            "Show the repository's architecture map — all modules and how they "
            "depend on each other. Gives a bird's-eye view of the codebase structure."
        )

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {
            "properties": {
                "max_files": {
                    "type": "integer",
                    "description": "Max number of files to show (default 40)",
                },
            },
            "required": [],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        graph = _load_graph(ctx.cwd)
        if graph is None:
            return _no_graph_msg()

        max_files = int(kwargs.get("max_files") or 40)
        from ..graph.visualizer import GraphVisualizer
        viz = GraphVisualizer(graph)
        return ToolOutput.success(viz.architecture_map(max_files=max_files))


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------

def register_graph_tools(registry: Any, cwd: str) -> None:
    """
    Register all graph tools into the given ToolRegistry.

    Called from the agent startup when a graph exists.
    Graph tools are only registered when .zwis/graph/graph.json is present
    so they don't clutter the tool list for repos that haven't been learned.
    """
    from ..app_paths import app_home
    from ..graph.storage import graph_exists

    if not graph_exists(app_home(cwd)):
        logger.debug("No graph found at %s — skipping graph tool registration", cwd)
        return

    for tool in [
        GraphSearchTool(),
        GraphExplainTool(),
        GraphImpactTool(),
        GraphTraceTool(),
        GraphRefsTool(),
        GraphMapTool(),
    ]:
        registry.register(tool)

    logger.info("Graph tools registered (graph_search, graph_explain, graph_impact, graph_trace, graph_refs, graph_map)")

"""
Zwischenzug catalog — command/tool registry, routing, session store.
"""
from .catalog import (
    command_entries,
    execute_command,
    execute_tool,
    find_commands,
    find_tools,
    get_command,
    get_commands,
    get_tool,
    get_tools,
    render_command_index,
    render_tool_index,
    tool_entries,
)
from .manifest import build_port_manifest
from .models import (
    CatalogEntry,
    ExecutionResult,
    ModuleSummary,
    PortManifest,
    RoutedMatch,
    RuntimeSession,
    SessionPayload,
    StoredSession,
    TurnResult,
)
from .parity import run_parity_audit
from .query_engine import QueryEnginePort
from .reports import bootstrap_graph, command_graph, setup_report, tool_pool
from .runtime import PortRuntime
from .session_store import load_session, save_session, list_sessions, latest_session_id

__all__ = [
    # catalog
    "command_entries", "tool_entries",
    "get_command", "get_tool", "find_commands", "find_tools",
    "get_commands", "get_tools",
    "execute_command", "execute_tool",
    "render_command_index", "render_tool_index",
    # models
    "CatalogEntry", "ExecutionResult", "RoutedMatch", "TurnResult",
    "RuntimeSession", "ModuleSummary", "PortManifest",
    "SessionPayload", "StoredSession",
    # query engine
    "QueryEnginePort",
    # runtime
    "PortRuntime",
    # session store
    "save_session", "load_session", "list_sessions", "latest_session_id",
    # manifest
    "build_port_manifest",
    # parity
    "run_parity_audit",
    # reports
    "setup_report", "command_graph", "tool_pool", "bootstrap_graph",
]

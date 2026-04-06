from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import CatalogEntry, ExecutionResult
from ..permissions import ToolPermissionContext

ROOT = Path(__file__).resolve().parent / "reference_data"


def _load_entries(filename: str) -> tuple[CatalogEntry, ...]:
    raw = json.loads((ROOT / filename).read_text())
    return tuple(CatalogEntry(name=e["name"], responsibility=e["responsibility"], source_hint=e["source_hint"]) for e in raw)


@lru_cache(maxsize=1)
def command_entries() -> tuple[CatalogEntry, ...]:
    return _load_entries("commands_snapshot.json")


@lru_cache(maxsize=1)
def tool_entries() -> tuple[CatalogEntry, ...]:
    return _load_entries("tools_snapshot.json")


def get_command(name: str) -> CatalogEntry | None:
    needle = name.lower()
    return next((e for e in command_entries() if e.name.lower() == needle), None)


def get_tool(name: str) -> CatalogEntry | None:
    needle = name.lower()
    return next((e for e in tool_entries() if e.name.lower() == needle), None)


def find_commands(query: str, limit: int = 20) -> list[CatalogEntry]:
    q = query.lower()
    matches = [e for e in command_entries() if q in e.name.lower() or q in e.source_hint.lower() or q in e.responsibility.lower()]
    return matches[:limit]


def find_tools(query: str, limit: int = 20) -> list[CatalogEntry]:
    q = query.lower()
    matches = [e for e in tool_entries() if q in e.name.lower() or q in e.source_hint.lower() or q in e.responsibility.lower()]
    return matches[:limit]


def get_commands(include_plugin_commands: bool = True, include_skill_commands: bool = True) -> tuple[CatalogEntry, ...]:
    entries = list(command_entries())
    if not include_plugin_commands:
        entries = [e for e in entries if "plugin" not in e.source_hint.lower()]
    if not include_skill_commands:
        entries = [e for e in entries if "skill" not in e.source_hint.lower()]
    return tuple(entries)


def get_tools(simple_mode: bool = False, include_mcp: bool = True, permission_context: ToolPermissionContext | None = None) -> tuple[CatalogEntry, ...]:
    entries = list(tool_entries())
    if simple_mode:
        allowed = {"BashTool", "FileReadTool", "FileEditTool"}
        entries = [e for e in entries if e.name in allowed]
    if not include_mcp:
        entries = [e for e in entries if "mcp" not in e.name.lower() and "mcp" not in e.source_hint.lower()]
    if permission_context is not None:
        entries = [e for e in entries if not permission_context.blocks(e.name)]
    return tuple(entries)


def execute_command(name: str, prompt: str) -> ExecutionResult:
    entry = get_command(name)
    if entry is None:
        return ExecutionResult(handled=False, message=f"Unknown command: {name}")
    return ExecutionResult(handled=True, message=f"Command '{entry.name}' processed prompt {prompt!r}.")


def execute_tool(name: str, payload: str) -> ExecutionResult:
    entry = get_tool(name)
    if entry is None:
        return ExecutionResult(handled=False, message=f"Unknown tool: {name}")
    return ExecutionResult(handled=True, message=f"Tool '{entry.name}' processed payload {payload!r}.")


def render_command_index(limit: int = 20, query: str | None = None) -> str:
    rows = find_commands(query, limit) if query else list(command_entries()[:limit])
    lines = [f"Command entries: {len(command_entries())}", ""]
    if query:
        lines.extend([f"Filtered by: {query}", ""])
    lines.extend(f"- {r.name} - {r.source_hint}" for r in rows)
    return "\n".join(lines)


def render_tool_index(limit: int = 20, query: str | None = None) -> str:
    rows = find_tools(query, limit) if query else list(tool_entries()[:limit])
    lines = [f"Tool entries: {len(tool_entries())}", ""]
    if query:
        lines.extend([f"Filtered by: {query}", ""])
    lines.extend(f"- {r.name} - {r.source_hint}" for r in rows)
    return "\n".join(lines)

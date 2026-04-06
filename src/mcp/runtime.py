from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import (
    BlobResourceContents,
    EmbeddedResource,
    Resource,
    TextContent,
    TextResourceContents,
    Tool as MCPToolSpec,
)

from ..tools import Tool, ToolContext, ToolOutput, ToolRegistry
from .config import MCPServerConfig, list_servers

logger = logging.getLogger("zwischenzug.mcp")
logging.getLogger("mcp.client.stdio").setLevel(logging.CRITICAL)


@dataclass(slots=True)
class MCPServerSnapshot:
    server: MCPServerConfig
    tools: list[MCPToolSpec] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _safe_name(value: str) -> str:
    chars = []
    for ch in value:
        chars.append(ch.lower() if ch.isalnum() else "_")
    normalized = "".join(chars).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized or "server"


def _is_method_not_found_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "method not found" in text or "method_not_found" in text


def _is_missing_command_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    text = str(exc).lower()
    return "no such file or directory" in text or "[errno 2]" in text


def _is_likely_read_only_tool_name(name: str) -> bool:
    normalized = name.strip().lower()
    return normalized.startswith(
        (
            "get",
            "list",
            "read",
            "fetch",
            "find",
            "search",
            "describe",
            "show",
        )
    )


def _normalize_json_text(value: str) -> str:
    try:
        return json.dumps(json.loads(value), sort_keys=True)
    except Exception:  # noqa: BLE001
        return value.strip()


def _append_unique_part(parts: list[str], part: str) -> None:
    text = part.strip()
    if not text:
        return
    normalized = _normalize_json_text(text)
    if any(_normalize_json_text(existing) == normalized for existing in parts):
        return
    parts.append(text)


@asynccontextmanager
async def _open_session(server: MCPServerConfig):
    timeout = timedelta(seconds=server.timeout_seconds)
    if server.transport == "stdio":
        params = StdioServerParameters(
            command=server.command or "",
            args=server.args,
            env=server.env or None,
            cwd=server.cwd,
        )
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                read_stream, write_stream = streams
                async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
                    await session.initialize()
                    yield session
        return

    if server.transport == "http":
        async with streamablehttp_client(
            server.url or "",
            headers=server.headers or None,
            timeout=server.timeout_seconds,
            sse_read_timeout=server.sse_read_timeout_seconds,
        ) as streams:
            read_stream, write_stream, _ = streams
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
                await session.initialize()
                yield session
        return

    if server.transport == "sse":
        async with sse_client(
            server.url or "",
            headers=server.headers or None,
            timeout=server.timeout_seconds,
            sse_read_timeout=server.sse_read_timeout_seconds,
        ) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream, read_timeout_seconds=timeout) as session:
                await session.initialize()
                yield session
        return

    raise ValueError(f"Unsupported MCP transport: {server.transport}")


async def _discover_server(server: MCPServerConfig) -> MCPServerSnapshot:
    snapshot = MCPServerSnapshot(server=server)
    try:
        async with _open_session(server) as session:
            try:
                snapshot.tools = list((await session.list_tools()).tools)
            except Exception as exc:  # noqa: BLE001
                if not _is_method_not_found_error(exc):
                    snapshot.errors.append(f"list_tools failed: {exc}")
            try:
                snapshot.resources = list((await session.list_resources()).resources)
            except Exception as exc:  # noqa: BLE001
                if not _is_method_not_found_error(exc):
                    snapshot.errors.append(f"list_resources failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        snapshot.errors.append(str(exc))
    return snapshot


async def discover_servers(cwd: str | None = None) -> list[MCPServerSnapshot]:
    servers = [server for server in list_servers(cwd) if server.enabled]
    if not servers:
        return []
    return await asyncio.gather(*(_discover_server(server) for server in servers))


def _discover_servers_sync(cwd: str | None = None) -> list[MCPServerSnapshot]:
    return asyncio.run(discover_servers(cwd))


def _render_content_block(item: Any) -> str:
    if isinstance(item, TextContent):
        return item.text
    if isinstance(item, EmbeddedResource):
        return _render_resource_block(item.resource)
    if hasattr(item, "model_dump"):
        return json.dumps(item.model_dump(mode="json"), indent=2, sort_keys=True)
    return str(item)


def _render_resource_block(item: Any) -> str:
    if isinstance(item, TextResourceContents):
        return item.text
    if isinstance(item, BlobResourceContents):
        return f"[binary resource omitted] uri={item.uri} mime={item.mimeType or 'unknown'}"
    if hasattr(item, "model_dump"):
        return json.dumps(item.model_dump(mode="json"), indent=2, sort_keys=True)
    return str(item)


async def call_tool(server: MCPServerConfig, tool_name: str, arguments: dict[str, Any]) -> ToolOutput:
    async with _open_session(server) as session:
        result = await session.call_tool(tool_name, arguments)
    parts = []
    if result.structuredContent is not None:
        _append_unique_part(parts, json.dumps(result.structuredContent, indent=2, sort_keys=True))
    for item in result.content:
        _append_unique_part(parts, _render_content_block(item))
    content = "\n\n".join(p for p in parts if p).strip() or "(no output)"
    return ToolOutput(content=content, is_error=bool(result.isError))


async def read_resource(server: MCPServerConfig, uri: str) -> ToolOutput:
    async with _open_session(server) as session:
        result = await session.read_resource(uri)
    parts = [_render_resource_block(item) for item in result.contents]
    content = "\n\n".join(p for p in parts if p).strip() or "(empty resource)"
    return ToolOutput.success(content)


class MCPProxyTool(Tool):
    def __init__(self, server: MCPServerConfig, spec: MCPToolSpec) -> None:
        self._server = server
        self._spec = spec
        self._resolved_name = f"mcp__{_safe_name(server.name)}__{_safe_name(spec.name)}"

    @property
    def name(self) -> str:
        return self._resolved_name

    @property
    def description(self) -> str:
        base = self._spec.description or self._spec.title or f"MCP tool {self._spec.name}"
        return f"[MCP:{self._server.name}] {base}"

    @property
    def is_read_only(self) -> bool:
        annotations = getattr(self._spec, "annotations", None)
        if bool(getattr(annotations, "readOnlyHint", False)):
            return True
        return _is_likely_read_only_tool_name(self._spec.name)

    def input_schema(self) -> dict[str, Any]:
        schema = dict(self._spec.inputSchema or {})
        if schema.get("type") != "object":
            schema = {
                "type": "object",
                "properties": {"input": schema or {"type": "string"}},
                "required": ["input"],
            }
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        return schema

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        return await call_tool(self._server, self._spec.name, kwargs)


class MCPReadResourceTool(Tool):
    def __init__(self, server: MCPServerConfig, resources: list[Resource]) -> None:
        self._server = server
        self._resources = resources
        self._resolved_name = f"mcp__{_safe_name(server.name)}__read_resource"

    @property
    def name(self) -> str:
        return self._resolved_name

    @property
    def description(self) -> str:
        return f"[MCP:{self._server.name}] Read a resource by URI from the MCP server."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        description = "Resource URI to read."
        if self._resources:
            preview = ", ".join(resource.uri for resource in self._resources[:5])
            description = f"{description} Known URIs include: {preview}"
        return {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": description},
            },
            "required": ["uri"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        return await read_resource(self._server, str(kwargs["uri"]))


class MCPListResourcesTool(Tool):
    def __init__(self, server: MCPServerConfig, resources: list[Resource]) -> None:
        self._server = server
        self._resources = resources
        self._resolved_name = f"mcp__{_safe_name(server.name)}__list_resources"

    @property
    def name(self) -> str:
        return self._resolved_name

    @property
    def description(self) -> str:
        return f"[MCP:{self._server.name}] List resources exposed by the MCP server."

    @property
    def is_read_only(self) -> bool:
        return True

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        if not self._resources:
            return ToolOutput.success("No resources exposed by this MCP server.")
        lines = []
        for resource in self._resources:
            label = resource.name or resource.title or resource.uri
            desc = f" - {resource.description}" if resource.description else ""
            lines.append(f"{label} [{resource.uri}]{desc}")
        return ToolOutput.success("\n".join(lines))


def register_mcp_tools(registry: ToolRegistry, cwd: str | None = None) -> list[str]:
    try:
        snapshots = _discover_servers_sync(cwd)
    except RuntimeError:
        logger.warning("Skipping MCP discovery inside a running event loop.")
        return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("MCP discovery failed: %s", exc)
        return []

    registered: list[str] = []
    for snapshot in snapshots:
        if snapshot.errors:
            message = "; ".join(snapshot.errors)
            if any(_is_missing_command_error(RuntimeError(error)) for error in snapshot.errors):
                logger.info(
                    "Skipping MCP server '%s' because its command is unavailable: %s",
                    snapshot.server.name,
                    message,
                )
            else:
                logger.warning(
                    "MCP server '%s' discovery issues: %s",
                    snapshot.server.name,
                    message,
                )
        for spec in snapshot.tools:
            tool = MCPProxyTool(snapshot.server, spec)
            registry.register(tool)
            registered.append(tool.name)
        if snapshot.resources:
            for tool in (
                MCPListResourcesTool(snapshot.server, snapshot.resources),
                MCPReadResourceTool(snapshot.server, snapshot.resources),
            ):
                registry.register(tool)
                registered.append(tool.name)
    return registered

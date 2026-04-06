from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Resource, Tool as MCPToolSpec

from src.mcp.config import MCPServerConfig, add_server, get_server, remove_server
from src.mcp.runtime import MCPServerSnapshot, _discover_server, register_mcp_tools
from src.tools import PermissionMode, ToolContext, ToolRegistry


class TestMCPConfig:
    def test_add_and_get_project_server(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        saved = add_server(
            MCPServerConfig(
                name="github",
                transport="http",
                url="https://example.com/mcp",
                headers={"Authorization": "Bearer token"},
                scope="project",
            ),
            cwd=str(project),
        )

        loaded = get_server("github", cwd=str(project))
        assert loaded is not None
        assert saved.name == "github"
        assert loaded.url == "https://example.com/mcp"
        assert loaded.headers["Authorization"] == "Bearer token"
        assert loaded.scope == "project"

    def test_project_scope_overrides_user_scope(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        project = tmp_path / "project"
        project.mkdir()

        add_server(
            MCPServerConfig(name="shared", transport="http", url="https://user.example/mcp", scope="user"),
            cwd=str(project),
        )
        add_server(
            MCPServerConfig(name="shared", transport="http", url="https://project.example/mcp", scope="project"),
            cwd=str(project),
        )

        loaded = get_server("shared", cwd=str(project))
        assert loaded is not None
        assert loaded.url == "https://project.example/mcp"
        assert loaded.scope == "project"

    def test_remove_server(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        add_server(MCPServerConfig(name="temp", transport="http", url="https://example.com", scope="project"), cwd=str(project))
        assert remove_server("temp", scope="project", cwd=str(project)) is True
        assert get_server("temp", cwd=str(project)) is None

    def test_repairs_legacy_stdio_command_saved_as_mcp(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        saved = add_server(
            MCPServerConfig(
                name="time",
                transport="stdio",
                command="mcp",
                args=["-y", "@modelcontextprotocol/server-time"],
                scope="project",
            ),
            cwd=str(project),
        )

        assert saved.command == "npx"
        assert saved.args == ["-y", "@modelcontextprotocol/server-time"]


class TestMCPRuntime:
    async def test_discover_server_ignores_optional_method_not_found(self, monkeypatch):
        server = MCPServerConfig(name="memory", transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-memory"])

        class _Session:
            async def list_tools(self):
                class _Result:
                    tools = []
                return _Result()

            async def list_resources(self):
                raise RuntimeError("Method not found")

        class _SessionCM:
            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.mcp.runtime._open_session", lambda _server: _SessionCM())

        snapshot = await _discover_server(server)
        assert snapshot.errors == []
        assert snapshot.resources == []

    def test_register_mcp_tools_from_snapshot(self, monkeypatch, tmp_path):
        registry = ToolRegistry()
        snapshot = MCPServerSnapshot(
            server=MCPServerConfig(name="github", transport="http", url="https://example.com", scope="project"),
            tools=[
                MCPToolSpec(
                    name="search_issues",
                    description="Search issues",
                    inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                )
            ],
            resources=[
                Resource(name="Repo README", uri="repo://README.md", description="Readme"),
            ],
        )
        monkeypatch.setattr("src.mcp.runtime._discover_servers_sync", lambda cwd=None: [snapshot])

        names = register_mcp_tools(registry, cwd=str(tmp_path))

        assert "mcp__github__search_issues" in names
        assert "mcp__github__list_resources" in names
        assert "mcp__github__read_resource" in names
        assert registry.get("mcp__github__search_issues") is not None

    def test_register_mcp_tools_suppresses_missing_stdio_command_warning(self, monkeypatch, tmp_path, caplog):
        registry = ToolRegistry()
        snapshot = MCPServerSnapshot(
            server=MCPServerConfig(name="time", transport="stdio", command="uvx", args=["mcp-server-time"]),
            errors=["[Errno 2] No such file or directory: 'uvx'"],
        )
        monkeypatch.setattr("src.mcp.runtime._discover_servers_sync", lambda cwd=None: [snapshot])

        names = register_mcp_tools(registry, cwd=str(tmp_path))

        assert names == []
        assert "MCP server 'time' discovery issues" not in caplog.text

    def test_read_prefixed_tool_defaults_to_read_only(self, monkeypatch, tmp_path):
        registry = ToolRegistry()
        snapshot = MCPServerSnapshot(
            server=MCPServerConfig(name="memory", transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-memory"]),
            tools=[
                MCPToolSpec(
                    name="read_graph",
                    description="Read the graph",
                    inputSchema={"type": "object", "properties": {}},
                )
            ],
        )
        monkeypatch.setattr("src.mcp.runtime._discover_servers_sync", lambda cwd=None: [snapshot])

        register_mcp_tools(registry, cwd=str(tmp_path))
        tool = registry.get("mcp__memory__read_graph")
        assert tool is not None
        assert tool.is_read_only is True

    async def test_proxy_tool_executes_via_runtime(self, monkeypatch, tmp_path):
        registry = ToolRegistry()
        snapshot = MCPServerSnapshot(
            server=MCPServerConfig(name="github", transport="http", url="https://example.com", scope="project"),
            tools=[
                MCPToolSpec(
                    name="search_issues",
                    description="Search issues",
                    inputSchema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                )
            ],
        )
        monkeypatch.setattr("src.mcp.runtime._discover_servers_sync", lambda cwd=None: [snapshot])

        calls: list[tuple[str, dict[str, str]]] = []

        async def fake_call_tool(server, tool_name, arguments):
            calls.append((tool_name, arguments))
            from src.tools import ToolOutput

            return ToolOutput.success("ok")

        monkeypatch.setattr("src.mcp.runtime.call_tool", fake_call_tool)
        register_mcp_tools(registry, cwd=str(tmp_path))

        tool = registry.get("mcp__github__search_issues")
        assert tool is not None

        out = await tool.execute(ToolContext(cwd=str(tmp_path)), query="bug")
        assert out.content == "ok"
        assert calls == [("search_issues", {"query": "bug"})]

    async def test_call_tool_deduplicates_structured_and_text_json(self, monkeypatch):
        server = MCPServerConfig(name="memory", transport="stdio", command="npx", args=["-y", "@modelcontextprotocol/server-memory"])

        class _Result:
            structuredContent = {"entities": [], "relations": []}
            isError = False
            content = []

        from mcp.types import TextContent
        _Result.content = [TextContent(type="text", text='{\n  "entities": [],\n  "relations": []\n}')]

        class _Session:
            async def call_tool(self, tool_name, arguments):
                return _Result()

        class _SessionCM:
            async def __aenter__(self):
                return _Session()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        monkeypatch.setattr("src.mcp.runtime._open_session", lambda _server: _SessionCM())

        from src.mcp.runtime import call_tool

        out = await call_tool(server, "read_graph", {})
        assert out.is_error is False
        assert out.content.count('"entities"') == 1


class TestMCPCLI:
    def _run(self, cwd: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        merged_env = None
        if env is not None:
            merged_env = {**os.environ, **env}
        return subprocess.run(
            [sys.executable, "-m", "src.main", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            env=merged_env,
        )

    def test_add_list_get_remove_project_server(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        env = None

        added = self._run(
            project,
            "mcp", "add", "github",
            "--transport", "http",
            "--header", "Authorization: Bearer token",
            "--url", "https://example.com/mcp",
            env=env,
        )
        assert added.returncode == 0

        listed = self._run(project, "mcp", "list", env=env)
        assert listed.returncode == 0
        assert "github" in listed.stdout

        got = self._run(project, "mcp", "get", "github", "--json", env=env)
        assert got.returncode == 0
        assert '"url": "https://example.com/mcp"' in got.stdout

        removed = self._run(project, "mcp", "remove", "github", env=env)
        assert removed.returncode == 0

        listed_after = self._run(project, "mcp", "list", env=env)
        assert "No MCP servers configured." in listed_after.stdout

    def test_stdio_add_accepts_arg_values_that_start_with_dash(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        added = self._run(
            project,
            "mcp", "add", "time",
            "--transport", "stdio",
            "--command", "npx",
            "--arg", "-y",
            "--arg", "@modelcontextprotocol/server-time",
        )
        assert added.returncode == 0

        got = self._run(project, "mcp", "get", "time", "--json")
        assert got.returncode == 0
        assert '"command": "npx"' in got.stdout
        assert '"-y"' in got.stdout
        assert '"@modelcontextprotocol/server-time"' in got.stdout

    def test_stdio_add_accepts_claude_style_double_dash_syntax(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()

        added = self._run(
            project,
            "mcp", "add", "time",
            "--transport", "stdio",
            "--",
            "npx",
            "-y",
            "@modelcontextprotocol/server-time",
        )
        assert added.returncode == 0

        got = self._run(project, "mcp", "get", "time", "--json")
        assert got.returncode == 0
        assert '"command": "npx"' in got.stdout
        assert '"-y"' in got.stdout

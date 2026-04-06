"""
Tests for src/permissions — ToolPermissionContext and PermissionMode.
"""
from __future__ import annotations

import pytest

from src.permissions import PermissionMode, ToolPermissionContext
from src.tools import PermissionMode as ToolsPermissionMode


class TestPermissionMode:
    def test_auto_value(self):
        assert PermissionMode.AUTO == "auto"

    def test_interactive_value(self):
        assert PermissionMode.INTERACTIVE == "interactive"

    def test_deny_value(self):
        assert PermissionMode.DENY == "deny"

    def test_from_string(self):
        assert PermissionMode("auto") == PermissionMode.AUTO
        assert PermissionMode("interactive") == PermissionMode.INTERACTIVE
        assert PermissionMode("deny") == PermissionMode.DENY

    def test_permissions_and_tools_share_same_enum(self):
        # Both src.permissions and src.tools export the same enum
        assert PermissionMode.AUTO == ToolsPermissionMode.AUTO


class TestToolPermissionContext:
    def test_empty_context_blocks_nothing(self):
        ctx = ToolPermissionContext.from_iterables([], [])
        assert not ctx.blocks("BashTool")
        assert not ctx.blocks("FileReadTool")

    def test_denied_tool_is_blocked(self):
        ctx = ToolPermissionContext.from_iterables(["BashTool"], [])
        assert ctx.blocks("BashTool")
        assert ctx.blocks("bashtool")  # case-insensitive

    def test_allowed_tool_is_not_blocked(self):
        ctx = ToolPermissionContext.from_iterables(["BashTool"], [])
        assert not ctx.blocks("FileReadTool")

    def test_denied_prefix_blocks_matching_tools(self):
        ctx = ToolPermissionContext.from_iterables([], ["mcp"])
        assert ctx.blocks("McpServerTool")
        assert ctx.blocks("mcpanalytics")

    def test_denied_prefix_does_not_block_non_matching(self):
        ctx = ToolPermissionContext.from_iterables([], ["mcp"])
        assert not ctx.blocks("BashTool")

    def test_multiple_denied_tools(self):
        ctx = ToolPermissionContext.from_iterables(["BashTool", "FileWriteTool"], [])
        assert ctx.blocks("BashTool")
        assert ctx.blocks("FileWriteTool")
        assert not ctx.blocks("FileReadTool")

    def test_multiple_denied_prefixes(self):
        ctx = ToolPermissionContext.from_iterables([], ["mcp", "web"])
        assert ctx.blocks("McpTool")
        assert ctx.blocks("WebFetchTool")
        assert not ctx.blocks("BashTool")

    def test_normalization_case_insensitive_denied_tools(self):
        ctx = ToolPermissionContext.from_iterables(["BASHTOOL"], [])
        assert ctx.blocks("BashTool")
        assert ctx.blocks("bashtool")
        assert ctx.blocks("BASHTOOL")

    def test_normalization_case_insensitive_prefixes(self):
        ctx = ToolPermissionContext.from_iterables([], ["MCP"])
        assert ctx.blocks("mcpserver")
        assert ctx.blocks("MCPServer")

    def test_from_iterables_returns_frozen_context(self):
        ctx = ToolPermissionContext.from_iterables(["a"], ["b"])
        assert isinstance(ctx.denied_tools, frozenset)
        assert isinstance(ctx.denied_prefixes, tuple)

    def test_is_immutable(self):
        ctx = ToolPermissionContext.from_iterables(["BashTool"], [])
        with pytest.raises((AttributeError, TypeError)):
            ctx.denied_tools = frozenset()  # type: ignore

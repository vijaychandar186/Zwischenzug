"""Tests for the plugin system."""
from __future__ import annotations

import json
import os

import pytest

from src.tools import PermissionMode, ToolContext
from src.plugins import (
    Plugin,
    PluginManifest,
    PluginRegistry,
    PluginStatus,
    PluginTool,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-plugins",
    )


@pytest.fixture
def plugin_dir(tmp_path):
    """Create a .zwis/plugins directory with a sample plugin."""
    pdir = tmp_path / ".zwis" / "plugins" / "sample-plugin"
    pdir.mkdir(parents=True)
    manifest = {
        "name": "sample-plugin",
        "version": "1.0.0",
        "description": "A test plugin",
        "author": "Test",
        "category": "testing",
        "tools": [],
        "skills": [],
        "hooks": [],
        "dependencies": [],
    }
    (pdir / "plugin.json").write_text(json.dumps(manifest))
    return tmp_path


class TestPluginManifest:
    def test_defaults(self):
        m = PluginManifest(name="test")
        assert m.version == "0.0.0"
        assert m.category == "general"
        assert m.tools == []

    def test_fields(self):
        m = PluginManifest(
            name="my-plugin",
            version="2.0.0",
            description="desc",
            author="me",
        )
        assert m.name == "my-plugin"
        assert m.version == "2.0.0"


class TestPluginRegistry:
    def test_discover_finds_plugins(self, plugin_dir):
        reg = PluginRegistry()
        discovered = reg.discover(str(plugin_dir))
        assert len(discovered) == 1
        assert discovered[0].manifest.name == "sample-plugin"

    def test_discover_empty_dir(self, tmp_path):
        reg = PluginRegistry()
        discovered = reg.discover(str(tmp_path))
        assert len(discovered) == 0

    def test_get_plugin(self, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        assert reg.get("sample-plugin") is not None
        assert reg.get("nonexistent") is None

    def test_all_and_enabled(self, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        assert len(reg.all()) == 1
        assert len(reg.enabled()) == 1

    def test_enable_disable(self, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        assert reg.disable("sample-plugin")
        assert len(reg.enabled()) == 0
        assert reg.enable("sample-plugin")
        assert len(reg.enabled()) == 1

    def test_remove(self, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        assert reg.remove("sample-plugin")
        assert len(reg.all()) == 0

    def test_invalid_manifest(self, tmp_path):
        pdir = tmp_path / ".zwis" / "plugins" / "bad-plugin"
        pdir.mkdir(parents=True)
        (pdir / "plugin.json").write_text("not valid json")
        reg = PluginRegistry()
        discovered = reg.discover(str(tmp_path))
        assert len(discovered) == 1
        assert discovered[0].status == PluginStatus.ERROR


class TestPluginTool:
    @pytest.mark.asyncio
    async def test_list_empty(self, ctx):
        tool = PluginTool(PluginRegistry())
        result = await tool.execute(ctx, action="list")
        assert "no plugins" in result.content.lower()

    @pytest.mark.asyncio
    async def test_list_with_plugins(self, ctx, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        tool = PluginTool(reg)
        ctx_with_dir = ToolContext(
            cwd=str(plugin_dir),
            permission_mode=PermissionMode.AUTO,
            session_id="x",
        )
        result = await tool.execute(ctx_with_dir, action="list")
        assert "sample-plugin" in result.content

    @pytest.mark.asyncio
    async def test_enable_disable(self, ctx, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        tool = PluginTool(reg)
        result = await tool.execute(ctx, action="disable", plugin_name="sample-plugin")
        assert not result.is_error
        result = await tool.execute(ctx, action="enable", plugin_name="sample-plugin")
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_info(self, ctx, plugin_dir):
        reg = PluginRegistry()
        reg.discover(str(plugin_dir))
        tool = PluginTool(reg)
        result = await tool.execute(ctx, action="info", plugin_name="sample-plugin")
        assert "sample-plugin" in result.content
        assert "1.0.0" in result.content

    @pytest.mark.asyncio
    async def test_info_unknown(self, ctx):
        tool = PluginTool(PluginRegistry())
        result = await tool.execute(ctx, action="info", plugin_name="nope")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_discover(self, ctx, plugin_dir):
        reg = PluginRegistry()
        tool = PluginTool(reg)
        ctx_with_dir = ToolContext(
            cwd=str(plugin_dir),
            permission_mode=PermissionMode.AUTO,
            session_id="x",
        )
        result = await tool.execute(ctx_with_dir, action="discover")
        assert not result.is_error

    @pytest.mark.asyncio
    async def test_unknown_action(self, ctx):
        tool = PluginTool(PluginRegistry())
        result = await tool.execute(ctx, action="explode")
        assert result.is_error

    def test_name(self):
        assert PluginTool().name == "plugin"

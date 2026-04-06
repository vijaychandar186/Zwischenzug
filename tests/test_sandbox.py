"""Tests for the sandboxing system."""
from __future__ import annotations

import json

import pytest

from src.tools import PermissionMode, ToolContext
from src.tools.sandbox import (
    BUILTIN_PROFILES,
    NetworkPolicy,
    SandboxEnforcer,
    SandboxProfile,
    SandboxTool,
    _ACTIVE_SANDBOXES,
    get_active_sandbox,
)


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return ToolContext(
        cwd=str(tmp_path),
        permission_mode=PermissionMode.AUTO,
        session_id="test-sandbox",
    )


@pytest.fixture(autouse=True)
def _clear_sandboxes():
    _ACTIVE_SANDBOXES.clear()
    yield
    _ACTIVE_SANDBOXES.clear()


class TestSandboxToolMetadata:
    def test_name(self):
        assert SandboxTool().name == "sandbox"

    def test_not_read_only(self):
        assert not SandboxTool().is_read_only


class TestSandboxActivate:
    @pytest.mark.asyncio
    async def test_activate_default(self, ctx):
        result = await SandboxTool().execute(ctx, action="activate", profile="default")
        assert not result.is_error
        assert get_active_sandbox(ctx.session_id) is not None

    @pytest.mark.asyncio
    async def test_activate_unknown_profile(self, ctx):
        result = await SandboxTool().execute(ctx, action="activate", profile="nonexistent")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_deactivate(self, ctx):
        await SandboxTool().execute(ctx, action="activate", profile="default")
        result = await SandboxTool().execute(ctx, action="deactivate")
        assert not result.is_error
        assert get_active_sandbox(ctx.session_id) is None


class TestSandboxStatus:
    @pytest.mark.asyncio
    async def test_status_no_sandbox(self, ctx):
        result = await SandboxTool().execute(ctx, action="status")
        assert "no sandbox" in result.content.lower()

    @pytest.mark.asyncio
    async def test_status_with_sandbox(self, ctx):
        await SandboxTool().execute(ctx, action="activate", profile="strict")
        result = await SandboxTool().execute(ctx, action="status")
        assert "strict" in result.content


class TestSandboxList:
    @pytest.mark.asyncio
    async def test_list_profiles(self, ctx):
        result = await SandboxTool().execute(ctx, action="list")
        assert "default" in result.content
        assert "strict" in result.content
        assert "network-off" in result.content
        assert "read-only" in result.content


class TestSandboxCreate:
    @pytest.mark.asyncio
    async def test_create_custom_profile(self, ctx):
        config = json.dumps({
            "name": "custom",
            "description": "Custom test profile",
            "network_policy": "deny",
            "blocked_tools": ["bash"],
        })
        result = await SandboxTool().execute(ctx, action="create", profile=config)
        assert not result.is_error
        assert "custom" in BUILTIN_PROFILES

    @pytest.mark.asyncio
    async def test_create_invalid_json(self, ctx):
        result = await SandboxTool().execute(ctx, action="create", profile="not json")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_create_missing_name(self, ctx):
        result = await SandboxTool().execute(
            ctx, action="create", profile='{"description": "no name"}'
        )
        assert result.is_error


class TestSandboxEnforcer:
    def test_blocked_tool(self):
        profile = SandboxProfile(name="test", blocked_tools=["bash"])
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_tool("bash") is not None
        assert enforcer.check_tool("read_file") is None

    def test_allowed_tools_only(self):
        profile = SandboxProfile(name="test", allowed_tools=["read_file", "grep"])
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_tool("read_file") is None
        assert enforcer.check_tool("bash") is not None

    def test_blocked_command(self):
        profile = SandboxProfile(name="test", blocked_commands=[r"rm\s+-rf\s+/"])
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_command("rm -rf /") is not None
        assert enforcer.check_command("echo hello") is None

    def test_network_deny(self):
        profile = SandboxProfile(name="test", network_policy=NetworkPolicy.DENY)
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_network() is not None

    def test_network_allow(self):
        profile = SandboxProfile(name="test", network_policy=NetworkPolicy.ALLOW)
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_network() is None

    def test_network_restrict_hosts(self):
        profile = SandboxProfile(
            name="test",
            network_policy=NetworkPolicy.RESTRICT,
            allowed_hosts=["*.example.com"],
        )
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_network("api.example.com") is None
        assert enforcer.check_network("evil.com") is not None

    def test_path_write_denylist(self):
        profile = SandboxProfile(name="test", fs_write_denylist=["*.env", "/etc/*"])
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_path_write("/app/.env") is not None
        assert enforcer.check_path_write("/etc/passwd") is not None
        assert enforcer.check_path_write("/app/code.py") is None

    def test_path_read_allowlist(self):
        profile = SandboxProfile(name="test", fs_read_allowlist=["/app/*"])
        enforcer = SandboxEnforcer(profile)
        assert enforcer.check_path_read("/app/code.py") is None
        assert enforcer.check_path_read("/etc/passwd") is not None


class TestBuiltinProfiles:
    def test_default_exists(self):
        assert "default" in BUILTIN_PROFILES

    def test_strict_blocks_bash(self):
        strict = BUILTIN_PROFILES["strict"]
        assert "bash" in strict.blocked_tools

    def test_network_off_denies_network(self):
        profile = BUILTIN_PROFILES["network-off"]
        assert profile.network_policy == NetworkPolicy.DENY

    def test_read_only_blocks_writes(self):
        profile = BUILTIN_PROFILES["read-only"]
        assert "write_file" in profile.blocked_tools
        assert "bash" in profile.blocked_tools


class TestRegistryIntegration:
    def test_sandbox_tool_in_registry(self):
        from src.tools import default_registry
        assert default_registry().get("sandbox") is not None

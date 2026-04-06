"""
Sandboxing system — configurable isolation profiles for tool execution.

Provides filesystem restrictions, network controls, resource limits,
and integration with the ToolOrchestrator permission system.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import Tool, ToolContext, ToolOutput


# ---------------------------------------------------------------------------
# Sandbox profile model
# ---------------------------------------------------------------------------

class NetworkPolicy(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    RESTRICT = "restrict"  # Only allow specific hosts


@dataclass
class SandboxProfile:
    """Defines isolation constraints for tool execution."""
    name: str
    description: str = ""
    # Filesystem
    fs_read_allowlist: list[str] = field(default_factory=list)  # Glob patterns
    fs_read_denylist: list[str] = field(default_factory=list)
    fs_write_allowlist: list[str] = field(default_factory=list)
    fs_write_denylist: list[str] = field(default_factory=list)
    # Network
    network_policy: NetworkPolicy = NetworkPolicy.ALLOW
    allowed_hosts: list[str] = field(default_factory=list)
    # Resource limits
    max_timeout_seconds: float = 300.0
    max_output_chars: int = 50_000
    max_memory_mb: int = 0  # 0 = unlimited
    # Tool restrictions
    blocked_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)  # empty = all
    # Bash restrictions
    blocked_commands: list[str] = field(default_factory=list)  # Regex patterns
    blocked_env_vars: list[str] = field(default_factory=list)  # Env vars to mask


# Built-in profiles
BUILTIN_PROFILES: dict[str, SandboxProfile] = {
    "default": SandboxProfile(
        name="default",
        description="Standard profile with sensible defaults.",
        fs_write_denylist=[
            "/etc/*", "/usr/*", "/bin/*", "/sbin/*",
            "*/.env", "*/.git/config", "*/credentials*",
        ],
        blocked_commands=[
            r"rm\s+-rf\s+/",
            r"mkfs\.",
            r"dd\s+.*of=/dev/",
            r":(){ :|:& };:",  # fork bomb
        ],
        blocked_env_vars=["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"],
    ),
    "strict": SandboxProfile(
        name="strict",
        description="Strict isolation — limited FS, no network, no dangerous tools.",
        fs_write_denylist=["*"],  # No writes by default
        network_policy=NetworkPolicy.DENY,
        blocked_tools=["bash", "shell_exec", "shell_create"],
        max_timeout_seconds=30.0,
    ),
    "network-off": SandboxProfile(
        name="network-off",
        description="All tools available but network access is blocked.",
        network_policy=NetworkPolicy.DENY,
        blocked_tools=["web_fetch", "web_search"],
    ),
    "read-only": SandboxProfile(
        name="read-only",
        description="Read-only access — no file writes, no bash, no network.",
        fs_write_denylist=["*"],
        network_policy=NetworkPolicy.DENY,
        blocked_tools=[
            "bash", "write_file", "edit_file", "apply_patch",
            "shell_create", "shell_exec", "shell_close",
            "web_fetch", "web_search",
        ],
    ),
}


# Session-scoped active sandbox
_ACTIVE_SANDBOXES: dict[str, SandboxProfile] = {}


def get_active_sandbox(session_id: str) -> SandboxProfile | None:
    """Get the active sandbox profile for a session."""
    return _ACTIVE_SANDBOXES.get(session_id)


# ---------------------------------------------------------------------------
# Sandbox enforcement
# ---------------------------------------------------------------------------

class SandboxEnforcer:
    """Checks tool calls against sandbox constraints."""

    def __init__(self, profile: SandboxProfile):
        self.profile = profile
        self._blocked_cmd_patterns = [
            re.compile(p, re.IGNORECASE) for p in profile.blocked_commands
        ]

    def check_tool(self, tool_name: str) -> str | None:
        """Check if a tool is allowed. Returns error message or None."""
        if self.profile.blocked_tools and tool_name in self.profile.blocked_tools:
            return f"Tool '{tool_name}' is blocked by sandbox profile '{self.profile.name}'."
        if self.profile.allowed_tools and tool_name not in self.profile.allowed_tools:
            return f"Tool '{tool_name}' is not in the sandbox allowlist."
        return None

    def check_command(self, command: str) -> str | None:
        """Check if a bash command is allowed. Returns error message or None."""
        for pattern in self._blocked_cmd_patterns:
            if pattern.search(command):
                return (
                    f"Command blocked by sandbox: matches pattern "
                    f"'{pattern.pattern}' in profile '{self.profile.name}'."
                )
        return None

    def check_path_read(self, path: str) -> str | None:
        """Check if reading a path is allowed."""
        return self._check_path(
            path, self.profile.fs_read_allowlist, self.profile.fs_read_denylist, "read"
        )

    def check_path_write(self, path: str) -> str | None:
        """Check if writing a path is allowed."""
        return self._check_path(
            path, self.profile.fs_write_allowlist, self.profile.fs_write_denylist, "write"
        )

    def check_network(self, host: str = "") -> str | None:
        """Check if network access is allowed."""
        if self.profile.network_policy == NetworkPolicy.DENY:
            return f"Network access blocked by sandbox profile '{self.profile.name}'."
        if self.profile.network_policy == NetworkPolicy.RESTRICT:
            if host and self.profile.allowed_hosts:
                if not any(_host_matches(host, ah) for ah in self.profile.allowed_hosts):
                    return f"Host '{host}' not in sandbox allowlist."
        return None

    def _check_path(
        self, path: str, allowlist: list[str], denylist: list[str], mode: str
    ) -> str | None:
        # Check denylist first
        for pattern in denylist:
            if _glob_match(path, pattern):
                return f"Path '{path}' blocked for {mode} by sandbox denylist."
        # If allowlist is set, path must match
        if allowlist:
            if not any(_glob_match(path, p) for p in allowlist):
                return f"Path '{path}' not in sandbox {mode} allowlist."
        return None


def _glob_match(path: str, pattern: str) -> bool:
    """Simple glob matching for sandbox paths."""
    import fnmatch
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(os.path.basename(path), pattern)


def _host_matches(host: str, pattern: str) -> bool:
    """Check if a host matches a pattern (supports *.example.com)."""
    import fnmatch
    return fnmatch.fnmatch(host.lower(), pattern.lower())


# ---------------------------------------------------------------------------
# SandboxTool
# ---------------------------------------------------------------------------

class SandboxTool(Tool):
    """Configure sandbox profiles for tool execution isolation."""

    @property
    def name(self) -> str:
        return "sandbox"

    @property
    def description(self) -> str:
        return (
            "Configure sandboxing for tool execution. Actions:\n"
            "- 'activate <profile>': Enable a sandbox profile "
            "(default, strict, network-off, read-only)\n"
            "- 'deactivate': Remove the active sandbox\n"
            "- 'status': Show current sandbox state\n"
            "- 'list': List available profiles\n"
            "- 'create': Create a custom profile (pass JSON config)"
        )

    @property
    def is_read_only(self) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "Action: 'activate', 'deactivate', 'status', 'list', 'create'."
                    ),
                },
                "profile": {
                    "type": "string",
                    "description": (
                        "Profile name for 'activate'. "
                        "Or JSON config for 'create'."
                    ),
                },
            },
            "required": ["action"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        import json

        action = kwargs.get("action", "").strip().lower()
        profile_arg = kwargs.get("profile", "").strip()

        if action == "activate":
            if not profile_arg:
                return ToolOutput.error("Specify a profile name to activate.")
            profile = BUILTIN_PROFILES.get(profile_arg)
            if profile is None:
                return ToolOutput.error(
                    f"Unknown profile: {profile_arg!r}. "
                    f"Available: {', '.join(BUILTIN_PROFILES.keys())}"
                )
            _ACTIVE_SANDBOXES[ctx.session_id] = profile
            return ToolOutput.success(
                f"Sandbox activated: {profile.name}\n"
                f"Description: {profile.description}\n"
                f"Network: {profile.network_policy.value}\n"
                f"Blocked tools: {', '.join(profile.blocked_tools) or 'none'}"
            )

        elif action == "deactivate":
            if ctx.session_id in _ACTIVE_SANDBOXES:
                del _ACTIVE_SANDBOXES[ctx.session_id]
            return ToolOutput.success("Sandbox deactivated.")

        elif action == "status":
            profile = _ACTIVE_SANDBOXES.get(ctx.session_id)
            if profile is None:
                return ToolOutput.success("No sandbox active.")
            return ToolOutput.success(
                f"Active sandbox: {profile.name}\n"
                f"Description: {profile.description}\n"
                f"Network: {profile.network_policy.value}\n"
                f"Blocked tools: {', '.join(profile.blocked_tools) or 'none'}\n"
                f"Max timeout: {profile.max_timeout_seconds}s\n"
                f"FS write denylist: {', '.join(profile.fs_write_denylist) or 'none'}"
            )

        elif action == "list":
            lines = ["Available sandbox profiles:"]
            for p in BUILTIN_PROFILES.values():
                lines.append(f"  {p.name}: {p.description}")
            return ToolOutput.success("\n".join(lines))

        elif action == "create":
            if not profile_arg:
                return ToolOutput.error("'create' requires JSON config in 'profile'.")
            try:
                data = json.loads(profile_arg)
            except json.JSONDecodeError as exc:
                return ToolOutput.error(f"Invalid JSON: {exc}")

            if "name" not in data:
                return ToolOutput.error("Custom profile must have a 'name' field.")

            custom = SandboxProfile(
                name=data["name"],
                description=data.get("description", "Custom profile"),
                fs_read_denylist=data.get("fs_read_denylist", []),
                fs_write_denylist=data.get("fs_write_denylist", []),
                fs_read_allowlist=data.get("fs_read_allowlist", []),
                fs_write_allowlist=data.get("fs_write_allowlist", []),
                network_policy=NetworkPolicy(data.get("network_policy", "allow")),
                allowed_hosts=data.get("allowed_hosts", []),
                blocked_tools=data.get("blocked_tools", []),
                allowed_tools=data.get("allowed_tools", []),
                blocked_commands=data.get("blocked_commands", []),
                blocked_env_vars=data.get("blocked_env_vars", []),
                max_timeout_seconds=float(data.get("max_timeout_seconds", 300)),
                max_output_chars=int(data.get("max_output_chars", 50_000)),
            )
            BUILTIN_PROFILES[custom.name] = custom
            _ACTIVE_SANDBOXES[ctx.session_id] = custom
            return ToolOutput.success(
                f"Custom sandbox '{custom.name}' created and activated."
            )

        else:
            return ToolOutput.error(
                f"Unknown action: {action!r}. "
                "Use: activate, deactivate, status, list, create."
            )

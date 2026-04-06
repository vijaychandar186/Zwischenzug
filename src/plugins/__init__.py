"""
Plugin system — discover, load, and manage external plugins.

Plugins extend Zwischenzug with custom tools, skills, and hooks.
Discovery happens from directories: ~/.zwis/plugins/, .zwis/plugins/
Each plugin is a directory with a plugin.json manifest.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("zwischenzug.plugins")


# ---------------------------------------------------------------------------
# Plugin data model
# ---------------------------------------------------------------------------

class PluginStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass
class PluginManifest:
    """Parsed plugin.json manifest."""
    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    category: str = "general"
    # What the plugin provides
    tools: list[dict] = field(default_factory=list)  # [{module, class_name}]
    skills: list[str] = field(default_factory=list)  # relative paths to .md skill files
    hooks: list[dict] = field(default_factory=list)  # [{event, command}]
    # Dependencies
    dependencies: list[str] = field(default_factory=list)  # pip package names
    requires_tools: list[str] = field(default_factory=list)  # Zwis tools required
    # Source
    source_path: Path = field(default_factory=lambda: Path("."))


@dataclass
class Plugin:
    """A loaded plugin with its manifest and runtime state."""
    manifest: PluginManifest
    status: PluginStatus = PluginStatus.ENABLED
    error: str = ""
    loaded_tools: list = field(default_factory=list)
    loaded_skills: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Plugin Registry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Discovers, loads, and manages plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def discover(self, cwd: str = ".") -> list[Plugin]:
        """Discover plugins from standard directories."""
        plugin_dirs = [
            Path.home() / ".zwis" / "plugins",
            Path(cwd) / ".zwis" / "plugins",
            Path(cwd) / "plugins",
        ]

        discovered: list[Plugin] = []
        for pdir in plugin_dirs:
            if not pdir.is_dir():
                continue
            for entry in sorted(pdir.iterdir()):
                if not entry.is_dir():
                    continue
                manifest_path = entry / "plugin.json"
                if not manifest_path.exists():
                    continue
                try:
                    plugin = _load_plugin(manifest_path)
                    self._plugins[plugin.manifest.name] = plugin
                    discovered.append(plugin)
                except Exception as exc:
                    logger.warning("Failed to load plugin at %s: %s", entry, exc)
                    error_plugin = Plugin(
                        manifest=PluginManifest(
                            name=entry.name,
                            source_path=entry,
                        ),
                        status=PluginStatus.ERROR,
                        error=str(exc),
                    )
                    self._plugins[entry.name] = error_plugin
                    discovered.append(error_plugin)

        return discovered

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    def all(self) -> list[Plugin]:
        return list(self._plugins.values())

    def enabled(self) -> list[Plugin]:
        return [p for p in self._plugins.values() if p.status == PluginStatus.ENABLED]

    def enable(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        plugin.status = PluginStatus.ENABLED
        return True

    def disable(self, name: str) -> bool:
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        plugin.status = PluginStatus.DISABLED
        return True

    def remove(self, name: str) -> bool:
        return self._plugins.pop(name, None) is not None

    def register_tools(self, tool_registry: Any) -> int:
        """Load and register tools from all enabled plugins. Returns count registered."""
        count = 0
        for plugin in self.enabled():
            for tool_def in plugin.manifest.tools:
                try:
                    tool = _load_tool_class(plugin.manifest.source_path, tool_def)
                    if tool is not None:
                        tool_registry.register(tool)
                        plugin.loaded_tools.append(tool)
                        count += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to load tool %s from plugin %s: %s",
                        tool_def, plugin.manifest.name, exc,
                    )
        return count

    def register_skills(self, skill_registry: Any) -> int:
        """Load and register skills from all enabled plugins. Returns count registered."""
        count = 0
        for plugin in self.enabled():
            for skill_path in plugin.manifest.skills:
                try:
                    full_path = plugin.manifest.source_path / skill_path
                    if full_path.exists():
                        from ..skills import _parse_skill_file
                        skill = _parse_skill_file(full_path)
                        if skill:
                            skill_registry.register(skill)
                            plugin.loaded_skills.append(skill)
                            count += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to load skill %s from plugin %s: %s",
                        skill_path, plugin.manifest.name, exc,
                    )
        return count


def _load_plugin(manifest_path: Path) -> Plugin:
    """Load a plugin from its manifest file."""
    with open(manifest_path) as f:
        data = json.load(f)

    manifest = PluginManifest(
        name=data["name"],
        version=data.get("version", "0.0.0"),
        description=data.get("description", ""),
        author=data.get("author", ""),
        category=data.get("category", "general"),
        tools=data.get("tools", []),
        skills=data.get("skills", []),
        hooks=data.get("hooks", []),
        dependencies=data.get("dependencies", []),
        requires_tools=data.get("requires_tools", []),
        source_path=manifest_path.parent,
    )

    # Check dependencies
    missing_deps = _check_dependencies(manifest.dependencies)
    if missing_deps:
        return Plugin(
            manifest=manifest,
            status=PluginStatus.ERROR,
            error=f"Missing dependencies: {', '.join(missing_deps)}",
        )

    return Plugin(manifest=manifest, status=PluginStatus.ENABLED)


def _load_tool_class(source_path: Path, tool_def: dict) -> Any:
    """Dynamically load a tool class from a plugin."""
    import importlib.util

    module_path = source_path / tool_def.get("module", "")
    class_name = tool_def.get("class_name", "")

    if not module_path.exists():
        logger.warning("Tool module not found: %s", module_path)
        return None

    spec = importlib.util.spec_from_file_location(
        f"plugin_{source_path.name}_{module_path.stem}", module_path
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tool_class = getattr(module, class_name, None)
    if tool_class is None:
        return None

    return tool_class()


def _check_dependencies(deps: list[str]) -> list[str]:
    """Check if pip packages are installed. Returns list of missing."""
    import importlib
    missing = []
    for dep in deps:
        pkg_name = dep.split(">=")[0].split("==")[0].strip()
        try:
            importlib.import_module(pkg_name.replace("-", "_"))
        except ImportError:
            missing.append(dep)
    return missing


# ---------------------------------------------------------------------------
# PluginTool — CLI interface for managing plugins
# ---------------------------------------------------------------------------

from ..tools import Tool, ToolContext, ToolOutput


class PluginTool(Tool):
    """Manage plugins from within the agent."""

    def __init__(self, plugin_registry: PluginRegistry | None = None):
        self._registry = plugin_registry or PluginRegistry()

    @property
    def name(self) -> str:
        return "plugin"

    @property
    def description(self) -> str:
        return (
            "Manage Zwischenzug plugins. Actions:\n"
            "- 'list': Show all discovered plugins\n"
            "- 'enable <name>': Enable a plugin\n"
            "- 'disable <name>': Disable a plugin\n"
            "- 'info <name>': Show plugin details\n"
            "- 'discover': Re-scan plugin directories"
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
                    "description": "Action: 'list', 'enable', 'disable', 'info', 'discover'.",
                },
                "plugin_name": {
                    "type": "string",
                    "description": "Plugin name for enable/disable/info actions.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolOutput:
        action = kwargs.get("action", "").strip().lower()
        plugin_name = kwargs.get("plugin_name", "").strip()

        if action == "list":
            plugins = self._registry.all()
            if not plugins:
                return ToolOutput.success("No plugins discovered. Run 'discover' to scan.")
            lines = [f"Plugins ({len(plugins)}):"]
            for p in plugins:
                status_icon = {"enabled": "●", "disabled": "○", "error": "✗"}
                icon = status_icon.get(p.status.value, "?")
                lines.append(
                    f"  {icon} {p.manifest.name} v{p.manifest.version} "
                    f"[{p.status.value}] — {p.manifest.description[:60]}"
                )
                if p.error:
                    lines.append(f"      Error: {p.error}")
            return ToolOutput.success("\n".join(lines))

        elif action == "enable":
            if not plugin_name:
                return ToolOutput.error("Specify a plugin_name to enable.")
            if self._registry.enable(plugin_name):
                return ToolOutput.success(f"Plugin '{plugin_name}' enabled.")
            return ToolOutput.error(f"Plugin '{plugin_name}' not found.")

        elif action == "disable":
            if not plugin_name:
                return ToolOutput.error("Specify a plugin_name to disable.")
            if self._registry.disable(plugin_name):
                return ToolOutput.success(f"Plugin '{plugin_name}' disabled.")
            return ToolOutput.error(f"Plugin '{plugin_name}' not found.")

        elif action == "info":
            if not plugin_name:
                return ToolOutput.error("Specify a plugin_name.")
            plugin = self._registry.get(plugin_name)
            if plugin is None:
                return ToolOutput.error(f"Plugin '{plugin_name}' not found.")
            m = plugin.manifest
            lines = [
                f"Plugin: {m.name} v{m.version}",
                f"Status: {plugin.status.value}",
                f"Author: {m.author or 'unknown'}",
                f"Category: {m.category}",
                f"Description: {m.description}",
                f"Tools: {len(m.tools)}",
                f"Skills: {len(m.skills)}",
                f"Hooks: {len(m.hooks)}",
                f"Source: {m.source_path}",
            ]
            if plugin.error:
                lines.append(f"Error: {plugin.error}")
            return ToolOutput.success("\n".join(lines))

        elif action == "discover":
            plugins = self._registry.discover(ctx.cwd)
            return ToolOutput.success(
                f"Discovered {len(plugins)} plugins from plugin directories."
            )

        else:
            return ToolOutput.error(
                f"Unknown action: {action!r}. "
                "Use: list, enable, disable, info, discover."
            )

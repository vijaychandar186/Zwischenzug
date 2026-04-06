# Plugin System

## Overview

The plugin system (`src/plugins/__init__.py`) allows extending Zwischenzug with external tools, skills, and hooks. Plugins are directories containing a `plugin.json` manifest.

---

## Plugin Discovery

Plugins are discovered from these directories (in priority order):

1. `~/.zwis/plugins/` — User-level plugins
2. `.zwis/plugins/` — Project-level plugins
3. `plugins/` — Workspace plugins

---

## Manifest Format

Each plugin directory must contain a `plugin.json`:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "What this plugin does",
  "author": "Your Name",
  "category": "development",
  "tools": [
    {"module": "tools.py", "class_name": "MyCustomTool"}
  ],
  "skills": ["skills/my-skill.md"],
  "hooks": [
    {"event": "pre_tool_use", "command": "python check.py"}
  ],
  "dependencies": ["some-pip-package>=1.0"]
}
```

---

## Tool: `plugin`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | `list`, `enable`, `disable`, `info`, `discover` |
| `plugin_name` | string | No | Plugin name for enable/disable/info |

---

## Plugin States

| State | Description |
|-------|-------------|
| `enabled` | Active and loaded |
| `disabled` | Discovered but not active |
| `error` | Failed to load (missing deps, invalid manifest) |

---

## Creating a Plugin

1. Create a directory in `~/.zwis/plugins/my-plugin/`
2. Add `plugin.json` with the manifest
3. Add tool classes in Python files (must extend `Tool` from `src/tools`)
4. Add skill files as markdown with YAML frontmatter
5. Run `plugin(action='discover')` to load

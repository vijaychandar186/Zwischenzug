# Sandbox Tool

## Overview

The sandboxing system (`src/tools/sandbox.py`) provides configurable isolation profiles for tool execution. Profiles can restrict filesystem access, block network, limit specific tools, and filter dangerous commands.

---

## Tool

### `sandbox`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | Yes | `activate`, `deactivate`, `status`, `list`, `create` |
| `profile` | string | No | Profile name or JSON config |

---

## Built-in Profiles

| Profile | Network | Writes | Bash | Description |
|---------|---------|--------|------|-------------|
| `default` | Allow | Restricted | Yes | Blocks writes to system dirs and credentials |
| `strict` | Deny | Blocked | No | Maximum isolation, no writes or network |
| `network-off` | Deny | Allow | Yes | All tools except web_fetch/web_search |
| `read-only` | Deny | Blocked | No | Only read_file, glob, grep allowed |

---

## Custom Profiles

Create a custom profile by passing JSON to the `create` action:

```json
{
  "name": "my-profile",
  "description": "Custom restricted profile",
  "network_policy": "restrict",
  "allowed_hosts": ["*.github.com", "api.example.com"],
  "blocked_tools": ["bash"],
  "fs_write_denylist": ["*.env", "/etc/*"],
  "blocked_commands": ["rm -rf /"],
  "max_timeout_seconds": 60
}
```

---

## SandboxEnforcer

The `SandboxEnforcer` class performs enforcement checks:

- `check_tool(name)` — Is this tool allowed?
- `check_command(cmd)` — Is this bash command safe?
- `check_path_read(path)` — Can we read this path?
- `check_path_write(path)` — Can we write this path?
- `check_network(host)` — Is network access to this host allowed?

Each returns `None` if allowed, or an error message string if blocked.

---

## Network Policies

| Policy | Behavior |
|--------|----------|
| `allow` | All network access permitted |
| `deny` | All network access blocked |
| `restrict` | Only `allowed_hosts` patterns permitted |

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..app_paths import mcp_config_file, mcp_config_files

MCP_CONFIG_VERSION = 1


def _repair_legacy_stdio_command(command: str | None, args: list[str]) -> tuple[str | None, list[str]]:
    normalized_command = command.strip() if isinstance(command, str) else None
    normalized_args = [str(a) for a in args]

    # Compatibility repair for an earlier CLI parsing bug that could save
    # stdio servers as `command="mcp", args=["-y", "<package>"]` when the
    # user actually intended `npx -y <package>`.
    if normalized_command == "mcp" and normalized_args:
        first = normalized_args[0]
        second = normalized_args[1] if len(normalized_args) > 1 else ""
        if first == "-y" or second.startswith("@modelcontextprotocol/"):
            return "npx", normalized_args

    return normalized_command, normalized_args


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    transport: str
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True
    timeout_seconds: float = 30.0
    sse_read_timeout_seconds: float = 300.0
    scope: str = "project"

    def normalized(self) -> "MCPServerConfig":
        transport = self.transport.strip().lower()
        scope = self.scope.strip().lower()
        command, args = _repair_legacy_stdio_command(self.command, self.args)
        return MCPServerConfig(
            name=self.name.strip(),
            transport=transport,
            url=self.url.strip() if isinstance(self.url, str) and self.url.strip() else None,
            command=command,
            args=args,
            headers={str(k): str(v) for k, v in self.headers.items()},
            env={str(k): str(v) for k, v in self.env.items()},
            cwd=self.cwd.strip() if isinstance(self.cwd, str) and self.cwd.strip() else None,
            enabled=bool(self.enabled),
            timeout_seconds=float(self.timeout_seconds),
            sse_read_timeout_seconds=float(self.sse_read_timeout_seconds),
            scope=scope,
        )

    def validate(self) -> "MCPServerConfig":
        cfg = self.normalized()
        if not cfg.name:
            raise ValueError("MCP server name cannot be empty.")
        if cfg.transport not in {"stdio", "http", "sse"}:
            raise ValueError(f"Unsupported MCP transport: {cfg.transport}")
        if cfg.transport == "stdio":
            if not cfg.command:
                raise ValueError("stdio MCP servers require a command.")
        else:
            if not cfg.url:
                raise ValueError(f"{cfg.transport} MCP servers require a URL.")
        if cfg.scope not in {"project", "user"}:
            raise ValueError(f"Unsupported MCP config scope: {cfg.scope}")
        if cfg.timeout_seconds <= 0:
            raise ValueError("MCP timeout_seconds must be greater than 0.")
        if cfg.sse_read_timeout_seconds <= 0:
            raise ValueError("MCP sse_read_timeout_seconds must be greater than 0.")
        return cfg

    def to_record(self) -> dict[str, Any]:
        data = asdict(self.normalized())
        data.pop("scope", None)
        return data

    @classmethod
    def from_record(cls, data: dict[str, Any], *, scope: str) -> "MCPServerConfig":
        allowed = set(cls.__dataclass_fields__.keys()) - {"scope"}
        payload = {k: v for k, v in data.items() if k in allowed}
        payload["scope"] = scope
        return cls(**payload).validate()


def _load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": MCP_CONFIG_VERSION, "servers": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid MCP config format: {path}")
    servers = data.get("servers", [])
    if not isinstance(servers, list):
        raise ValueError(f"Invalid MCP servers list: {path}")
    return {
        "version": int(data.get("version", MCP_CONFIG_VERSION)),
        "servers": servers,
    }


def _save_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def list_servers(cwd: str | None = None) -> list[MCPServerConfig]:
    merged: dict[str, MCPServerConfig] = {}
    for path in mcp_config_files(cwd):
        scope = "user" if path == mcp_config_file("user", cwd) else "project"
        store = _load_store(path)
        for row in store["servers"]:
            server = MCPServerConfig.from_record(row, scope=scope)
            merged[server.name.lower()] = server
    return sorted(merged.values(), key=lambda s: (s.scope, s.name.lower()))


def get_server(name: str, cwd: str | None = None) -> MCPServerConfig | None:
    needle = name.strip().lower()
    for server in list_servers(cwd):
        if server.name.lower() == needle:
            return server
    return None


def add_server(server: MCPServerConfig, cwd: str | None = None) -> MCPServerConfig:
    cfg = server.validate()
    path = mcp_config_file(cfg.scope, cwd)
    store = _load_store(path)
    rows = []
    replaced = False
    for row in store["servers"]:
        existing = MCPServerConfig.from_record(row, scope=cfg.scope)
        if existing.name.lower() == cfg.name.lower():
            rows.append(cfg.to_record())
            replaced = True
        else:
            rows.append(existing.to_record())
    if not replaced:
        rows.append(cfg.to_record())
    store["servers"] = sorted(rows, key=lambda item: str(item.get("name", "")).lower())
    _save_store(path, store)
    return cfg


def remove_server(name: str, scope: str = "project", cwd: str | None = None) -> bool:
    normalized_scope = scope.strip().lower()
    path = mcp_config_file(normalized_scope, cwd)
    store = _load_store(path)
    before = len(store["servers"])
    store["servers"] = [
        row for row in store["servers"]
        if str(row.get("name", "")).strip().lower() != name.strip().lower()
    ]
    if len(store["servers"]) == before:
        return False
    _save_store(path, store)
    return True

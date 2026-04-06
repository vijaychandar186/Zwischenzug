from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = ".zwis"


def app_home(cwd: str | None = None) -> Path:
    override = os.getenv("ZWISCHENZUG_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / APP_DIR_NAME


def ensure_app_home(cwd: str | None = None) -> Path:
    home = app_home(cwd)
    home.mkdir(parents=True, exist_ok=True)
    return home


def sessions_dir(cwd: str | None = None) -> Path:
    return app_home(cwd) / "sessions"


def history_file(cwd: str | None = None) -> Path:
    return app_home(cwd) / "history"


def config_file(cwd: str | None = None) -> Path:
    return app_home(cwd) / "config.json"


def legacy_config_file() -> Path:
    return Path.home() / ".zwischenzug" / "config.json"


def mcp_config_file(scope: str = "project", cwd: str | None = None) -> Path:
    normalized = scope.strip().lower()
    if normalized == "user":
        return Path.home() / APP_DIR_NAME / "mcp.json"
    if normalized == "project":
        return app_home(cwd) / "mcp.json"
    raise ValueError(f"Unsupported MCP config scope: {scope}")


def mcp_config_files(cwd: str | None = None) -> list[Path]:
    """
    Return MCP config files in priority order (lowest → highest):
      1. ~/.zwis/mcp.json
      2. .zwis/mcp.json
    """
    return [
        mcp_config_file("user", cwd),
        mcp_config_file("project", cwd),
    ]


def legacy_history_file() -> Path:
    return Path.home() / ".zwischenzug_history"


def legacy_sessions_dir(cwd: str | None = None) -> Path:
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".port_sessions"


# ---------------------------------------------------------------------------
# Settings (hooks, permissions, etc.)
# ---------------------------------------------------------------------------

def settings_files(cwd: str | None = None) -> list[Path]:
    """
    Return settings.json paths in priority order (lowest → highest):
      1. ~/.zwis/settings.json  (user-level)
      2. .zwis/settings.json    (project-level, wins on conflict)
    """
    return [
        Path.home() / APP_DIR_NAME / "settings.json",
        app_home(cwd) / "settings.json",
    ]


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

def skills_dirs(cwd: str | None = None) -> list[Path]:
    """
    Return skill discovery directories in priority order (lowest → highest):
      1. Bundled skills (src/skills/builtin/)   — resolved relative to this file
      2. ~/.zwis/skills/                          (user-level)
      3. .zwis/skills/                            (project-level)
      4. skills/                                  (workspace root — highest precedence)
    """
    builtin = Path(__file__).resolve().parent / "skills" / "builtin"
    base = Path(cwd) if cwd is not None else Path.cwd()
    return [
        builtin,
        Path.home() / APP_DIR_NAME / "skills",
        app_home(cwd) / "skills",
        base / "skills",           # workspace-root skills/ — wins on name conflict
    ]


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def memory_dir() -> Path:
    """Persistent memory storage — always user-home-relative."""
    override = os.getenv("ZWISCHENZUG_MEMORY_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / APP_DIR_NAME / "memory"


def memory_index_file() -> Path:
    return memory_dir() / "MEMORY.md"


# ---------------------------------------------------------------------------
# Knowledge graph  (.zwis/graph/)
# ---------------------------------------------------------------------------

def graph_dir(cwd: str | None = None) -> Path:
    """Directory for the serialised knowledge graph."""
    return app_home(cwd) / "graph"


def knowledge_dir(cwd: str | None = None) -> Path:
    """Directory for generated knowledge Markdown files."""
    return app_home(cwd) / "knowledge"


def docs_dir(cwd: str | None = None) -> Path:
    """Directory for fetched framework documentation."""
    return app_home(cwd) / "docs"

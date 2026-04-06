"""
Graph persistence — save/load to .zwis/graph/graph.json.

Also maintains a metadata file (.zwis/graph/meta.json) that records:
  - when the graph was last built
  - per-file modification times (for incremental updates)
  - total node/edge counts
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import GraphEngine


# Default storage location inside the project workspace
_GRAPH_DIR = "graph"
_GRAPH_FILE = "graph.json"
_META_FILE = "meta.json"


def _graph_dir(app_home: Path) -> Path:
    return app_home / _GRAPH_DIR


def graph_path(app_home: Path) -> Path:
    return _graph_dir(app_home) / _GRAPH_FILE


def meta_path(app_home: Path) -> Path:
    return _graph_dir(app_home) / _META_FILE


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_graph(engine: GraphEngine, app_home: Path) -> None:
    """Persist the graph to disk, overwriting any previous file."""
    d = _graph_dir(app_home)
    d.mkdir(parents=True, exist_ok=True)

    data = engine.to_dict()
    graph_path(app_home).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_meta(meta: dict[str, Any], app_home: Path) -> None:
    """Persist graph metadata to disk."""
    d = _graph_dir(app_home)
    d.mkdir(parents=True, exist_ok=True)
    meta_path(app_home).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def load_graph(app_home: Path) -> GraphEngine | None:
    """
    Load graph from disk.

    Returns None if no graph file exists yet (i.e. `zwis learn` has not
    been run) rather than raising an exception.
    """
    p = graph_path(app_home)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return GraphEngine.from_dict(data)
    except Exception:
        return None


def load_meta(app_home: Path) -> dict[str, Any]:
    """Load metadata dict.  Returns empty dict if file doesn't exist."""
    p = meta_path(app_home)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def graph_exists(app_home: Path) -> bool:
    return graph_path(app_home).exists()


def make_meta(
    engine: GraphEngine,
    file_mtimes: dict[str, float],
    frameworks: list[str],
    cwd: str,
) -> dict[str, Any]:
    """Build a metadata dict from a freshly-built graph."""
    stats = engine.stats()
    return {
        "built_at": time.time(),
        "cwd": cwd,
        "frameworks": frameworks,
        "file_mtimes": file_mtimes,
        **stats,
    }


def stale_files(app_home: Path, current_mtimes: dict[str, float]) -> list[str]:
    """
    Compare stored mtimes against current ones.

    Returns a list of file paths whose mtime has changed since the
    last `learn` run — these files need to be re-parsed.
    """
    meta = load_meta(app_home)
    stored: dict[str, float] = meta.get("file_mtimes", {})
    stale: list[str] = []

    for fpath, mtime in current_mtimes.items():
        if fpath not in stored or stored[fpath] != mtime:
            stale.append(fpath)

    return stale

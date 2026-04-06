from __future__ import annotations

import json
import time
from pathlib import Path

from ..app_paths import legacy_sessions_dir, sessions_dir
from .models import SessionPayload, StoredSession


def _store_dir(cwd: str | None = None) -> Path:
    return sessions_dir(cwd)


def save_session(payload: SessionPayload, cwd: str | None = None) -> str:
    store = _store_dir(cwd)
    store.mkdir(parents=True, exist_ok=True)
    session_id = f"session-{int(time.time() * 1000)}"
    path = store / f"{session_id}.json"
    path.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "messages": payload.messages,
                "input_tokens": payload.input_tokens,
                "output_tokens": payload.output_tokens,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(path)


def load_session(session_id: str, cwd: str | None = None) -> StoredSession:
    path = _store_dir(cwd) / f"{session_id}.json"
    if not path.exists():
        path = legacy_sessions_dir(cwd) / f"{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")

    data = json.loads(path.read_text(encoding="utf-8"))
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError(f"Session file is invalid: {path}")

    return StoredSession(
        session_id=str(data.get("session_id", session_id)),
        messages=tuple(str(message) for message in messages),
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
    )


def list_sessions(cwd: str | None = None) -> list[dict]:
    """
    Return all saved sessions sorted by creation time (newest first).

    Each item: {"session_id": str, "path": Path, "timestamp": float, "message_count": int}
    """
    store = _store_dir(cwd)
    if not store.is_dir():
        return []

    sessions: list[dict] = []
    for json_file in store.glob("session-*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            ts = json_file.stat().st_mtime
            sessions.append({
                "session_id": str(data.get("session_id", json_file.stem)),
                "path": json_file,
                "timestamp": ts,
                "message_count": len(data.get("messages", [])),
                "input_tokens": int(data.get("input_tokens", 0)),
                "output_tokens": int(data.get("output_tokens", 0)),
            })
        except Exception:  # noqa: BLE001
            pass

    return sorted(sessions, key=lambda s: s["timestamp"], reverse=True)


def latest_session_id(cwd: str | None = None) -> str | None:
    """Return the most recent session ID, or None if no sessions exist."""
    sessions = list_sessions(cwd)
    return sessions[0]["session_id"] if sessions else None

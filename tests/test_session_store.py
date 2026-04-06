"""Tests for src/catalog/session_store — save/load/list sessions."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.catalog.models import SessionPayload, StoredSession
from src.catalog.session_store import (
    latest_session_id,
    list_sessions,
    load_session,
    save_session,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_store(tmp_path: Path) -> Path:
    store = tmp_path / ".zwis" / "sessions"
    store.mkdir(parents=True, exist_ok=True)
    return store


def _patch_store(tmp_path: Path):
    """Patch sessions_dir to return a tmp directory."""
    store = _make_store(tmp_path)
    return patch("src.catalog.session_store.sessions_dir", return_value=store)


def _make_payload(**kwargs) -> SessionPayload:
    return SessionPayload(
        messages=kwargs.get("messages", ["hello", "world"]),
        input_tokens=kwargs.get("input_tokens", 100),
        output_tokens=kwargs.get("output_tokens", 50),
    )


# ── save_session ──────────────────────────────────────────────────────────────

class TestSaveSession:
    def test_creates_json_file(self, tmp_path):
        with _patch_store(tmp_path):
            path = save_session(_make_payload(), cwd=str(tmp_path))
        assert Path(path).exists()
        assert path.endswith(".json")

    def test_saved_file_contains_session_id(self, tmp_path):
        with _patch_store(tmp_path):
            path = save_session(_make_payload(), cwd=str(tmp_path))
        data = json.loads(Path(path).read_text())
        assert "session_id" in data

    def test_saved_file_contains_messages(self, tmp_path):
        payload = _make_payload(messages=["msg-1", "msg-2"])
        with _patch_store(tmp_path):
            path = save_session(payload, cwd=str(tmp_path))
        data = json.loads(Path(path).read_text())
        assert data["messages"] == ["msg-1", "msg-2"]

    def test_saved_file_contains_token_counts(self, tmp_path):
        payload = _make_payload(input_tokens=123, output_tokens=456)
        with _patch_store(tmp_path):
            path = save_session(payload, cwd=str(tmp_path))
        data = json.loads(Path(path).read_text())
        assert data["input_tokens"] == 123
        assert data["output_tokens"] == 456

    def test_returns_path_string(self, tmp_path):
        with _patch_store(tmp_path):
            result = save_session(_make_payload(), cwd=str(tmp_path))
        assert isinstance(result, str)


# ── load_session ──────────────────────────────────────────────────────────────

class TestLoadSession:
    def _save_and_get_id(self, tmp_path: Path) -> tuple[str, str]:
        """Save a session and return (session_id, store_path_str)."""
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            path = save_session(_make_payload(), cwd=str(tmp_path))
        session_id = json.loads(Path(path).read_text())["session_id"]
        return session_id, str(store)

    def test_load_returns_stored_session(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            path = save_session(_make_payload(messages=["a", "b"]), cwd=str(tmp_path))
        session_id = json.loads(Path(path).read_text())["session_id"]
        with patch("src.catalog.session_store.sessions_dir", return_value=store), \
             patch("src.catalog.session_store.legacy_sessions_dir", return_value=tmp_path / "legacy"):
            result = load_session(session_id, cwd=str(tmp_path))
        assert isinstance(result, StoredSession)
        assert result.session_id == session_id

    def test_load_restores_messages(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            path = save_session(_make_payload(messages=["msg-A", "msg-B"]), cwd=str(tmp_path))
        session_id = json.loads(Path(path).read_text())["session_id"]
        with patch("src.catalog.session_store.sessions_dir", return_value=store), \
             patch("src.catalog.session_store.legacy_sessions_dir", return_value=tmp_path / "legacy"):
            result = load_session(session_id, cwd=str(tmp_path))
        assert "msg-A" in result.messages
        assert "msg-B" in result.messages

    def test_load_raises_for_unknown_session(self, tmp_path):
        store = _make_store(tmp_path)
        with pytest.raises(FileNotFoundError):
            with patch("src.catalog.session_store.sessions_dir", return_value=store), \
                 patch("src.catalog.session_store.legacy_sessions_dir", return_value=tmp_path / "legacy"):
                load_session("session-999999", cwd=str(tmp_path))

    def test_load_restores_token_counts(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            path = save_session(_make_payload(input_tokens=77, output_tokens=33), cwd=str(tmp_path))
        session_id = json.loads(Path(path).read_text())["session_id"]
        with patch("src.catalog.session_store.sessions_dir", return_value=store), \
             patch("src.catalog.session_store.legacy_sessions_dir", return_value=tmp_path / "legacy"):
            result = load_session(session_id, cwd=str(tmp_path))
        assert result.input_tokens == 77
        assert result.output_tokens == 33


# ── list_sessions ─────────────────────────────────────────────────────────────

class TestListSessions:
    def test_returns_empty_when_no_store(self, tmp_path):
        non_existent = tmp_path / "no-sessions"
        with patch("src.catalog.session_store.sessions_dir", return_value=non_existent):
            result = list_sessions(cwd=str(tmp_path))
        assert result == []

    def test_returns_sessions_sorted_newest_first(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            # Create two sessions with a small gap
            path1 = save_session(_make_payload(messages=["first"]), cwd=str(tmp_path))
            time.sleep(0.01)
            path2 = save_session(_make_payload(messages=["second"]), cwd=str(tmp_path))

        id1 = json.loads(Path(path1).read_text())["session_id"]
        id2 = json.loads(Path(path2).read_text())["session_id"]

        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            sessions = list_sessions(cwd=str(tmp_path))

        assert len(sessions) == 2
        # Newest first
        assert sessions[0]["session_id"] == id2

    def test_each_entry_has_expected_keys(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            save_session(_make_payload(), cwd=str(tmp_path))
            sessions = list_sessions(cwd=str(tmp_path))

        assert len(sessions) == 1
        entry = sessions[0]
        assert "session_id" in entry
        assert "timestamp" in entry
        assert "message_count" in entry

    def test_message_count_correct(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            save_session(_make_payload(messages=["a", "b", "c"]), cwd=str(tmp_path))
            sessions = list_sessions(cwd=str(tmp_path))
        assert sessions[0]["message_count"] == 3


# ── latest_session_id ─────────────────────────────────────────────────────────

class TestLatestSessionId:
    def test_returns_none_when_no_sessions(self, tmp_path):
        store = tmp_path / "empty-store"
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            result = latest_session_id(cwd=str(tmp_path))
        assert result is None

    def test_returns_most_recent_session_id(self, tmp_path):
        store = _make_store(tmp_path)
        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            save_session(_make_payload(messages=["old"]), cwd=str(tmp_path))
            time.sleep(0.01)
            path2 = save_session(_make_payload(messages=["new"]), cwd=str(tmp_path))
        id2 = json.loads(Path(path2).read_text())["session_id"]

        with patch("src.catalog.session_store.sessions_dir", return_value=store):
            result = latest_session_id(cwd=str(tmp_path))
        assert result == id2

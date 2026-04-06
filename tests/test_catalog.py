"""
Tests for src/catalog — catalog loading, routing, session store, manifest, parity.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.catalog import (
    PortRuntime,
    QueryEnginePort,
    build_port_manifest,
    command_entries,
    execute_command,
    execute_tool,
    find_commands,
    find_tools,
    get_command,
    get_commands,
    get_tool,
    get_tools,
    load_session,
    render_command_index,
    render_tool_index,
    run_parity_audit,
    save_session,
)
from src.catalog.models import (
    CatalogEntry,
    RoutedMatch,
    RuntimeSession,
    SessionPayload,
    StoredSession,
)
from src.permissions import ToolPermissionContext


# ── catalog loading ───────────────────────────────────────────────────────────

class TestCatalogEntries:
    def test_command_entries_loaded(self):
        entries = command_entries()
        assert len(entries) >= 20

    def test_tool_entries_loaded(self):
        entries = tool_entries()
        assert len(entries) >= 10

    def test_all_entries_have_required_fields(self):
        for entry in command_entries():
            assert entry.name
            assert entry.source_hint
            assert entry.responsibility

    def test_get_command_returns_entry(self):
        entry = get_command("summary")
        assert entry is not None
        assert entry.name == "summary"

    def test_get_game_command_returns_entry(self):
        entry = get_command("game")
        assert entry is not None
        assert entry.source_hint == "main:game"

    def test_get_command_is_case_insensitive(self):
        entry = get_command("SUMMARY")
        assert entry is not None

    def test_get_command_missing_returns_none(self):
        assert get_command("absolutely_not_a_command_xyz") is None

    def test_get_tool_returns_entry(self):
        entry = get_tool("BashTool")
        assert entry is not None

    def test_get_tool_missing_returns_none(self):
        assert get_tool("NonExistentTool123") is None

    def test_find_commands_by_substring(self):
        results = find_commands("tool", limit=10)
        assert len(results) >= 1
        assert all("tool" in r.name.lower() or "tool" in r.responsibility.lower() for r in results)

    def test_find_commands_finds_flappy_bird(self):
        results = find_commands("flappy", limit=10)
        assert any(r.name == "game/flappy-bird" for r in results)

    def test_find_tools_by_substring(self):
        results = find_tools("File", limit=5)
        assert len(results) >= 1

    def test_get_commands_filters_plugin(self):
        all_cmds = get_commands(include_plugin_commands=True)
        filtered = get_commands(include_plugin_commands=False)
        # filtered should be a subset
        assert len(filtered) <= len(all_cmds)

    def test_get_tools_simple_mode(self):
        simple = get_tools(simple_mode=True)
        allowed = {"BashTool", "FileReadTool", "FileEditTool"}
        for t in simple:
            assert t.name in allowed

    def test_get_tools_permission_context_excludes(self):
        perm = ToolPermissionContext.from_iterables(["BashTool"], [])
        filtered = get_tools(permission_context=perm)
        names = [t.name for t in filtered]
        assert "BashTool" not in names

    def test_get_tools_excludes_mcp_when_flag_false(self):
        all_tools = get_tools(include_mcp=True)
        no_mcp = get_tools(include_mcp=False)
        for t in no_mcp:
            assert "mcp" not in t.name.lower() and "mcp" not in t.source_hint.lower()


def tool_entries():
    from src.catalog.catalog import tool_entries as _te
    return _te()


# ── execution stubs ───────────────────────────────────────────────────────────

class TestExecutionStubs:
    def test_execute_known_command_succeeds(self):
        result = execute_command("summary", "test prompt")
        assert result.handled
        assert "summary" in result.message.lower()

    def test_execute_unknown_command_fails(self):
        result = execute_command("not_a_real_command_xyz", "prompt")
        assert not result.handled

    def test_execute_known_tool_succeeds(self):
        result = execute_tool("BashTool", '{"command": "echo hi"}')
        assert result.handled

    def test_execute_unknown_tool_fails(self):
        result = execute_tool("GhostTool", "{}")
        assert not result.handled


# ── render index ──────────────────────────────────────────────────────────────

class TestRenderIndex:
    def test_render_command_index_default(self):
        output = render_command_index(limit=5)
        assert "Command entries:" in output

    def test_render_command_index_with_query(self):
        output = render_command_index(limit=5, query="summary")
        assert "summary" in output.lower()

    def test_render_tool_index_default(self):
        output = render_tool_index(limit=5)
        assert "Tool entries:" in output


# ── session store ─────────────────────────────────────────────────────────────

class TestSessionStore:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        payload = SessionPayload(messages=["hello", "world"], input_tokens=5, output_tokens=3)
        path = save_session(payload)

        assert Path(path).exists()
        session_id = Path(path).stem
        loaded = load_session(session_id)

        assert loaded.session_id == session_id
        assert "hello" in loaded.messages
        assert "world" in loaded.messages
        assert loaded.input_tokens == 5
        assert loaded.output_tokens == 3

    def test_load_nonexistent_session_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="Session not found"):
            load_session("does-not-exist")

    def test_save_creates_port_sessions_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        payload = SessionPayload(messages=["x"], input_tokens=1, output_tokens=1)
        save_session(payload)
        assert (tmp_path / ".zwis" / "sessions").is_dir()

    def test_saved_file_is_valid_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        payload = SessionPayload(messages=["test"], input_tokens=1, output_tokens=1)
        path = save_session(payload)
        data = json.loads(Path(path).read_text())
        assert "session_id" in data
        assert "messages" in data

    def test_load_session_uses_legacy_port_sessions_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        legacy_dir = tmp_path / ".port_sessions"
        legacy_dir.mkdir()
        session_id = "session-legacy"
        (legacy_dir / f"{session_id}.json").write_text(json.dumps({
            "session_id": session_id,
            "messages": ["hello"],
            "input_tokens": 1,
            "output_tokens": 2,
        }))

        loaded = load_session(session_id)

        assert loaded.session_id == session_id
        assert loaded.messages == ("hello",)


# ── runtime routing ───────────────────────────────────────────────────────────

class TestPortRuntime:
    def test_route_prompt_returns_matches(self):
        rt = PortRuntime()
        matches = rt.route_prompt("bash tool")
        assert len(matches) >= 1

    def test_route_prompt_scores_descending(self):
        rt = PortRuntime()
        matches = rt.route_prompt("bash tool", limit=10)
        scores = [m.score for m in matches]
        assert scores == sorted(scores, reverse=True)

    def test_route_prompt_limit_respected(self):
        rt = PortRuntime()
        matches = rt.route_prompt("tool", limit=3)
        assert len(matches) <= 3

    def test_route_prompt_empty_returns_empty(self):
        rt = PortRuntime()
        matches = rt.route_prompt("xyzzy_no_match_possible_zzzz")
        assert matches == []

    def test_bootstrap_session_returns_runtime_session(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rt = PortRuntime()
        session = rt.bootstrap_session("list tools", limit=3)
        assert isinstance(session, RuntimeSession)
        assert session.prompt == "list tools"
        assert "Runtime Session" in session.as_markdown()

    def test_bootstrap_session_persists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rt = PortRuntime()
        session = rt.bootstrap_session("test", limit=2)
        assert Path(session.persisted_session_path).exists()

    def test_run_turn_loop_returns_all_turns(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        rt = PortRuntime()
        outputs = rt.run_turn_loop("route tools", max_turns=3)
        assert len(outputs) == 3
        for i, output in enumerate(outputs, 1):
            assert f"Turn {i}" in output


# ── query engine ──────────────────────────────────────────────────────────────

class TestQueryEnginePort:
    def test_render_summary_includes_heading(self):
        engine = QueryEnginePort.from_workspace()
        summary = engine.render_summary()
        assert "Zwischenzug Workspace Summary" in summary

    def test_render_summary_includes_counts(self):
        engine = QueryEnginePort.from_workspace()
        summary = engine.render_summary()
        assert "Command surface:" in summary
        assert "Tool surface:" in summary

    def test_submit_message_returns_turn_result(self):
        engine = QueryEnginePort.from_workspace()
        result = engine.submit_message("hello", matched_commands=("summary",), matched_tools=("BashTool",))
        assert result.output
        assert result.stop_reason == "completed"
        assert "summary" in result.matched_commands
        assert "BashTool" in result.matched_tools


# ── manifest ──────────────────────────────────────────────────────────────────

class TestManifest:
    def test_manifest_has_files(self):
        manifest = build_port_manifest()
        assert manifest.total_python_files >= 10

    def test_manifest_has_modules(self):
        manifest = build_port_manifest()
        assert len(manifest.top_level_modules) >= 5

    def test_manifest_to_markdown(self):
        manifest = build_port_manifest()
        md = manifest.to_markdown()
        assert "Total Python files" in md
        assert "src" in md.lower()

    def test_manifest_includes_sub_packages(self):
        manifest = build_port_manifest()
        names = {m.name for m in manifest.top_level_modules}
        assert "tools" in names or "core" in names


# ── parity audit ─────────────────────────────────────────────────────────────

class TestParityAudit:
    def test_command_ratio_covers_all(self):
        result = run_parity_audit()
        actual, total = result.command_entry_ratio
        assert actual >= 20
        assert total >= 20

    def test_tool_ratio_covers_all(self):
        result = run_parity_audit()
        actual, total = result.tool_entry_ratio
        assert actual >= 10

    def test_to_markdown_contains_heading(self):
        result = run_parity_audit()
        md = result.to_markdown()
        assert "Parity Audit" in md
        assert "Command entry coverage" in md
        assert "Tool entry coverage" in md

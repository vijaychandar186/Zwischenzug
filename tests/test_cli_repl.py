"""
Tests for src/cli/repl — run_single (non-interactive mode).
The REPL itself is tested via subprocess to avoid stdin/stdout complexity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from src.cli.repl import _handle_slash, _make_event_callback, _path_completion_options, run_single
from src.core.agent import TextDelta, UsageUpdate
from src.core.session import SessionConfig, SessionState
from src.games.flappy_bird import FlappyConfig, FlappyGame, PipeState
from tests.conftest import make_text_llm, make_tool_then_text_llm


class TestRunSingle:
    """Tests for the synchronous run_single entrypoint.

    run_single uses asyncio.run() internally, so tests must be plain
    synchronous functions (not pytest.mark.asyncio) to avoid the
    "cannot be called from a running event loop" conflict.
    """

    def test_returns_zero_on_success(self, tmp_path):
        cfg = SessionConfig(model="test")
        llm = make_text_llm("The answer is 42.")
        code = run_single("what is 42?", cfg, llm, output_format="text", cwd=str(tmp_path))
        assert code == 0

    def test_text_output_printed(self, tmp_path, capsys):
        cfg = SessionConfig(model="test")
        llm = make_text_llm("Hello from the model!")
        run_single("hello", cfg, llm, output_format="text", cwd=str(tmp_path))
        captured = capsys.readouterr()
        assert "Hello from the model!" in captured.out

    def test_json_output_is_valid_json(self, tmp_path, capsys):
        cfg = SessionConfig(model="test")
        llm = make_text_llm("JSON response here.")
        run_single("test", cfg, llm, output_format="json", cwd=str(tmp_path))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "text" in data
        assert "session_id" in data
        assert "input_tokens" in data
        assert "output_tokens" in data

    def test_json_output_contains_response_text(self, tmp_path, capsys):
        cfg = SessionConfig(model="test")
        llm = make_text_llm("specific answer text")
        run_single("q", cfg, llm, output_format="json", cwd=str(tmp_path))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "specific answer text" in data["text"]

    def test_tool_calls_included_in_json(self, tmp_path, capsys):
        cfg = SessionConfig(model="test", permission_mode="auto")
        llm = make_tool_then_text_llm("bash", {"command": "echo tool_output"})
        run_single("run bash", cfg, llm, output_format="json", cwd=str(tmp_path))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "tool_events" in data
        assert len(data["tool_events"]) == 1
        assert data["tool_events"][0]["content"]

    def test_tool_denied_in_deny_mode(self, tmp_path, capsys):
        cfg = SessionConfig(model="test", permission_mode="deny")
        llm = make_tool_then_text_llm("bash", {"command": "echo secret"})
        code = run_single("run bash", cfg, llm, output_format="json", cwd=str(tmp_path))
        assert code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["tool_events"][0]["is_error"]

    def test_uses_provided_cwd(self, tmp_path, capsys):
        (tmp_path / "marker.txt").write_text("exists")
        cfg = SessionConfig(model="test")
        llm = make_tool_then_text_llm("bash", {"command": "ls"})
        run_single("list files", cfg, llm, output_format="json", cwd=str(tmp_path))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        # tool result content should contain the ls output (marker.txt)
        assert any("marker.txt" in e["content"] for e in data["tool_events"])

    def test_event_callback_stops_status_on_first_visible_event(self):
        stopped = 0

        def stop_status():
            nonlocal stopped
            stopped += 1

        acc: list[str] = []
        on_event = _make_event_callback(acc, stop_status=stop_status)

        on_event(UsageUpdate(input_tokens=1, output_tokens=1))
        assert stopped == 0

        on_event(TextDelta(text="Hello"))
        assert stopped == 1
        assert acc == ["Hello"]


class TestCLIIntegration:
    """Subprocess-level tests for the zwischenzug CLI."""

    def _run(self, *args: str, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "src.main", *args],
            capture_output=True, text=True, **kwargs
        )

    def test_help_output_shows_zwischenzug(self):
        result = self._run("--help")
        assert "zwischenzug" in result.stdout.lower()

    def test_summary_command(self):
        result = self._run("summary", check=True)
        assert "Zwischenzug Workspace Summary" in result.stdout

    def test_commands_command(self):
        result = self._run("commands", "--limit", "3", check=True)
        assert "Command entries:" in result.stdout

    def test_tools_command(self):
        result = self._run("tools", "--limit", "3", check=True)
        assert "Tool entries:" in result.stdout

    def test_mcp_list_command(self):
        result = self._run("mcp", "list", check=True)
        assert result.returncode == 0
        assert result.stdout.strip()
        assert (
            "No MCP servers configured." in result.stdout
            or "\t" in result.stdout
            or "http" in result.stdout
            or "stdio" in result.stdout
        )

    def test_completion_command_outputs_bash_script(self):
        result = self._run("completion", "bash", check=True)
        assert "_zwis_completion()" in result.stdout
        assert "complete -o bashdefault -o default -F _zwis_completion zwis" in result.stdout
        assert "game" in result.stdout

    def test_route_command(self):
        result = self._run("route", "bash tool", check=True)
        assert result.returncode == 0

    def test_parity_audit_command(self):
        result = self._run("parity-audit", check=True)
        assert "Parity Audit" in result.stdout

    def test_manifest_command(self):
        result = self._run("manifest", check=True)
        assert "Total Python files" in result.stdout

    def test_remote_mode_command(self):
        result = self._run("remote-mode", "host1", check=True)
        assert "mode=remote" in result.stdout

    def test_ssh_mode_command(self):
        result = self._run("ssh-mode", "host2", check=True)
        assert "mode=ssh" in result.stdout

    def test_load_session_missing_exits_nonzero(self):
        result = self._run("load-session", "ghost-session-id")
        assert result.returncode != 0
        assert "Session not found" in result.stdout

    def test_show_command_known(self):
        result = self._run("show-command", "summary", check=True)
        assert "summary" in result.stdout.lower()

    def test_show_command_unknown_exits_nonzero(self):
        result = self._run("show-command", "zzz_not_real")
        assert result.returncode != 0
        assert "not found" in result.stdout.lower()

    def test_show_tool_known(self):
        result = self._run("show-tool", "BashTool", check=True)
        assert result.returncode == 0

    def test_exec_command_known(self):
        result = self._run("exec-command", "summary", "test prompt", check=True)
        assert result.returncode == 0

    def test_exec_tool_unknown_exits_nonzero(self):
        result = self._run("exec-tool", "GhostTool", "{}")
        assert result.returncode != 0

    def test_game_command_runs_flappy_bird_smoke(self, tmp_path):
        env = os.environ.copy()
        env["ZWISCHENZUG_HOME"] = str(tmp_path / ".zwis-home")
        result = self._run("game", "flappy-bird", "--max-frames", "2", check=True, env=env)
        assert result.returncode == 0
        assert (tmp_path / ".zwis-home" / "games" / "flappy_bird.json").exists()


class TestCompletionHelpers:
    def test_path_completion_options_for_skill_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "skills").mkdir()
        (tmp_path / "src" / "alpha.py").write_text("print('x')\n")

        options = _path_completion_options("/graph-review src/a", "src/a")
        assert "src/alpha.py" in options

    def test_path_completion_options_ignores_non_file_commands(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "alpha.py").write_text("print('x')\n")

        options = _path_completion_options("/help src/a", "src/a")
        assert options == []


class TestSlashCommands:
    def test_game_slash_command_launches_flappy_bird(self, tmp_path, monkeypatch):
        calls: list[str] = []

        def fake_run_flappy_bird(*, cwd=None, console=None, **kwargs):
            calls.append(cwd)

        monkeypatch.setattr("src.games.run_flappy_bird", fake_run_flappy_bird)
        session = SessionState.new(SessionConfig(model="test"), cwd=str(tmp_path))

        handled = _handle_slash(
            "/game/flappy-bird",
            session,
            registry=None,
            skill_registry=None,
            memory_manager=None,
            agent_config=None,
            provider="test",
        )

        assert handled is True
        assert calls == [str(tmp_path)]


class TestFlappyBird:
    def test_game_scores_when_bird_passes_pipe(self):
        game = FlappyGame(config=FlappyConfig())
        game.pipes = [PipeState(x=game.bird.x - game.config.pipe_width - 1, gap_y=6, scored=False)]

        game.step(flap=False)

        assert game.score == 1

    def test_game_crashes_when_pipe_blocks_gap(self):
        game = FlappyGame(config=FlappyConfig())
        game.bird.y = 1
        game.pipes = [PipeState(x=game.bird.x, gap_y=10, scored=False)]

        game.step(flap=False)

        assert game.crashed is True

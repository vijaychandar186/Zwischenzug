"""Tests for src/hooks — HookRunner, HookEvent, settings loading."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.hooks import HookDef, HookEntry, HookEvent, HookRunner, _matches


# ── _matches helper ───────────────────────────────────────────────────────────

class TestMatchesHelper:
    def test_wildcard_matches_everything(self):
        assert _matches("*", "bash")
        assert _matches("*", "any_tool")

    def test_empty_string_matches_everything(self):
        assert _matches("", "bash")

    def test_exact_match(self):
        assert _matches("bash", "bash")

    def test_case_insensitive(self):
        assert _matches("Bash", "bash")
        assert _matches("bash", "BASH")

    def test_no_match(self):
        assert not _matches("bash", "grep")


# ── HookEvent ─────────────────────────────────────────────────────────────────

class TestHookEvent:
    def test_pre_tool_use_value(self):
        assert HookEvent.PRE_TOOL_USE == "PreToolUse"

    def test_post_tool_use_value(self):
        assert HookEvent.POST_TOOL_USE == "PostToolUse"

    def test_is_string_enum(self):
        assert isinstance(HookEvent.PRE_QUERY, str)

    def test_has_session_events(self):
        assert HookEvent.SESSION_START == "SessionStart"
        assert HookEvent.SESSION_END == "SessionEnd"


# ── HookRunner construction ───────────────────────────────────────────────────

class TestHookRunnerConstruction:
    def test_empty_runner_has_no_hooks(self):
        runner = HookRunner.empty()
        assert not runner.has_hooks(HookEvent.PRE_TOOL_USE)

    def test_from_settings_loads_hooks(self, tmp_path):
        settings = tmp_path / ".zwis" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "bash", "hooks": [{"type": "command", "command": "echo hi"}]}
                ]
            }
        }))
        with patch("src.app_paths.app_home", return_value=tmp_path / ".zwis"):
            runner = HookRunner.from_settings(cwd=str(tmp_path))
        assert runner.has_hooks(HookEvent.PRE_TOOL_USE)

    def test_from_settings_ignores_missing_files(self, tmp_path):
        # No settings files → empty runner
        runner = HookRunner.from_settings(cwd=str(tmp_path))
        assert not runner.has_hooks(HookEvent.PRE_TOOL_USE)

    def test_from_settings_ignores_invalid_json(self, tmp_path):
        settings = tmp_path / ".zwis" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text("NOT VALID JSON {{{")
        # Should not raise
        runner = HookRunner.from_settings(cwd=str(tmp_path))
        assert not runner.has_hooks(HookEvent.PRE_TOOL_USE)

    def test_from_settings_skips_hooks_without_command(self, tmp_path):
        settings = tmp_path / ".zwis" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({
            "hooks": {
                "PreToolUse": [
                    {"matcher": "*", "hooks": [{"type": "command", "command": ""}]}
                ]
            }
        }))
        runner = HookRunner.from_settings(cwd=str(tmp_path))
        assert not runner.has_hooks(HookEvent.PRE_TOOL_USE)


# ── HookRunner.run ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHookRunnerRun:
    async def test_no_hooks_returns_true(self, tmp_path):
        runner = HookRunner.empty()
        result = await runner.run(HookEvent.PRE_TOOL_USE, matcher="bash", cwd=str(tmp_path))
        assert result is True

    async def test_successful_pre_hook_returns_true(self, tmp_path):
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command="exit 0")],
                )
            ]
        })
        result = await runner.run(HookEvent.PRE_TOOL_USE, cwd=str(tmp_path))
        assert result is True

    async def test_failing_pre_hook_returns_false(self, tmp_path):
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command="exit 1")],
                )
            ]
        })
        result = await runner.run(HookEvent.PRE_TOOL_USE, cwd=str(tmp_path))
        assert result is False

    async def test_failing_post_hook_returns_true(self, tmp_path):
        """Post-hooks never block — always return True regardless of exit code."""
        runner = HookRunner(_hooks={
            "PostToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command="exit 1")],
                )
            ]
        })
        result = await runner.run(HookEvent.POST_TOOL_USE, cwd=str(tmp_path))
        assert result is True

    async def test_matcher_filters_hooks(self, tmp_path):
        """Hook with matcher='bash' should not trigger for tool 'grep'."""
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="bash",
                    hooks=[HookDef(command="exit 1")],  # would block if run
                )
            ]
        })
        result = await runner.run(HookEvent.PRE_TOOL_USE, matcher="grep", cwd=str(tmp_path))
        assert result is True  # bash hook didn't match grep

    async def test_wildcard_matcher_matches_all(self, tmp_path):
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command="exit 1")],
                )
            ]
        })
        result = await runner.run(HookEvent.PRE_TOOL_USE, matcher="any_tool", cwd=str(tmp_path))
        assert result is False

    async def test_env_extra_passed_to_hook(self, tmp_path):
        """Verify env vars can be injected (smoke test — hook uses env)."""
        out_file = tmp_path / "env_value.txt"
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command=f"echo $MY_TEST_VAR > {out_file}")],
                )
            ]
        })
        await runner.run(
            HookEvent.PRE_TOOL_USE,
            env_extra={"MY_TEST_VAR": "hello"},
            cwd=str(tmp_path),
        )
        assert "hello" in out_file.read_text()

    async def test_timed_out_hook_does_not_block(self, tmp_path):
        """A hook that times out should not block (return True)."""
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command="sleep 60", timeout=0.05)],
                )
            ]
        })
        result = await runner.run(HookEvent.PRE_TOOL_USE, cwd=str(tmp_path))
        assert result is True

    async def test_has_hooks_false_for_unregistered_event(self):
        runner = HookRunner.empty()
        assert not runner.has_hooks(HookEvent.SESSION_END)

    async def test_string_event_name_works(self, tmp_path):
        runner = HookRunner(_hooks={
            "PreToolUse": [
                HookEntry(
                    matcher="*",
                    hooks=[HookDef(command="exit 0")],
                )
            ]
        })
        result = await runner.run("PreToolUse", cwd=str(tmp_path))
        assert result is True

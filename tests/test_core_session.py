"""
Tests for src/core/session — SessionState, SessionConfig, compaction.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.compact import TokenBudget
from src.core.session import SessionConfig, SessionState


class TestSessionConfig:
    def test_default_values(self):
        cfg = SessionConfig()
        assert cfg.max_turns == 50
        assert cfg.permission_mode == "auto"
        assert cfg.system_prompt == ""

    def test_default_factory(self):
        cfg = SessionConfig.default()
        assert isinstance(cfg, SessionConfig)
        assert cfg.model == ""


class TestSessionState:
    def test_new_has_unique_id(self, tmp_path):
        cfg = SessionConfig(model="m")
        s1 = SessionState.new(cfg, cwd=str(tmp_path))
        s2 = SessionState.new(cfg, cwd=str(tmp_path))
        assert s1.id != s2.id

    def test_new_with_system_prompt_prepends_system_message(self, tmp_path):
        cfg = SessionConfig(system_prompt="You are helpful.")
        state = SessionState.new(cfg, cwd=str(tmp_path))
        assert len(state.messages) == 1
        assert isinstance(state.messages[0], SystemMessage)
        assert state.messages[0].content == "You are helpful."

    def test_new_without_system_prompt_has_empty_messages(self, tmp_path):
        cfg = SessionConfig()
        state = SessionState.new(cfg, cwd=str(tmp_path))
        assert state.messages == []

    def test_push_human_appends_human_message(self, session):
        session.push_human("hello")
        assert len(session.messages) == 1
        assert isinstance(session.messages[0], HumanMessage)
        assert session.messages[0].content == "hello"

    def test_push_appends_any_message(self, session):
        msg = AIMessage(content="reply")
        session.push(msg)
        assert session.messages[-1] is msg

    def test_push_system_inserts_at_front(self, session):
        session.push_human("first human")
        session.push_system("system prompt")
        assert isinstance(session.messages[0], SystemMessage)
        assert session.messages[0].content == "system prompt"

    def test_push_system_updates_existing_system_message(self, tmp_path):
        cfg = SessionConfig(system_prompt="original")
        state = SessionState.new(cfg, cwd=str(tmp_path))
        state.push_system("updated")
        system_msgs = [m for m in state.messages if isinstance(m, SystemMessage)]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "updated"

    def test_turn_count_starts_at_zero(self, session):
        assert session.turn_count == 0

    def test_token_counters_start_at_zero(self, session):
        assert session.total_input_tokens == 0
        assert session.total_output_tokens == 0
        assert session.last_input_tokens == 0

    def test_to_dict_contains_required_keys(self, session):
        session.push_human("hi")
        d = session.to_dict()
        assert "session_id" in d
        assert "messages" in d
        assert "turn_count" in d
        assert "total_input_tokens" in d
        assert "total_output_tokens" in d
        assert "config" in d
        assert "created_at" in d

    def test_to_dict_session_id_matches(self, session):
        d = session.to_dict()
        assert d["session_id"] == session.id

    def test_to_dict_messages_are_serializable(self, session):
        import json
        session.push_human("hello")
        session.push(AIMessage(content="world"))
        d = session.to_dict()
        # Must not raise
        json.dumps(d)

    def test_ai_tool_calls_round_trip_through_serialization(self, tmp_path):
        cfg = SessionConfig(model="m")
        state = SessionState.new(cfg, cwd=str(tmp_path))
        state.push(
            AIMessage(
                content="Calling a tool",
                tool_calls=[{"id": "call-1", "name": "bash", "args": {"command": "echo hi"}}],
            )
        )

        restored = SessionState.from_dict(state.to_dict())

        ai_msgs = [m for m in restored.messages if isinstance(m, AIMessage)]
        assert len(ai_msgs) == 1
        assert ai_msgs[0].tool_calls[0]["id"] == "call-1"
        assert ai_msgs[0].tool_calls[0]["name"] == "bash"
        assert ai_msgs[0].tool_calls[0]["args"] == {"command": "echo hi"}

    def test_compact_removes_old_messages(self, tmp_path):
        cfg = SessionConfig(
            token_budget=TokenBudget(context_window=1_000, max_output_tokens=100),
        )
        state = SessionState.new(cfg, cwd=str(tmp_path))
        for i in range(20):
            state.push_human(f"msg {i}")
        state.last_input_tokens = 900
        removed = state.compact()
        assert removed > 0
        assert len(state.messages) < 20

    def test_compact_keeps_at_least_two_messages(self, tmp_path):
        cfg = SessionConfig(
            token_budget=TokenBudget(context_window=1_000, max_output_tokens=100),
        )
        state = SessionState.new(cfg, cwd=str(tmp_path))
        state.push_human("a")
        state.push(AIMessage(content="b"))
        state.last_input_tokens = 999
        removed = state.compact()
        assert removed == 0
        assert len(state.messages) == 2

    def test_compact_preserves_system_message(self, tmp_path):
        cfg = SessionConfig(
            system_prompt="Be helpful",
            token_budget=TokenBudget(context_window=1_000, max_output_tokens=100),
        )
        state = SessionState.new(cfg, cwd=str(tmp_path))
        for i in range(20):
            state.push_human(f"msg {i}")
        state.last_input_tokens = 900
        state.compact()
        assert isinstance(state.messages[0], SystemMessage)

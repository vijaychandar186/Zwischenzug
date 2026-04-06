"""
Tests for src/core/agent — the multi-turn agent loop.

Uses mock LLMs to exercise the loop without real API calls.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.core.agent import (
    TextDelta,
    ToolResultEvent,
    ToolUseStart,
    TurnComplete,
    UsageUpdate,
    _classify_error,
    _ErrorClass,
    _load_project_memory,
    run_agent,
)
from src.core.session import SessionConfig, SessionState
from src.tools import PermissionMode, ToolOrchestrator, ToolRegistry, default_registry
from tests.conftest import make_text_llm, make_tool_then_text_llm, _make_astream


# ── error classification ──────────────────────────────────────────────────────

class TestErrorClassification:
    def test_context_too_long(self):
        assert _classify_error(Exception("context_too_long")) == _ErrorClass.CONTEXT_TOO_LONG

    def test_context_window(self):
        assert _classify_error(Exception("context window exceeded")) == _ErrorClass.CONTEXT_TOO_LONG

    def test_request_too_large_413_is_context_too_long(self):
        err = Exception(
            "Error code: 413 - {'error': {'message': 'Request too large for model "
            "`openai/gpt-oss-120b` on TPM: Limit 8000, Requested 10528', "
            "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )
        assert _classify_error(err) == _ErrorClass.CONTEXT_TOO_LONG

    def test_rate_limit_429(self):
        assert _classify_error(Exception("429 rate limit exceeded")) == _ErrorClass.RATE_LIMIT

    def test_rate_limit_text(self):
        assert _classify_error(Exception("rate_limit hit")) == _ErrorClass.RATE_LIMIT

    def test_server_error_500(self):
        assert _classify_error(Exception("500 internal server error")) == _ErrorClass.SERVER_ERROR

    def test_server_error_503(self):
        assert _classify_error(Exception("503 service unavailable")) == _ErrorClass.SERVER_ERROR

    def test_unretryable(self):
        assert _classify_error(Exception("invalid api key")) == _ErrorClass.UNRETRYABLE

    def test_unretryable_generic(self):
        assert _classify_error(ValueError("some random error")) == _ErrorClass.UNRETRYABLE


# ── project memory ────────────────────────────────────────────────────────────

class TestProjectMemory:
    def test_loads_zwischenzug_md(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("# Project rules")
        result = _load_project_memory(str(tmp_path))
        assert result == "# Project rules"

    def test_loads_dot_zwischenzug_as_fallback(self, tmp_path):
        (tmp_path / ".zwischenzug").write_text("Project memory")
        result = _load_project_memory(str(tmp_path))
        assert result == "Project memory"

    def test_prefers_zwischenzug_md_over_dot_zwischenzug(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("zwischenzug content")
        (tmp_path / ".zwischenzug").write_text("fallback content")
        result = _load_project_memory(str(tmp_path))
        assert result == "zwischenzug content"

    def test_returns_none_when_no_files(self, tmp_path):
        assert _load_project_memory(str(tmp_path)) is None

    def test_returns_none_for_empty_file(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("  \n  ")
        assert _load_project_memory(str(tmp_path)) is None


# ── agent loop ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAgentLoop:
    async def test_simple_text_response_ends_loop(self, session, registry, orchestrator):
        llm = make_text_llm("Hello, I can help with that.")
        session.push_human("Hello")

        events = []
        await run_agent(session, llm, registry, orchestrator, on_event=events.append)

        text_events = [e for e in events if isinstance(e, TextDelta)]
        assert any("Hello" in e.text for e in text_events)
        complete_events = [e for e in events if isinstance(e, TurnComplete)]
        assert len(complete_events) == 1

    async def test_list_text_blocks_are_emitted(self, session, registry, orchestrator):
        response = AIMessage(content=[
            {"type": "text", "text": "Hello!"},
            {"type": "text", "text": " How can I help?"},
        ])
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        from unittest.mock import AsyncMock, MagicMock

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        llm.ainvoke = AsyncMock(return_value=response)
        llm.astream = _make_astream(response)

        session.push_human("Hello")
        events = []
        await run_agent(session, llm, registry, orchestrator, on_event=events.append)

        text_events = [e for e in events if isinstance(e, TextDelta)]
        assert len(text_events) == 1
        assert text_events[0].text == "Hello! How can I help?"

    async def test_token_usage_is_tracked(self, session, registry, orchestrator):
        llm = make_text_llm("Done.")
        session.push_human("count tokens")

        await run_agent(session, llm, registry, orchestrator)

        assert session.total_input_tokens > 0
        assert session.total_output_tokens > 0

    async def test_turn_count_increments(self, session, registry, orchestrator):
        llm = make_text_llm("Done.")
        session.push_human("hi")

        assert session.turn_count == 0
        await run_agent(session, llm, registry, orchestrator)
        assert session.turn_count == 1

    async def test_assistant_message_added_to_history(self, session, registry, orchestrator):
        llm = make_text_llm("My response.")
        session.push_human("question")

        await run_agent(session, llm, registry, orchestrator)

        ai_msgs = [m for m in session.messages if isinstance(m, AIMessage)]
        assert len(ai_msgs) == 1

    async def test_reasoning_blocks_are_normalized_before_history_replay(self, session, registry, orchestrator):
        response = AIMessage(content=[
            {"type": "reasoning", "thinking": "hidden"},
            {"type": "text", "text": "Visible answer."},
        ])
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 5}

        from unittest.mock import AsyncMock, MagicMock

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        llm.ainvoke = AsyncMock(return_value=response)
        llm.astream = _make_astream(response)

        session.push_human("hi")
        await run_agent(session, llm, registry, orchestrator)

        ai_msgs = [m for m in session.messages if isinstance(m, AIMessage)]
        assert len(ai_msgs) == 1
        assert ai_msgs[0].content == "Visible answer."

    async def test_tool_call_executes_and_continues(self, session, registry, orchestrator, tmp_path):
        # Write a file so bash can cat it
        (tmp_path / "hello.txt").write_text("world")
        llm = make_tool_then_text_llm("bash", {"command": f"cat {tmp_path}/hello.txt"})
        session.push_human("read the file")

        events = []
        await run_agent(session, llm, registry, orchestrator, on_event=events.append)

        tool_starts = [e for e in events if isinstance(e, ToolUseStart)]
        tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
        assert len(tool_starts) == 1
        assert tool_starts[0].name == "bash"
        assert len(tool_results) == 1
        assert "world" in tool_results[0].content

    async def test_tool_result_message_added_to_history(self, session, registry, orchestrator, tmp_path):
        (tmp_path / "f.txt").write_text("content")
        llm = make_tool_then_text_llm("bash", {"command": "echo hi"})
        session.push_human("run something")

        await run_agent(session, llm, registry, orchestrator)

        tool_msgs = [m for m in session.messages if isinstance(m, ToolMessage)]
        assert len(tool_msgs) == 1

    async def test_max_turns_raises(self, tmp_path):
        cfg = SessionConfig(max_turns=1)
        state = SessionState.new(cfg, cwd=str(tmp_path))
        state.push_human("first")

        from unittest.mock import AsyncMock, MagicMock
        # LLM always responds with a tool call → never ends naturally
        tool_resp = AIMessage(content="")
        tool_resp.tool_calls = [{"id": "c1", "name": "bash", "args": {"command": "echo hi"}}]
        tool_resp.usage_metadata = {"input_tokens": 5, "output_tokens": 2}

        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=llm)
        llm.ainvoke = AsyncMock(return_value=tool_resp)
        llm.astream = _make_astream(tool_resp)

        registry = default_registry()
        orchestrator = ToolOrchestrator(registry)

        with pytest.raises(RuntimeError, match="Max turns"):
            await run_agent(state, llm, registry, orchestrator)

    async def test_deny_permission_surfaces_as_tool_error(self, deny_ctx, tmp_path):
        cfg = SessionConfig(permission_mode="deny")
        state = SessionState.new(cfg, cwd=str(tmp_path))
        state.push_human("run bash")

        llm = make_tool_then_text_llm("bash", {"command": "echo secret"})

        registry = default_registry()
        orchestrator = ToolOrchestrator(registry)
        events = []
        await run_agent(state, llm, registry, orchestrator, on_event=events.append)

        error_results = [e for e in events if isinstance(e, ToolResultEvent) and e.is_error]
        assert len(error_results) == 1
        assert "permission denied" in error_results[0].content.lower()

    async def test_unknown_tool_surfaces_as_error(self, session, registry, orchestrator):
        llm = make_tool_then_text_llm("nonexistent_tool", {})
        session.push_human("use unknown tool")

        events = []
        await run_agent(session, llm, registry, orchestrator, on_event=events.append)

        error_events = [e for e in events if isinstance(e, ToolResultEvent) and e.is_error]
        assert len(error_events) == 1
        assert "Unknown tool" in error_events[0].content

    async def test_system_prompt_injected_from_project_memory(self, tmp_path):
        (tmp_path / "ZWISCHENZUG.md").write_text("Always be concise.")
        cfg = SessionConfig(system_prompt="Base prompt.")
        state = SessionState.new(cfg, cwd=str(tmp_path))
        state.push_human("hi")

        llm = make_text_llm("ok")
        registry = default_registry()
        orchestrator = ToolOrchestrator(registry)
        await run_agent(state, llm, registry, orchestrator)

        system_msgs = [m for m in state.messages if isinstance(m, SystemMessage)]
        assert len(system_msgs) == 1
        assert "Always be concise." in system_msgs[0].content
        assert "Base prompt." in system_msgs[0].content

    async def test_usage_event_emitted(self, session, registry, orchestrator):
        llm = make_text_llm("response")
        session.push_human("test")
        events = []
        await run_agent(session, llm, registry, orchestrator, on_event=events.append)
        usage_events = [e for e in events if isinstance(e, UsageUpdate)]
        assert len(usage_events) == 1
        assert usage_events[0].input_tokens == 10
        assert usage_events[0].output_tokens == 5

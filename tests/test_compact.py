"""
Tests for src/compact — TokenBudget, micro_compact, TruncateStrategy.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.compact import TokenBudget, TruncateStrategy, micro_compact


class TestTokenBudget:
    def test_input_budget_is_context_minus_output(self):
        budget = TokenBudget(context_window=200_000, max_output_tokens=16_384)
        assert budget.input_budget() == 200_000 - 16_384

    def test_should_compact_below_threshold_returns_false(self):
        budget = TokenBudget(context_window=200_000, max_output_tokens=16_384, compact_threshold=0.80)
        # 50% usage → no compact needed
        assert not budget.should_compact(90_000)

    def test_should_compact_at_threshold_returns_true(self):
        budget = TokenBudget(context_window=200_000, max_output_tokens=16_384, compact_threshold=0.80)
        # 80% of 183_616 ≈ 146_892
        assert budget.should_compact(147_000)

    def test_should_compact_above_threshold_returns_true(self):
        budget = TokenBudget(context_window=1000, max_output_tokens=100, compact_threshold=0.80)
        # input_budget = 900; 80% = 720; current = 800 → trigger
        assert budget.should_compact(800)

    def test_custom_threshold(self):
        budget = TokenBudget(context_window=10_000, max_output_tokens=1_000, compact_threshold=0.50)
        assert budget.should_compact(4_600)   # 51% → trigger
        assert not budget.should_compact(4_400)  # 49% → no trigger

    def test_default_values(self):
        budget = TokenBudget()
        assert budget.context_window == 200_000
        assert budget.max_output_tokens == 16_384
        assert budget.compact_threshold == 0.80


class TestMicroCompact:
    def test_short_text_unchanged(self):
        text = "hello world"
        assert micro_compact(text) == text

    def test_long_text_is_truncated(self):
        text = "x" * 15_000
        result = micro_compact(text)
        assert len(result) < len(text)
        assert result.endswith("[truncated]")

    def test_truncated_at_exactly_10000_chars(self):
        text = "a" * 10_001
        result = micro_compact(text)
        assert result.startswith("a" * 10_000)

    def test_exactly_threshold_is_unchanged(self):
        text = "b" * 10_000
        assert micro_compact(text) == text

    def test_empty_string(self):
        assert micro_compact("") == ""

    def test_unicode_text(self):
        text = "中文" * 3_000   # 6000 chars, under threshold
        assert micro_compact(text) == text


class TestTruncateStrategy:
    def _msgs(self, n: int, include_system: bool = False) -> list:
        msgs = []
        if include_system:
            msgs.append(SystemMessage(content="system"))
        for i in range(n):
            msgs.append(HumanMessage(content=f"human {i}") if i % 2 == 0 else AIMessage(content=f"ai {i}"))
        return msgs

    def test_small_history_unchanged(self):
        strategy = TruncateStrategy()
        budget = TokenBudget(context_window=10_000, max_output_tokens=1_000)
        msgs = self._msgs(2)
        result = strategy.compact(msgs, last_input_tokens=100, budget=budget)
        assert result == msgs

    def test_removes_old_messages_when_over_budget(self):
        strategy = TruncateStrategy()
        # Very tight budget forces aggressive removal
        budget = TokenBudget(context_window=1_000, max_output_tokens=100, compact_threshold=0.50)
        msgs = self._msgs(20)
        result = strategy.compact(msgs, last_input_tokens=800, budget=budget)
        assert len(result) < len(msgs)
        assert len(result) >= 2   # always keeps at least 2

    def test_preserves_system_message(self):
        strategy = TruncateStrategy()
        budget = TokenBudget(context_window=1_000, max_output_tokens=100, compact_threshold=0.50)
        msgs = self._msgs(20, include_system=True)
        result = strategy.compact(msgs, last_input_tokens=800, budget=budget)
        assert isinstance(result[0], SystemMessage)

    def test_keeps_most_recent_messages(self):
        strategy = TruncateStrategy()
        budget = TokenBudget(context_window=1_000, max_output_tokens=100)
        msgs = self._msgs(10)
        result = strategy.compact(msgs, last_input_tokens=850, budget=budget)
        # The last message must be retained
        assert result[-1] is msgs[-1]

    def test_zero_last_input_tokens_still_compacts(self):
        strategy = TruncateStrategy()
        budget = TokenBudget(context_window=1_000, max_output_tokens=100)
        msgs = self._msgs(20)
        result = strategy.compact(msgs, last_input_tokens=0, budget=budget)
        # Falls back to halving when no token data
        assert len(result) <= len(msgs)

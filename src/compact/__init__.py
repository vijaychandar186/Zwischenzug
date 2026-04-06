"""
Zwischenzug compact — token budget management and session compaction.

TokenBudget tracks context-window limits and determines when to compact.
CompactStrategy (pluggable) decides which messages to keep.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TokenBudget:
    """
    Tracks token limits for a model context window.

    Defaults match large-context models:
      - context_window:    200 000 tokens
      - max_output_tokens:  16 384 tokens reserved for responses
      - compact_threshold:     0.80 (trigger at 80% of input budget)
    """
    context_window: int = 200_000
    max_output_tokens: int = 16_384
    compact_threshold: float = 0.80

    def input_budget(self) -> int:
        """Max tokens available for input (context - reserved output)."""
        return self.context_window - self.max_output_tokens

    def should_compact(self, current_input_tokens: int) -> bool:
        """Return True when current usage exceeds the compact threshold."""
        return current_input_tokens >= int(self.input_budget() * self.compact_threshold)


MICRO_COMPACT_THRESHOLD = 10_000  # chars


def micro_compact(text: str) -> str:
    """
    Truncate a single oversized string to prevent one tool result from
    dominating the context window.
    """
    if len(text) > MICRO_COMPACT_THRESHOLD:
        return text[:MICRO_COMPACT_THRESHOLD] + "\n...[truncated]"
    return text


class CompactStrategy(ABC):
    """Pluggable compaction algorithm."""

    @abstractmethod
    def compact(self, messages: list, last_input_tokens: int, budget: TokenBudget) -> list:
        """Return a reduced message list that fits within the token budget."""
        ...


class TruncateStrategy(CompactStrategy):
    """
    Default strategy: keep the most recent messages, removing the oldest.
    Aims for 70% of the input budget so the next request has headroom.
    Always keeps at least 2 non-system messages.
    """

    def compact(self, messages: list, last_input_tokens: int, budget: TokenBudget) -> list:
        from langchain_core.messages import SystemMessage

        system = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        if len(non_system) <= 2:
            return messages

        msg_count = len(non_system)
        avg_tokens = (last_input_tokens or msg_count * 400) / max(1, msg_count)
        target = int(budget.input_budget() * 0.70)
        keep = max(2, min(msg_count, int(target / max(1, avg_tokens))))
        removed = msg_count - keep
        return system + non_system[removed:]


__all__ = ["TokenBudget", "micro_compact", "CompactStrategy", "TruncateStrategy"]

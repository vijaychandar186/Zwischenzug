"""
Zwischenzug session — state machine for multi-turn agent conversations.

Token budget logic is delegated to src/compact/ (its own sub-package).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from ..compact import CompactStrategy, TokenBudget, TruncateStrategy, micro_compact


# ---------------------------------------------------------------------------
# Session config
# ---------------------------------------------------------------------------

@dataclass
class SessionConfig:
    model: str = ""
    system_prompt: str = ""
    max_turns: int = 50
    token_budget: TokenBudget = field(default_factory=TokenBudget)
    permission_mode: str = "auto"   # "auto" | "interactive" | "deny"
    compact_strategy: CompactStrategy = field(default_factory=TruncateStrategy)

    @classmethod
    def default(cls) -> "SessionConfig":
        return cls()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """
    Mutable conversation state threaded through the agent loop.
    Owns the message history, token counters, and turn bookkeeping.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    config: SessionConfig = field(default_factory=SessionConfig)
    cwd: str = "."
    messages: list[BaseMessage] = field(default_factory=list)
    turn_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_input_tokens: int = 0
    created_at: float = field(default_factory=time.time)

    # ----------------------------------------------------------------
    # Message helpers
    # ----------------------------------------------------------------

    def push(self, message: BaseMessage) -> None:
        self.messages.append(message)

    def push_human(self, text: str) -> None:
        self.messages.append(HumanMessage(content=text))

    def push_system(self, text: str) -> None:
        """Insert a system message at the front (idempotent)."""
        if not self.messages or not isinstance(self.messages[0], SystemMessage):
            self.messages.insert(0, SystemMessage(content=text))
        else:
            # Refresh existing system message content
            self.messages[0] = SystemMessage(content=text)

    # ----------------------------------------------------------------
    # Compaction
    # ----------------------------------------------------------------

    def compact(self) -> int:
        """
        Delegate to the configured CompactStrategy.
        Returns the number of messages removed.
        """
        before = len(self.messages)
        self.messages = self.config.compact_strategy.compact(
            self.messages,
            self.last_input_tokens,
            self.config.token_budget,
        )
        return before - len(self.messages)

    # ----------------------------------------------------------------
    # Serialization
    # ----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        def _msg(m: BaseMessage) -> dict:
            base: dict[str, Any] = {
                "type": type(m).__name__,
                "content": str(m.content),
            }
            if isinstance(m, AIMessage):
                base["tool_calls"] = list(getattr(m, "tool_calls", []) or [])
            if isinstance(m, ToolMessage):
                base["tool_call_id"] = str(getattr(m, "tool_call_id", ""))
                base["name"] = str(getattr(m, "name", ""))
            return base

        return {
            "session_id": self.id,
            "config": {
                "model": self.config.model,
                "system_prompt": self.config.system_prompt,
                "max_turns": self.config.max_turns,
                "permission_mode": self.config.permission_mode,
            },
            "cwd": self.cwd,
            "turn_count": self.turn_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "messages": [_msg(m) for m in self.messages],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], config: SessionConfig | None = None) -> "SessionState":
        """
        Restore a SessionState from a serialized dict (for --resume / --continue).

        Args:
            data:   Dict produced by `to_dict()`.
            config: Override config (e.g. with new permission_mode). If None,
                    the config is rebuilt from the stored data.
        """
        stored_cfg = data.get("config", {})
        if config is None:
            config = SessionConfig(
                model=stored_cfg.get("model", ""),
                system_prompt=stored_cfg.get("system_prompt", ""),
                max_turns=stored_cfg.get("max_turns", 50),
                permission_mode=stored_cfg.get("permission_mode", "auto"),
            )

        messages: list[BaseMessage] = []
        for m in data.get("messages", []):
            msg_type = m.get("type", "HumanMessage")
            content = m.get("content", "")
            if msg_type == "SystemMessage":
                messages.append(SystemMessage(content=content))
            elif msg_type == "HumanMessage":
                messages.append(HumanMessage(content=content))
            elif msg_type == "AIMessage":
                messages.append(AIMessage(content=content, tool_calls=m.get("tool_calls", []) or []))
            elif msg_type == "ToolMessage":
                messages.append(ToolMessage(
                    content=content,
                    tool_call_id=m.get("tool_call_id", ""),
                    name=m.get("name", "unknown"),
                ))
            else:
                messages.append(HumanMessage(content=content))

        state = cls(
            id=data.get("session_id", str(uuid.uuid4())),
            config=config,
            cwd=data.get("cwd", "."),
            messages=messages,
            turn_count=data.get("turn_count", 0),
            total_input_tokens=data.get("total_input_tokens", 0),
            total_output_tokens=data.get("total_output_tokens", 0),
            created_at=data.get("created_at", time.time()),
        )
        return state

    @classmethod
    def new(cls, config: SessionConfig, cwd: str = ".") -> "SessionState":
        state = cls(config=config, cwd=cwd)
        if config.system_prompt:
            state.push_system(config.system_prompt)
        return state


# Re-export for convenience
__all__ = ["SessionConfig", "SessionState", "TokenBudget", "micro_compact"]

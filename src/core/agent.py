"""
Zwischenzug agent loop — the beating heart of the runtime.

Drives multi-turn conversations by:
  1. Building the system prompt (base + ZWISCHENZUG.md + memory index)
  2. Streaming the model response
  3. Collecting assistant text and tool_use blocks
  4. Running pre-tool hooks (blocking if they exit non-zero)
  5. Executing tool calls via the orchestrator
  6. Running post-tool hooks
  7. Appending tool_result messages
  8. Looping until end_turn or max_turns exceeded
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, AsyncIterator, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from .session import SessionState, micro_compact
from .system_prompt import build_system_prompt, load_project_instructions, load_graph_context

# Backward-compat alias — tests may import this directly
_load_project_memory = load_project_instructions
from ..tools import ToolContext, ToolOrchestrator, ToolRegistry
from ..tools import PermissionMode

if TYPE_CHECKING:
    from ..hooks import HookRunner, HookEvent

logger = logging.getLogger("zwischenzug.agent")

MAX_RETRIES = 3
RATE_LIMIT_DELAY = 2.0  # seconds


# ---------------------------------------------------------------------------
# Query events (streamed to the UI layer)
# ---------------------------------------------------------------------------

@dataclass
class ThinkingDelta:
    text: str


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUseStart:
    id: str
    name: str
    args: dict


@dataclass
class ToolResultEvent:
    tool_use_id: str
    content: str
    is_error: bool


@dataclass
class TurnComplete:
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"


@dataclass
class UsageUpdate:
    input_tokens: int
    output_tokens: int


QueryEvent = ThinkingDelta | TextDelta | ToolUseStart | ToolResultEvent | TurnComplete | UsageUpdate

EventCallback = Callable[[QueryEvent], None]


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------

class _ErrorClass(Enum):
    CONTEXT_TOO_LONG = "context_too_long"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    UNRETRYABLE = "unretryable"


def _classify_error(exc: Exception) -> _ErrorClass:
    msg = str(exc).lower()
    # 413 "request too large" is a context-size error, even when the provider
    # embeds a rate_limit_exceeded code in the payload.  Check this first.
    if "413" in msg and "request too large" in msg:
        return _ErrorClass.CONTEXT_TOO_LONG
    # Rate limits — Groq TPM/RPM 413s that mention "per minute" / TPM / RPM
    # are genuine rate limits, not context errors.
    if (
        "429" in msg
        or "rate limit" in msg
        or "rate_limit" in msg
        or "tokens per minute" in msg
        or "tpm" in msg
        or "rpm" in msg
        or ("413" in msg and ("per minute" in msg or "tpm" in msg or "rpm" in msg))
    ):
        return _ErrorClass.RATE_LIMIT
    if (
        "context_too_long" in msg
        or "context window" in msg
        or "context length" in msg
        or "maximum context" in msg
    ):
        return _ErrorClass.CONTEXT_TOO_LONG
    if any(code in msg for code in ("500", "502", "503", "internal server error")):
        return _ErrorClass.SERVER_ERROR
    return _ErrorClass.UNRETRYABLE


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def run_agent(
    session: SessionState,
    llm,  # LangChain ChatModel (Groq / Gemini / etc.)
    registry: ToolRegistry,
    orchestrator: ToolOrchestrator,
    on_event: EventCallback | None = None,
    hook_runner: "HookRunner | None" = None,
) -> None:
    """
    Run the multi-turn agent loop until the model ends the conversation
    or max_turns is exceeded.

    Args:
        session:      Mutable session state (messages, token counts, etc.)
        llm:          A LangChain ChatModel with tool-calling support.
        registry:     Tool registry providing available tools.
        orchestrator: Executes tool calls and enforces permissions.
        on_event:     Optional callback for streaming events to the UI.
        hook_runner:  Optional lifecycle hook runner.
    """
    from ..memory import MemoryManager

    def emit(event: QueryEvent) -> None:
        if on_event:
            on_event(event)

    # Build LangChain tools and bind them to the model
    # Extract provider from model string (e.g. "groq/llama-3.3-70b" → "groq")
    _model_str = session.config.model or ""
    _provider = _model_str.split("/", 1)[0] if "/" in _model_str else ""
    tool_ctx = ToolContext(
        cwd=session.cwd,
        permission_mode=PermissionMode(session.config.permission_mode),
        session_id=session.id,
        provider=_provider,
        model=_model_str,
    )
    lc_tools = registry.as_langchain_tools(tool_ctx)
    bound_llm = llm.bind_tools(lc_tools) if lc_tools else llm

    # Build system prompt: base + ZWISCHENZUG.md + memory index
    zwischenzug_md = load_project_instructions(session.cwd)
    memory_index: str | None = None
    try:
        mgr = MemoryManager.default()
        memory_index = mgr.load_index() or None
    except Exception:  # noqa: BLE001
        pass  # memory system failure is non-fatal

    # Load graph context (only if graph has been built with `zwis learn`)
    graph_context: str | None = None
    try:
        graph_context = load_graph_context(session.cwd)
    except Exception:  # noqa: BLE001
        pass

    system_text = build_system_prompt(
        base=session.config.system_prompt,
        zwischenzug_md=zwischenzug_md,
        memory_index=memory_index,
        graph_context=graph_context,
    )

    # Inject / refresh system message
    if system_text:
        session.push_system(system_text)

    # Run session-start hook (non-blocking for post-type hooks handled in REPL)
    # PreQuery hook before first turn is handled in the loop below.

    retry_count = 0
    context_compacted = False

    while True:
        # Token budget check — compact before building the request
        if (
            session.last_input_tokens > 0
            and session.config.token_budget.should_compact(session.last_input_tokens)
        ):
            removed = session.compact()
            logger.info("token budget threshold exceeded — compacted %d messages", removed)

        if session.turn_count >= session.config.max_turns:
            raise RuntimeError(
                f"Max turns ({session.config.max_turns}) exceeded. "
                "Increase --max-turns or start a new session."
            )

        session.turn_count += 1
        logger.debug("starting turn %d", session.turn_count)

        # ----------------------------------------------------------------
        # Pre-query hook
        # ----------------------------------------------------------------
        if hook_runner is not None:
            from ..hooks import HookEvent
            blocked = not await hook_runner.run(
                HookEvent.PRE_QUERY,
                session_id=session.id,
                cwd=session.cwd,
            )
            if blocked:
                logger.warning("PreQuery hook blocked the API call.")
                session.turn_count -= 1
                break

        # ----------------------------------------------------------------
        # Call the model
        # ----------------------------------------------------------------
        try:
            response = await _stream_response(bound_llm, session.messages, emit)
            retry_count = 0
            context_compacted = False
        except Exception as exc:  # noqa: BLE001
            ec = _classify_error(exc)
            if ec == _ErrorClass.CONTEXT_TOO_LONG:
                if context_compacted:
                    raise RuntimeError(
                        "Context still too long after compaction. "
                        "The system prompt or tool schemas may exceed this model's context window. "
                        "Try /clear to reset the conversation, or switch to a model with a larger context window."
                    ) from exc
                logger.warning("context_too_long — compacting and retrying")
                removed = session.compact()
                if removed == 0:
                    raise RuntimeError(
                        "Context too long and compaction removed nothing "
                        f"({len(session.messages)} messages remain). "
                        "The system prompt or tool schemas may exceed this model's context window. "
                        "Try /clear to reset the conversation, or switch to a model with a larger context window."
                    ) from exc
                context_compacted = True
                session.turn_count -= 1
                continue
            if ec in (_ErrorClass.RATE_LIMIT, _ErrorClass.SERVER_ERROR):
                if retry_count < MAX_RETRIES:
                    retry_count += 1
                    logger.warning(
                        "transient error (attempt %d/%d): %s", retry_count, MAX_RETRIES, exc
                    )
                    session.turn_count -= 1
                    await asyncio.sleep(RATE_LIMIT_DELAY * retry_count)
                    continue
            raise

        # ----------------------------------------------------------------
        # Post-query hook
        # ----------------------------------------------------------------
        if hook_runner is not None:
            from ..hooks import HookEvent
            await hook_runner.run(
                HookEvent.POST_QUERY,
                session_id=session.id,
                cwd=session.cwd,
            )

        # ----------------------------------------------------------------
        # Track token usage
        # ----------------------------------------------------------------
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            inp = um.get("input_tokens", 0)
            out = um.get("output_tokens", 0)
            session.last_input_tokens = inp
            session.total_input_tokens += inp
            session.total_output_tokens += out
            emit(UsageUpdate(input_tokens=inp, output_tokens=out))

        # Thinking and text deltas were already emitted during streaming.
        # Extract final text for history normalization below.

        # Add a normalized assistant message to history so providers that emit
        # structured reasoning/content blocks do not poison the next turn.
        session.push(_normalize_ai_message_for_history(response))

        # ----------------------------------------------------------------
        # Handle tool calls
        # ----------------------------------------------------------------
        tool_calls = getattr(response, "tool_calls", []) or []

        if not tool_calls:
            # No tool calls → conversation is done
            emit(TurnComplete(stop_reason="end_turn"))
            logger.debug("no tool calls — ending agent loop")
            return

        # Emit tool start events
        for tc in tool_calls:
            emit(ToolUseStart(id=tc["id"], name=tc["name"], args=tc["args"]))

        # ----------------------------------------------------------------
        # Pre-tool hooks (run once per batch, matching each tool name)
        # ----------------------------------------------------------------
        if hook_runner is not None:
            from ..hooks import HookEvent
            for tc in tool_calls:
                blocked = not await hook_runner.run(
                    HookEvent.PRE_TOOL_USE,
                    matcher=tc["name"],
                    session_id=session.id,
                    cwd=session.cwd,
                    env_extra={"ZWIS_TOOL_NAME": tc["name"]},
                )
                if blocked:
                    # Inject a synthetic error result for this tool call
                    tool_calls_to_run = [t for t in tool_calls if t["id"] != tc["id"]]
                    session.push(
                        ToolMessage(
                            content="[Permission denied by pre-tool hook]",
                            tool_call_id=tc["id"],
                            name=tc["name"],
                        )
                    )
                    emit(ToolResultEvent(
                        tool_use_id=tc["id"],
                        content="[Permission denied by pre-tool hook]",
                        is_error=True,
                    ))

        # Execute all tool calls (may run in parallel for read-only tools)
        lc_tool_calls = [
            {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
            for tc in tool_calls
        ]
        results = await orchestrator.execute_batch(lc_tool_calls, tool_ctx)

        # ----------------------------------------------------------------
        # Post-tool hooks
        # ----------------------------------------------------------------
        if hook_runner is not None:
            from ..hooks import HookEvent
            for tc in tool_calls:
                await hook_runner.run(
                    HookEvent.POST_TOOL_USE,
                    matcher=tc["name"],
                    session_id=session.id,
                    cwd=session.cwd,
                    env_extra={"ZWIS_TOOL_NAME": tc["name"]},
                )

        # Append tool results to history (user role per API convention)
        for r in results:
            content = micro_compact(r.output.content)
            emit(ToolResultEvent(
                tool_use_id=r.tool_call_id,
                content=content,
                is_error=r.output.is_error,
            ))
            session.push(
                ToolMessage(
                    content=content,
                    tool_call_id=r.tool_call_id,
                    name=next(
                        (tc["name"] for tc in tool_calls if tc["id"] == r.tool_call_id),
                        "unknown",
                    ),
                )
            )
        # Loop back → model continues after seeing tool results


async def _stream_response(
    llm,
    messages: list,
    emit: Callable[[QueryEvent], None],
) -> AIMessage:
    """
    Stream the model response, emitting TextDelta / ThinkingDelta events
    as chunks arrive.  Returns the fully-accumulated AIMessage.
    """
    from langchain_core.messages import AIMessageChunk

    accumulated: AIMessageChunk | None = None

    async for chunk in llm.astream(messages):
        # Merge chunks into a single accumulated message
        if accumulated is None:
            accumulated = chunk
        else:
            accumulated = accumulated + chunk

        # Emit thinking deltas
        thinking = _extract_thinking_content(chunk)
        if thinking:
            emit(ThinkingDelta(text=thinking))

        # Emit text deltas
        text = _extract_text_content(chunk)
        if text:
            emit(TextDelta(text=text))

    if accumulated is None:
        return AIMessage(content="")

    # Convert the accumulated chunk into a proper AIMessage.
    # Attach usage/response metadata post-init to avoid pydantic validation
    # issues with provider-specific dict shapes.
    msg = AIMessage(
        content=accumulated.content,
        tool_calls=getattr(accumulated, "tool_calls", []) or [],
    )
    if getattr(accumulated, "usage_metadata", None):
        msg.usage_metadata = accumulated.usage_metadata
    if getattr(accumulated, "response_metadata", None):
        msg.response_metadata = accumulated.response_metadata
    return msg


def _extract_thinking_content(message: AIMessage) -> str:
    """Extract reasoning/thinking blocks from provider-specific AIMessage."""
    content = message.content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            text = block.get("thinking", "") or block.get("text", "")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts)


def _extract_text_content(message: AIMessage) -> str:
    """Normalize provider-specific AIMessage content into plain text."""
    content = message.content
    if isinstance(content, str):
        return content

    text_attr = getattr(message, "text", "")
    if isinstance(text_attr, str) and text_attr:
        return text_attr

    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "".join(parts)

    return ""


def _normalize_ai_message_for_history(message: AIMessage) -> AIMessage:
    """Store assistant history in a replay-safe form for the next provider call."""
    normalized = AIMessage(
        content=_extract_text_content(message),
        tool_calls=getattr(message, "tool_calls", []) or [],
    )
    if getattr(message, "usage_metadata", None):
        normalized.usage_metadata = message.usage_metadata
    if getattr(message, "response_metadata", None):
        normalized.response_metadata = message.response_metadata
    return normalized

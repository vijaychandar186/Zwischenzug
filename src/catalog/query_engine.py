from __future__ import annotations

from .catalog import command_entries, tool_entries
from .manifest import build_port_manifest
from .models import TurnResult


class QueryEnginePort:
    def __init__(self) -> None:
        self.messages: list[str] = []

    @classmethod
    def from_workspace(cls) -> "QueryEnginePort":
        return cls()

    def render_summary(self) -> str:
        manifest = build_port_manifest()
        return "\n".join(
            [
                "# Zwischenzug Workspace Summary",
                "",
                manifest.to_markdown(),
                "",
                f"Command surface: {len(command_entries())}",
                f"Tool surface: {len(tool_entries())}",
            ]
        )

    def submit_message(self, prompt: str, matched_commands: tuple[str, ...] = (), matched_tools: tuple[str, ...] = ()) -> TurnResult:
        self.messages.append(prompt)
        output = f"Prompt: {prompt}\nCommands: {', '.join(matched_commands) or 'none'}\nTools: {', '.join(matched_tools) or 'none'}"
        return TurnResult(
            output=output,
            stop_reason="completed",
            matched_commands=matched_commands,
            matched_tools=matched_tools,
        )

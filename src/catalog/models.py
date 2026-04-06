from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    responsibility: str
    source_hint: str


@dataclass(frozen=True)
class ExecutionResult:
    handled: bool
    message: str


@dataclass(frozen=True)
class RoutedMatch:
    kind: str
    name: str
    score: int
    source_hint: str


@dataclass(frozen=True)
class TurnResult:
    output: str
    stop_reason: str
    matched_commands: tuple[str, ...]
    matched_tools: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeSession:
    prompt: str
    matches: tuple[RoutedMatch, ...]
    command_messages: tuple[str, ...]
    tool_messages: tuple[str, ...]
    turn_result: TurnResult
    persisted_session_path: str

    def as_markdown(self) -> str:
        lines = [
            "# Runtime Session",
            "",
            f"Prompt: {self.prompt}",
            "",
            "## Routed Matches",
        ]
        if self.matches:
            lines.extend(f"- [{m.kind}] {m.name} ({m.score}) - {m.source_hint}" for m in self.matches)
        else:
            lines.append("- none")
        lines.extend([
            "",
            "## Command Execution",
            *(self.command_messages or ("none",)),
            "",
            "## Tool Execution",
            *(self.tool_messages or ("none",)),
            "",
            "## Turn Result",
            self.turn_result.output,
            "",
            f"Persisted session path: {self.persisted_session_path}",
        ])
        return "\n".join(lines)


@dataclass(frozen=True)
class ModuleSummary:
    name: str
    file_count: int
    notes: str


@dataclass(frozen=True)
class PortManifest:
    port_root: str
    total_python_files: int
    top_level_modules: tuple[ModuleSummary, ...]

    def to_markdown(self) -> str:
        lines = [
            f"Port root: `{self.port_root}`",
            f"Total Python files: **{self.total_python_files}**",
            "",
            "Top-level Python modules:",
        ]
        lines.extend(f"- `{m.name}` ({m.file_count} files) - {m.notes}" for m in self.top_level_modules)
        return "\n".join(lines)


@dataclass
class SessionPayload:
    messages: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class StoredSession:
    session_id: str
    messages: tuple[str, ...]
    input_tokens: int
    output_tokens: int

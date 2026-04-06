from __future__ import annotations

from .catalog import execute_command, execute_tool, get_command, get_tool, get_tools, command_entries
from .models import RoutedMatch, RuntimeSession, SessionPayload
from .query_engine import QueryEnginePort
from .session_store import save_session


class PortRuntime:
    def route_prompt(self, prompt: str, limit: int = 5) -> list[RoutedMatch]:
        tokens = {t.lower() for t in prompt.replace("-", " ").replace("/", " ").split() if t}
        matches: list[RoutedMatch] = []

        for entry in command_entries():
            score = self._score(tokens, entry.name, entry.responsibility, entry.source_hint)
            if score > 0:
                matches.append(RoutedMatch(kind="command", name=entry.name, score=score, source_hint=entry.source_hint))

        for entry in get_tools():
            score = self._score(tokens, entry.name, entry.responsibility, entry.source_hint)
            if score > 0:
                matches.append(RoutedMatch(kind="tool", name=entry.name, score=score, source_hint=entry.source_hint))

        matches.sort(key=lambda m: (-m.score, m.kind, m.name))
        return matches[:limit]

    def bootstrap_session(self, prompt: str, limit: int = 5) -> RuntimeSession:
        matches = self.route_prompt(prompt, limit)
        command_messages = tuple(
            execute_command(m.name, prompt).message
            for m in matches
            if m.kind == "command" and get_command(m.name) is not None
        )
        tool_messages = tuple(
            execute_tool(m.name, prompt).message
            for m in matches
            if m.kind == "tool" and get_tool(m.name) is not None
        )
        engine = QueryEnginePort.from_workspace()
        turn = engine.submit_message(
            prompt,
            matched_commands=tuple(m.name for m in matches if m.kind == "command"),
            matched_tools=tuple(m.name for m in matches if m.kind == "tool"),
        )
        session_path = save_session(SessionPayload(messages=[prompt, turn.output], input_tokens=len(prompt.split()), output_tokens=len(turn.output.split())))
        return RuntimeSession(
            prompt=prompt,
            matches=tuple(matches),
            command_messages=command_messages,
            tool_messages=tool_messages,
            turn_result=turn,
            persisted_session_path=session_path,
        )

    def run_turn_loop(self, prompt: str, limit: int = 5, max_turns: int = 3) -> list[str]:
        engine = QueryEnginePort.from_workspace()
        matches = self.route_prompt(prompt, limit)
        commands = tuple(m.name for m in matches if m.kind == "command")
        tools = tuple(m.name for m in matches if m.kind == "tool")
        outputs: list[str] = []
        for turn in range(max_turns):
            turn_prompt = prompt if turn == 0 else f"{prompt} [turn {turn + 1}]"
            result = engine.submit_message(turn_prompt, matched_commands=commands, matched_tools=tools)
            outputs.append(f"## Turn {turn + 1}\n{result.output}\nstop_reason={result.stop_reason}")
        return outputs

    @staticmethod
    def _score(tokens: set[str], *haystacks: str) -> int:
        lowered = [h.lower() for h in haystacks]
        return sum(1 for token in tokens if any(token in h for h in lowered))

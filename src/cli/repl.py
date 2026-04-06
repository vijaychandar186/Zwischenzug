"""
Zwischenzug REPL — interactive multi-turn conversation loop.

Features:
  • readline editing, persistent history, tab completion for slash commands
  • Rich streaming output (colour, panels, markdown)
  • Full slash command set: /help /tools /session /clear /save /exit /quit
    /compact /memory /skills /cost /status /config /plan
    + all skills auto-registered as /skill-name commands
  • Token stats on exit
  • Hook runner integration (SessionStart, SessionEnd)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..app_paths import app_home, history_file, sessions_dir
from ..core.agent import (
    EventCallback,
    QueryEvent,
    ThinkingDelta,
    TextDelta,
    ToolResultEvent,
    ToolUseStart,
    TurnComplete,
    UsageUpdate,
    run_agent,
)
from ..core.session import SessionConfig, SessionState
from ..tools import PermissionMode, ToolOrchestrator, ToolRegistry, default_registry

console = Console()
err_console = Console(stderr=True)

# Log file handle — set by _enable_log_file(), used by _log_write().
_log_file: "open | None" = None


def _enable_log_file(cwd: str) -> None:
    """Open .zwis/zwis.log for append and install a tee on the console."""
    global _log_file, console, err_console
    import logging as _logging

    log_dir = app_home(cwd)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "zwis.log"
    _log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115

    # Write a separator so successive runs are easy to tell apart.
    import datetime as _dt
    _log_file.write(f"\n{'-' * 80}\n")
    _log_file.write(f"Session started: {_dt.datetime.now().isoformat()}\n")
    _log_file.write(f"{'-' * 80}\n")
    _log_file.flush()

    # Also capture Python logging output (browser-use, LiteLLM, etc.) to the log file.
    file_handler = _logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(_logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s"))
    _logging.root.addHandler(file_handler)

    # Wrap both consoles so every print also goes to the log file.
    console = _TeeConsole(file=sys.stdout)
    err_console = _TeeConsole(file=sys.stderr, stderr=True)


class _TeeConsole(Console):
    """A Rich Console that also writes plain-text output to the log file."""

    def print(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        super().print(*args, **kwargs)
        if _log_file is not None:
            # Render the same content as plain text for the log.
            with self.capture() as captured:
                super().print(*args, **kwargs)
            text = captured.get()
            if text:
                _log_file.write(text)
                _log_file.flush()

PALETTE = ["#ff2d95", "#ff6f3c", "#ffd166", "#06d6a0", "#00b4ff", "#7b61ff"]
PROMPT_STYLE = "[bold #7b61ff]❯[/] "

_ASCII_LOGO = r"""  ______        _          _
 |___  /       (_)        | |
    / /_      ___ ___  ___| |__   ___ _ __  _____   _  __ _
   / /\ \ /\ / / / __|/ __| '_ \ / _ \ '_ \|_  / | | |/ _` |
  / /__\ V  V /| \__ \ (__| | | |  __/ | | |/ /| |_| | (_| |
 /_____|\_/\_/ |_|___/\___|_| |_|\___|_| |_/___|\__,_|\__, |
                                                       __/ |
                                                      |____/ """



# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

def _print_banner(model: str, provider: str) -> None:
    for i, line in enumerate(_ASCII_LOGO.split("\n")):
        console.print(line, style=f"bold {PALETTE[i % len(PALETTE)]}")
    console.print(
        f"\n[dim]provider:[/] [bold]{provider}[/]  "
        f"[dim]model:[/] [bold]{model}[/]  "
        f"[dim]type[/] [bold]/help[/] [dim]for commands[/]"
    )
    console.print()


# ---------------------------------------------------------------------------
# Event callback
# ---------------------------------------------------------------------------

def _make_event_callback(
    accumulator: list[str],
    stop_status: Callable[[], None] | None = None,
) -> EventCallback:
    def on_event(event: QueryEvent) -> None:
        if stop_status is not None and not isinstance(event, UsageUpdate):
            stop_status()
        if isinstance(event, ThinkingDelta):
            console.print(
                f"\n[dim italic]🧠 Thinking:[/]\n[dim]{event.text}[/]\n",
                highlight=False,
            )
        elif isinstance(event, TextDelta):
            accumulator.append(event.text)
            console.print(event.text, end="", highlight=False)
        elif isinstance(event, ToolUseStart):
            console.print(
                f"\n[dim]⚡ Tool:[/] [bold cyan]{event.name}[/]",
                highlight=False,
            )
        elif isinstance(event, ToolResultEvent):
            icon = "✅" if not event.is_error else "❌"
            preview = event.content[:120].replace("\n", " ")
            console.print(
                f"[dim]{icon} Result ({len(event.content)} chars):[/] {preview}",
                highlight=False,
            )
        elif isinstance(event, TurnComplete):
            console.print()  # newline after streamed text
        elif isinstance(event, UsageUpdate):
            pass  # shown in session stats

    return on_event


# ---------------------------------------------------------------------------
# Input reading
# ---------------------------------------------------------------------------

_CTRL_C = object()


def _read_multiline(prompt_text: str) -> "str | None | object":
    """Read possibly multi-line input. Lines ending with \\ continue."""
    try:
        line = input(prompt_text)
    except EOFError:
        return None
    except KeyboardInterrupt:
        print()
        return _CTRL_C

    parts = [line]
    while parts and parts[-1].endswith("\\"):
        parts[-1] = parts[-1][:-1]
        try:
            parts.append(input("... "))
        except (EOFError, KeyboardInterrupt):
            break

    text = "\n".join(parts).strip()
    if _log_file is not None and text:
        _log_file.write(f"\n> {text}\n")
        _log_file.flush()
    return text


# ---------------------------------------------------------------------------
# Slash command handler
# ---------------------------------------------------------------------------

def _handle_slash(
    cmd: str,
    session: SessionState,
    registry: ToolRegistry,
    skill_registry: Any,        # SkillRegistry | None
    memory_manager: Any,        # MemoryManager | None
    agent_config: Any,          # AgentConfig | None
    provider: str,
) -> "bool | str":
    """
    Handle a /command.

    Returns:
        True  — command handled, continue REPL
        False — exit REPL
        str   — a prompt string to inject into the conversation
    """
    parts = cmd.strip().split(None, 1)
    name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    # ── Exit ────────────────────────────────────────────────────────────────
    if name in ("/exit", "/quit"):
        return False

    # ── Help ─────────────────────────────────────────────────────────────────
    if name == "/help":
        _show_help(skill_registry)
        return True

    # ── Tools ────────────────────────────────────────────────────────────────
    if name == "/tools":
        tools = registry.all()
        rows = "\n".join(
            f"  • **{t.name}** — {t.description[:70]}{'…' if len(t.description) > 70 else ''}"
            for t in tools
        )
        console.print(Markdown(f"**Available tools ({len(tools)})**\n\n{rows}"))
        return True

    # ── Session stats ────────────────────────────────────────────────────────
    if name == "/session":
        _show_session(session)
        return True

    # ── Clear history ────────────────────────────────────────────────────────
    if name == "/clear":
        from langchain_core.messages import SystemMessage
        system_msgs = [m for m in session.messages if isinstance(m, SystemMessage)]
        session.messages = system_msgs
        session.turn_count = 0
        console.print("[dim]History cleared.[/]")
        return True

    # ── Save session ─────────────────────────────────────────────────────────
    if name == "/save":
        _save_session(session)
        return True

    # ── Manual compact ──────────────────────────────────────────────────────
    if name == "/compact":
        removed = session.compact()
        console.print(
            f"[dim]Compacted: removed {removed} messages. "
            f"Remaining: {len(session.messages)}[/]"
        )
        return True

    # ── Memory ───────────────────────────────────────────────────────────────
    if name == "/memory":
        if memory_manager is None:
            console.print("[dim]Memory system not available.[/]")
            return True
        if args:
            console.print(Markdown(memory_manager.render_entry(args)))
        else:
            console.print(Markdown(memory_manager.render_list()))
        return True

    # ── Skills ───────────────────────────────────────────────────────────────
    if name == "/skills":
        if skill_registry is None or not skill_registry.all():
            console.print("[dim]No skills discovered.[/]")
            return True
        _show_skills(skill_registry.all())
        return True

    # ── Cost ─────────────────────────────────────────────────────────────────
    if name == "/cost":
        _show_cost(session, provider)
        return True

    # ── Status ───────────────────────────────────────────────────────────────
    if name == "/status":
        _show_status(session, provider)
        return True

    # ── Config ───────────────────────────────────────────────────────────────
    if name == "/config":
        if agent_config is not None:
            _show_config(agent_config)
        else:
            console.print("[dim]Config not available.[/]")
        return True

    # ── Plan mode ────────────────────────────────────────────────────────────
    if name == "/plan":
        session.config.permission_mode = "deny"
        console.print(
            "[bold yellow]Plan mode enabled.[/] "
            "[dim]Write operations are blocked. Use /auto to disable.[/]"
        )
        return True

    if name == "/auto":
        session.config.permission_mode = "auto"
        console.print("[bold green]Auto mode enabled.[/] [dim]Write operations allowed.[/]")
        return True

    # ── Graph ────────────────────────────────────────────────────────────────
    if name == "/graph":
        _show_graph(args)
        return True

    # ── Knowledge files ──────────────────────────────────────────────────────
    if name == "/knowledge":
        _show_knowledge(args)
        return True

    # ── Games ────────────────────────────────────────────────────────────────
    if name == "/game/flappy-bird":
        from ..games import run_flappy_bird

        console.print("[bold cyan]Launching Flappy Bird...[/]")
        run_flappy_bird(cwd=session.cwd, console=console)
        return True

    # ── Skill commands (auto-registered) ─────────────────────────────────────
    if skill_registry is not None:
        skill = skill_registry.get(name)
        if skill is not None:
            expanded = skill.expand(args)
            if not expanded:
                console.print(f"[red]Skill {name!r} has an empty template.[/]")
                return True
            return expanded  # caller will submit this as a user message

    # ── Unknown ──────────────────────────────────────────────────────────────
    console.print(f"[red]Unknown command: {name}[/]  Type [bold]/help[/] for commands.")
    return True


# ---------------------------------------------------------------------------
# Rich display helpers
# ---------------------------------------------------------------------------

def _show_help(skill_registry: Any) -> None:
    help_md = """\
**Built-in slash commands**

| Command | Description |
|---------|-------------|
| /help | Show this help message |
| /tools | List available tools |
| /session | Show current session stats |
| /clear | Clear conversation history |
| /save | Save session to .zwis/sessions/ |
| /compact | Manually compress conversation context |
| /memory [name] | List memories or show a specific memory |
| /skills | List all available skills |
| /cost | Show token usage and estimated cost |
| /status | Show model, provider, session info |
| /config | Show current configuration |
| /plan | Enter plan mode (read-only, no writes) |
| /auto | Return to auto mode (writes allowed) |
| /graph [map] | Show knowledge graph stats or architecture map |
| /knowledge [topic] | List or view knowledge files from .zwis/knowledge/ |
| /game/flappy-bird | Play the built-in terminal game (CLI: `zwis game flappy-bird`) |
| /exit /quit | Exit the REPL |

Type any message to talk to the AI.
Multi-line input: end a line with `\\` to continue.
"""
    if skill_registry is not None:
        skills = skill_registry.all()
        if skills:
            skill_rows = "\n".join(
                f"| /{s.name} | {s.description} |"
                for s in skills
            )
            help_md += f"\n**Skills (invoke with /name)**\n\n| Skill | Description |\n|-------|-------------|\n{skill_rows}\n"

    console.print(Markdown(help_md))


def _show_session(session: SessionState) -> None:
    table = Table(title="Session Stats", border_style="#7b61ff", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("ID", session.id[:16] + "…")
    table.add_row("Model", session.config.model)
    table.add_row("Permission", session.config.permission_mode)
    table.add_row("Turns", str(session.turn_count))
    table.add_row("Messages", str(len(session.messages)))
    table.add_row("Input tokens", f"{session.total_input_tokens:,}")
    table.add_row("Output tokens", f"{session.total_output_tokens:,}")
    table.add_row("CWD", session.cwd)
    console.print(table)


def _get_cost_rates() -> tuple[float, float]:
    """Return (input_rate, output_rate) per 1M tokens from env vars.

    Set ZWISCHENZUG_COST_INPUT and ZWISCHENZUG_COST_OUTPUT in your .env.
    Values are USD per 1 million tokens. Returns (0.0, 0.0) if not set.
    """
    try:
        inp = float(os.getenv("ZWISCHENZUG_COST_INPUT", "0") or "0")
    except ValueError:
        inp = 0.0
    try:
        out = float(os.getenv("ZWISCHENZUG_COST_OUTPUT", "0") or "0")
    except ValueError:
        out = 0.0
    return inp, out


def _calc_cost(session: SessionState) -> tuple[float, float, float]:
    """Return (input_cost, output_cost, total_cost) in USD."""
    inp_rate, out_rate = _get_cost_rates()
    inp_cost = session.total_input_tokens / 1_000_000 * inp_rate
    out_cost = session.total_output_tokens / 1_000_000 * out_rate
    return inp_cost, out_cost, inp_cost + out_cost


def _get_budget() -> float | None:
    """Return ZWISCHENZUG_BUDGET in USD, or None if not set."""
    raw = os.getenv("ZWISCHENZUG_BUDGET", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _show_cost(session: SessionState, provider: str) -> None:
    inp_rate, out_rate = _get_cost_rates()
    inp_cost, out_cost, total = _calc_cost(session)
    budget = _get_budget()
    has_rates = inp_rate > 0 or out_rate > 0

    table = Table(title="Token Usage", border_style="cyan", show_header=True)
    table.add_column("", style="bold")
    table.add_column("Tokens", justify="right")
    if has_rates:
        table.add_column("Est. Cost (USD)", justify="right")
        table.add_row("Input", f"{session.total_input_tokens:,}", f"${inp_cost:.5f}")
        table.add_row("Output", f"{session.total_output_tokens:,}", f"${out_cost:.5f}")
        table.add_row("Total", f"{session.total_input_tokens + session.total_output_tokens:,}", f"${total:.5f}")
    else:
        table.add_row("Input", f"{session.total_input_tokens:,}")
        table.add_row("Output", f"{session.total_output_tokens:,}")
        table.add_row("Total", f"{session.total_input_tokens + session.total_output_tokens:,}")
    console.print(table)

    if has_rates:
        console.print(f"[dim]Rates: ${inp_rate}/1M input, ${out_rate}/1M output[/]")
    else:
        console.print("[dim]Set ZWISCHENZUG_COST_INPUT / ZWISCHENZUG_COST_OUTPUT in .env for cost tracking.[/]")

    if budget is not None:
        remaining = budget - total
        color = "red" if remaining <= 0 else "yellow" if remaining < budget * 0.1 else "green"
        console.print(f"[{color}]Budget: ${total:.5f} / ${budget:.2f} used ({remaining:.5f} remaining)[/]")


def _show_status(session: SessionState, provider: str) -> None:
    table = Table(title="System Status", border_style="green", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Provider", provider)
    table.add_row("Model", session.config.model)
    table.add_row("Permission mode", session.config.permission_mode)
    table.add_row("Session ID", session.id[:24] + "…")
    table.add_row("Turn count", str(session.turn_count))
    table.add_row("Max turns", str(session.config.max_turns))
    table.add_row("Working dir", session.cwd)
    table.add_row(
        "Context",
        f"{session.last_input_tokens:,} tokens (last turn)"
        if session.last_input_tokens else "N/A (no turns yet)"
    )
    console.print(table)


def _show_config(agent_config: Any) -> None:
    table = Table(title="Agent Configuration", border_style="blue", show_header=False)
    table.add_column("Setting", style="bold")
    table.add_column("Value")
    for key, val in vars(agent_config).items():
        if key != "system_prompt":
            table.add_row(key, str(val))
    if agent_config.system_prompt:
        table.add_row("system_prompt", agent_config.system_prompt[:80] + "…")
    console.print(table)


def _show_skills(skills: list[Any]) -> None:
    table = Table(title=f"Skills ({len(skills)})", border_style="magenta", show_lines=False)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Aliases", style="dim cyan", no_wrap=True)
    table.add_column("Description", overflow="fold")
    table.add_column("Source", style="dim", no_wrap=True)

    for skill in skills:
        aliases = ", ".join("/" + a for a in skill.aliases) if skill.aliases else "-"
        table.add_row(
            f"/{skill.name}",
            aliases,
            skill.description or "-",
            _skill_source_label(skill.source_path),
        )

    console.print(table)


def _skill_source_label(path: Path) -> str:
    parts = path.parts
    if "builtin" in parts:
        return "builtin"
    if path.parent.name == "skills":
        if ".zwis" in parts:
            return "project"
        if ".zwis" not in parts and "workspaces" in parts:
            return "workspace"
    return path.parent.name or "."


def _show_graph(args: str) -> None:
    """Display the knowledge graph stats or architecture map."""
    try:
        from ..app_paths import app_home
        from ..graph.storage import load_graph, load_meta, graph_exists

        cwd = os.getcwd()
        ah = app_home(cwd)

        if not graph_exists(ah):
            console.print(
                "[yellow]No knowledge graph found.[/] Run [bold]zwis learn[/] to build one."
            )
            return

        graph = load_graph(ah)
        if graph is None:
            console.print("[red]Failed to load graph.[/]")
            return

        meta = load_meta(ah)
        subcommand = (args or "stats").strip().lower()

        if subcommand in ("map", "arch", "architecture"):
            from ..graph.visualizer import GraphVisualizer
            viz = GraphVisualizer(graph)
            console.print(viz.architecture_map())
        else:
            from ..graph.visualizer import GraphVisualizer
            viz = GraphVisualizer(graph)
            console.print(viz.stats_summary())
            if meta.get("frameworks"):
                console.print(f"\n[dim]Frameworks:[/] {', '.join(meta['frameworks'])}")
            built = meta.get("built_at")
            if built:
                import datetime
                ts = datetime.datetime.fromtimestamp(built).strftime("%Y-%m-%d %H:%M")
                console.print(f"[dim]Last built:[/] {ts}")
            console.print("\n[dim]Use /graph map  for the architecture map[/]")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Graph error:[/] {exc}")


def _show_knowledge(topic: str) -> None:
    """List or view knowledge files."""
    try:
        from ..app_paths import knowledge_dir

        cwd = os.getcwd()
        kdir = knowledge_dir(cwd)

        if not kdir.exists():
            console.print(
                "[yellow]No knowledge files found.[/] Run [bold]zwis learn[/] to generate them."
            )
            return

        topic = (topic or "").strip()
        if not topic:
            # List all knowledge files
            files = sorted(kdir.glob("*.md"))
            if not files:
                console.print("[dim]No knowledge files in .zwis/knowledge/[/]")
                return
            rows = "\n".join(f"  • **{f.name}**" for f in files)
            console.print(Markdown(
                f"**Knowledge files in .zwis/knowledge/** ({len(files)})\n\n{rows}\n\n"
                "Use `/knowledge <filename>` to read a file."
            ))
        else:
            # Find matching file
            name = topic if topic.endswith(".md") else f"{topic}.md"
            path = kdir / name
            if not path.exists():
                # Try partial match
                matches = list(kdir.glob(f"*{topic}*.md"))
                if not matches:
                    console.print(f"[red]No knowledge file matching '{topic}'[/]")
                    return
                path = matches[0]
            content = path.read_text(encoding="utf-8", errors="replace")
            console.print(Markdown(content))
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Knowledge error:[/] {exc}")


def _save_session(session: SessionState) -> None:
    store = sessions_dir(os.getcwd())
    store.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    path = store / f"session-{ts}.json"
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    console.print(f"[dim]Session saved → {path}[/]")


# ---------------------------------------------------------------------------
# Tab completion
# ---------------------------------------------------------------------------

def _setup_completion(commands: list[str]) -> None:
    """Register readline tab completion for slash commands."""
    try:
        import readline

        slash_commands = sorted(set(commands), key=str.lower)

        def completer(text: str, state: int) -> str | None:
            buffer = readline.get_line_buffer()
            begidx = readline.get_begidx()

            if begidx == 0:
                needle = text.lower()
                options = [c for c in slash_commands if c.lower().startswith(needle)]
            else:
                options = _path_completion_options(buffer, text)
            return options[state] if state < len(options) else None

        readline.set_completer(completer)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("set show-all-if-ambiguous on")
        readline.parse_and_bind("set completion-ignore-case on")
        readline.parse_and_bind("set mark-directories on")
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass


def _path_completion_options(buffer: str, text: str) -> list[str]:
    command = buffer.strip().split(None, 1)[0] if buffer.strip() else ""
    file_commands = {
        "/graph-review", "/gr", "/greview",
        "/safe-edit", "/se", "/safeedit",
        "/trace-flow", "/tf", "/traceflow",
        "/review", "/r",
        "/knowledge",
    }
    if command not in file_commands:
        return []

    prefix = text or ""
    path = Path(prefix).expanduser()
    if prefix.endswith("/"):
        base = path
        fragment = ""
    else:
        base = path.parent if prefix else Path(".")
        fragment = path.name

    base = Path(".") if str(base) == "" else base
    try:
        entries = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []

    options: list[str] = []
    for entry in entries:
        name = entry.name
        if fragment and not name.lower().startswith(fragment.lower()):
            continue
        candidate = str((base / name).as_posix()) if str(base) != "." else name
        if entry.is_dir():
            candidate += "/"
        options.append(candidate)
    return options


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def run_repl(
    session_config: SessionConfig,
    llm: Any,
    cwd: str | None = None,
    hook_runner: Any = None,   # HookRunner | None
    agent_config: Any = None,  # AgentConfig | None (for /config display)
    initial_session: SessionState | None = None,  # for --resume/--continue
    with_logs: bool = False,
) -> int:
    """
    Start the interactive REPL.

    Args:
        session_config:  Pre-built session configuration.
        llm:             LangChain ChatModel (already constructed).
        cwd:             Working directory for tool execution.
        hook_runner:     Optional lifecycle hook runner.
        agent_config:    Optional full config for /config display.
        initial_session: Pre-existing session to resume (--continue/--resume).
        with_logs:       Also write all terminal output to .zwis/zwis.log.

    Returns:
        Exit code (0 = normal exit).
    """
    _setup_readline()

    cwd = cwd or os.getcwd()

    if with_logs:
        _enable_log_file(cwd)

    # Discover skills and memory
    try:
        from ..skills import SkillRegistry
        skill_registry = SkillRegistry.discover(cwd)
    except Exception:  # noqa: BLE001
        skill_registry = None

    try:
        from ..memory import MemoryManager
        memory_manager = MemoryManager.default()
    except Exception:  # noqa: BLE001
        memory_manager = None

    # Build tool registry and orchestrator
    registry = default_registry()

    try:
        from ..mcp import register_mcp_tools
        register_mcp_tools(registry, cwd)
    except Exception:  # noqa: BLE001
        pass

    # Register graph tools if a knowledge graph exists for this project
    try:
        from ..tools.graph_tools import register_graph_tools
        register_graph_tools(registry, cwd)
    except Exception:  # noqa: BLE001
        pass

    orchestrator = ToolOrchestrator(registry)

    # Build session
    if initial_session is not None:
        session = initial_session
        session.config = session_config
        session.cwd = cwd
    else:
        session = SessionState.new(session_config, cwd=cwd)

    provider = getattr(llm, "model_name", session_config.model)
    provider_name = agent_config.provider if agent_config else "unknown"

    _print_banner(session_config.model, provider_name)

    if initial_session is not None:
        console.print(
            f"[dim]Resumed session {session.id[:16]}… "
            f"({session.turn_count} turns, {len(session.messages)} messages)[/]\n"
        )

    # Tab completion
    builtin_cmds = [
        "/help", "/tools", "/session", "/clear", "/save", "/exit", "/quit",
        "/compact", "/memory", "/skills", "/cost", "/status", "/config",
        "/plan", "/auto", "/graph", "/knowledge", "/game/flappy-bird",
    ]
    skill_cmds = []
    if skill_registry is not None:
        skill_cmds = ["/" + s.name for s in skill_registry.all()]
        for s in skill_registry.all():
            skill_cmds.extend("/" + a for a in s.aliases)
    _setup_completion(builtin_cmds + skill_cmds)

    # Session start hook
    if hook_runner is not None:
        try:
            from ..hooks import HookEvent
            asyncio.run(hook_runner.run(
                HookEvent.SESSION_START,
                session_id=session.id,
                cwd=cwd,
            ))
        except Exception:  # noqa: BLE001
            pass

    try:
        asyncio.run(_repl_loop(
            session, llm, registry, orchestrator,
            skill_registry=skill_registry,
            memory_manager=memory_manager,
            agent_config=agent_config,
            provider=provider_name,
            hook_runner=hook_runner,
        ))
    except KeyboardInterrupt:
        pass

    # Session end hook
    if hook_runner is not None:
        try:
            from ..hooks import HookEvent
            asyncio.run(hook_runner.run(
                HookEvent.SESSION_END,
                session_id=session.id,
                cwd=cwd,
            ))
        except Exception:  # noqa: BLE001
            pass

    _print_exit_stats(session)

    # Close log file if open.
    global _log_file
    if _log_file is not None:
        _log_file.write(f"\n{'=' * 80}\nSession ended.\n{'=' * 80}\n")
        _log_file.close()
        _log_file = None

    return 0


async def _repl_loop(
    session: SessionState,
    llm: Any,
    registry: ToolRegistry,
    orchestrator: ToolOrchestrator,
    skill_registry: Any,
    memory_manager: Any,
    agent_config: Any,
    provider: str,
    hook_runner: Any = None,
) -> None:
    last_interrupt: float = 0.0

    while True:
        text = _read_multiline("> ")

        if text is None:  # EOF
            break

        if text is _CTRL_C:
            now = time.time()
            if now - last_interrupt < 1.5:
                break
            last_interrupt = now
            console.print("[dim](Press Ctrl+C again within 1.5s to exit)[/]")
            continue

        last_interrupt = 0.0

        if not text:
            continue

        if text.lower() in ("q", "exit", "quit", "/exit", "/quit"):
            break

        if text.startswith("/"):
            result = _handle_slash(
                text,
                session,
                registry,
                skill_registry,
                memory_manager,
                agent_config,
                provider,
            )
            if result is False:
                break
            if result is True:
                continue
            # result is a string → inject as a user message
            text = str(result)

        session.push_human(text)
        accumulator: list[str] = []
        status = console.status("[dim]Thinking...[/]", spinner="dots")
        status.start()
        status_stopped = False

        def stop_status() -> None:
            nonlocal status_stopped
            if not status_stopped:
                status.stop()
                status_stopped = True

        on_event = _make_event_callback(accumulator, stop_status=stop_status)

        try:
            await run_agent(
                session, llm, registry, orchestrator,
                on_event=on_event,
                hook_runner=hook_runner,
            )
        except KeyboardInterrupt:
            stop_status()
            console.print("\n[dim]Interrupted.[/]")
        except Exception as exc:  # noqa: BLE001
            stop_status()
            err_console.print(f"[red]Error:[/] {exc}")
        else:
            stop_status()

        # Budget check after each turn
        budget = _get_budget()
        if budget is not None:
            _, _, total_cost = _calc_cost(session)
            if total_cost >= budget:
                console.print(
                    f"[red bold]Budget limit reached (${total_cost:.5f} >= ${budget:.2f}). "
                    "Session ended.[/]"
                )
                break


# ---------------------------------------------------------------------------
# Exit stats + readline
# ---------------------------------------------------------------------------

def _print_exit_stats(session: SessionState) -> None:
    inp_rate, out_rate = _get_cost_rates()
    cost_str = ""
    if inp_rate > 0 or out_rate > 0:
        _, _, total_cost = _calc_cost(session)
        budget = _get_budget()
        cost_str = f", est. cost ${total_cost:.5f}"
        if budget is not None:
            cost_str += f" / ${budget:.2f} budget"
    console.print(
        f"\n[dim]Session ended — "
        f"{session.turn_count} turns, "
        f"{session.total_input_tokens:,} input tokens, "
        f"{session.total_output_tokens:,} output tokens{cost_str}[/]"
    )


def _setup_readline() -> None:
    try:
        import readline
        history = history_file(os.getcwd())
        history.parent.mkdir(parents=True, exist_ok=True)
        try:
            readline.read_history_file(history)
        except FileNotFoundError:
            legacy = Path.home() / ".zwischenzug_history"
            if legacy.exists():
                readline.read_history_file(legacy)
        readline.parse_and_bind("set enable-keypad on")
        readline.parse_and_bind("set show-all-if-ambiguous on")
        readline.parse_and_bind("set completion-ignore-case on")
        import atexit
        atexit.register(readline.write_history_file, history)
    except ImportError:
        pass  # readline not available on Windows


# ---------------------------------------------------------------------------
# Single-shot (non-interactive) run
# ---------------------------------------------------------------------------

def run_single(
    prompt: str,
    session_config: SessionConfig,
    llm: Any,
    output_format: str = "text",
    cwd: str | None = None,
    hook_runner: Any = None,
) -> int:
    """
    Execute a single non-interactive prompt and print the result.

    Args:
        prompt:         The user's prompt.
        session_config: Session configuration.
        llm:            LangChain ChatModel.
        output_format:  "text" | "json"
        cwd:            Working directory.
        hook_runner:    Optional lifecycle hook runner.

    Returns:
        Exit code.
    """

    cwd = cwd or os.getcwd()
    registry = default_registry()
    try:
        from ..mcp import register_mcp_tools
        register_mcp_tools(registry, cwd)
    except Exception:  # noqa: BLE001
        pass
    orchestrator = ToolOrchestrator(registry)
    session = SessionState.new(session_config, cwd=cwd)
    session.push_human(prompt)

    text_parts: list[str] = []
    tool_events: list[dict] = []

    def on_event(event: QueryEvent) -> None:
        if isinstance(event, ThinkingDelta):
            if output_format == "text":
                print(f"\n🧠 Thinking:\n{event.text}\n", flush=True)
        elif isinstance(event, TextDelta):
            text_parts.append(event.text)
            if output_format == "text":
                print(event.text, end="", flush=True)
        elif isinstance(event, ToolUseStart) and output_format == "text":
            print(f"\n⚡ {event.name}", flush=True)
        elif isinstance(event, ToolResultEvent):
            tool_events.append({
                "tool_use_id": event.tool_use_id,
                "content": event.content,
                "is_error": event.is_error,
            })
            if output_format == "text":
                icon = "✅" if not event.is_error else "❌"
                print(f"{icon} ({len(event.content)} chars)", flush=True)

    try:
        asyncio.run(run_agent(
            session, llm, registry, orchestrator,
            on_event=on_event,
            hook_runner=hook_runner,
        ))
    except Exception as exc:  # noqa: BLE001
        if output_format == "json":
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"\nError: {exc}", file=sys.stderr)
        return 1

    if output_format == "json":
        print(json.dumps({
            "session_id": session.id,
            "text": "".join(text_parts),
            "tool_events": tool_events,
            "input_tokens": session.total_input_tokens,
            "output_tokens": session.total_output_tokens,
        }))
    elif output_format == "text":
        print()  # trailing newline

    return 0

"""
Zwischenzug CLI — entry point.

Sub-commands
────────────
  Agent (real AI):
    chat        Interactive multi-turn REPL
    run         Single non-interactive prompt

  Catalog / Discovery:
    summary     Workspace overview
    manifest    Python module manifest
    completion  Emit shell completion script
    commands    List known commands
    tools       List known tools
    route       Score-match a prompt against commands/tools
    bootstrap   Route + execute + one turn
    turn-loop   Simulated multi-turn (catalog only)
    show-command / show-tool
    exec-command / exec-tool

  Session:
    flush-transcript   Bootstrap and save session
    load-session       Load and display a saved session
    sessions           List all saved sessions

  Modes (connection stubs):
    remote-mode / ssh-mode / teleport-mode / direct-connect-mode / deep-link-mode

  Reports:
    parity-audit / setup-report / command-graph / tool-pool / bootstrap-graph / subsystems

    Animated UI:
    zwischenzug   Animated logo + LangChain response

  Games:
    game         Play built-in terminal games
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .mcp import MCPServerConfig, add_server as add_mcp_server, get_server as get_mcp_server, list_servers as list_mcp_servers, remove_server as remove_mcp_server
from .catalog import (
    build_port_manifest,
    execute_command,
    execute_tool,
    get_command,
    get_commands,
    get_tool,
    get_tools,
    load_session,
    QueryEnginePort,
    PortRuntime,
    render_command_index,
    render_tool_index,
    run_parity_audit,
    bootstrap_graph,
    command_graph,
    setup_report,
    tool_pool,
)
from .catalog.session_store import list_sessions, latest_session_id
from .modes import run_deep_link, run_direct_connect, run_remote_mode, run_ssh_mode, run_teleport_mode
from .permissions import ToolPermissionContext
from .ui import load_zwischenzug_config, run_zwischenzug


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _add_agent_args(p: argparse.ArgumentParser) -> None:
    """Attach shared LLM/session flags to a sub-parser."""
    p.add_argument("--provider", help="LiteLLM provider slug (e.g. openai, anthropic, ollama, azure, ...)")
    p.add_argument("--model", help="Model identifier or alias")
    p.add_argument("--system", metavar="PROMPT", help="System prompt override")
    p.add_argument("--permission", choices=["auto", "interactive", "deny"],
                   dest="permission_mode", help="Tool permission mode")
    p.add_argument("--temperature", type=float)
    p.add_argument("--max-tokens", type=int)
    p.add_argument("--max-retries", type=int)
    p.add_argument("--include-reasoning", dest="include_reasoning", action="store_true",
                   help="Ask supported models/providers to include reasoning output")
    p.add_argument("--no-include-reasoning", dest="include_reasoning", action="store_false",
                   help="Disable reasoning output for supported models/providers")
    p.add_argument("--reasoning-effort", choices=["none", "default", "low", "medium", "high"],
                   help="Reasoning effort for supported models/providers")
    p.add_argument("--reasoning-format",
                   help="Provider-specific reasoning format for supported models/providers")
    p.set_defaults(include_reasoning=None)
    p.add_argument("--max-turns", type=int)
    p.add_argument("--context-window", type=int, metavar="TOKENS",
                   help="Model context window size in tokens (e.g. 131072 for 128k)")


def _build_clean_parser() -> argparse.ArgumentParser:
    """Build a fresh parser without duplicate subcommand registrations."""
    parser = argparse.ArgumentParser(
        prog="zwischenzug",
        description="Zwischenzug — AI coding agent powered by LangChain",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize .env interactively (provider, model, API key).",
    )
    parser.add_argument(
        "--with-logs",
        action="store_true",
        dest="with_logs",
        help="Also log all terminal output to .zwis/zwis.log.",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    # Agent
    chat_p = sub.add_parser("chat", help="Interactive REPL (multi-turn agent)")
    _add_agent_args(chat_p)
    chat_p.add_argument("--continue", "-c", action="store_true", dest="cont",
                        help="Continue the most recent session")
    chat_p.add_argument("--resume", "-r", metavar="ID", dest="resume_id",
                        help="Resume a specific session by ID")
    chat_p.add_argument("--plan", action="store_true",
                        help="Start in plan mode (read-only, no writes)")
    chat_p.add_argument("--with-logs", action="store_true", dest="with_logs",
                        help="Also log all terminal output to .zwis/zwis.log")

    run_p = sub.add_parser("run", help="Single non-interactive prompt")
    _add_agent_args(run_p)
    run_p.add_argument("prompt", nargs="?", default=None)
    run_p.add_argument("--print", dest="print_prompt", metavar="PROMPT")
    run_p.add_argument("--output-format", choices=["text", "json"], default="text")

    # Discovery
    sub.add_parser("summary")
    sub.add_parser("manifest")
    completion_p = sub.add_parser("completion", help="Emit shell completion script")
    completion_p.add_argument("shell", choices=["bash"], nargs="?", default="bash")
    sub.add_parser("parity-audit")
    sub.add_parser("setup-report")
    sb_p = sub.add_parser("setup-browser", help="Install Playwright Chromium + start VNC stack")
    sb_p.add_argument(
        "--port", type=int, default=6080,
        help="noVNC port to expose the browser on (default: 6080)",
    )
    sb_p.add_argument(
        "--no-vnc", action="store_true", dest="no_vnc",
        help="Skip starting the VNC stack after install",
    )
    sub.add_parser("command-graph")
    sub.add_parser("tool-pool")
    sub.add_parser("bootstrap-graph")

    sl = sub.add_parser("subsystems")
    sl.add_argument("--limit", type=int, default=32)

    cmd_p = sub.add_parser("commands")
    cmd_p.add_argument("--limit", type=int, default=20)
    cmd_p.add_argument("--query")
    cmd_p.add_argument("--no-plugin-commands", action="store_true")
    cmd_p.add_argument("--no-skill-commands", action="store_true")

    tl_p = sub.add_parser("tools")
    tl_p.add_argument("--limit", type=int, default=20)
    tl_p.add_argument("--query")
    tl_p.add_argument("--simple-mode", action="store_true")
    tl_p.add_argument("--no-mcp", action="store_true")
    tl_p.add_argument("--deny-tool", action="append", default=[])
    tl_p.add_argument("--deny-prefix", action="append", default=[])

    mcp_p = sub.add_parser("mcp", help="Manage MCP servers")
    mcp_p.set_defaults(command="mcp")
    mcp_sub = mcp_p.add_subparsers(dest="mcp_command", required=True)

    mcp_list = mcp_sub.add_parser("list", help="List configured MCP servers")
    mcp_list.add_argument("--json", action="store_true", dest="json_output")

    mcp_get = mcp_sub.add_parser("get", help="Show one configured MCP server")
    mcp_get.add_argument("name")
    mcp_get.add_argument("--json", action="store_true", dest="json_output")

    mcp_add = mcp_sub.add_parser("add", help="Add or update an MCP server")
    mcp_add.add_argument("name")
    mcp_add.add_argument("--transport", required=True, choices=["stdio", "http", "sse"])
    mcp_add.add_argument("--scope", choices=["project", "user"], default="project")
    mcp_add.add_argument("--header", action="append", default=[])
    mcp_add.add_argument("--env", action="append", default=[])
    mcp_add.add_argument("--cwd", dest="server_cwd")
    mcp_add.add_argument("--timeout", type=float, default=30.0)
    mcp_add.add_argument("--sse-read-timeout", type=float, default=300.0)
    mcp_add.add_argument("--url")
    mcp_add.add_argument("--command", dest="server_command")
    mcp_add.add_argument("--arg", action="append", default=[], dest="server_args")

    mcp_remove = mcp_sub.add_parser("remove", help="Remove an MCP server")
    mcp_remove.add_argument("name")
    mcp_remove.add_argument("--scope", choices=["project", "user"], default="project")

    rt_p = sub.add_parser("route")
    rt_p.add_argument("prompt")
    rt_p.add_argument("--limit", type=int, default=5)

    bs_p = sub.add_parser("bootstrap")
    bs_p.add_argument("prompt")
    bs_p.add_argument("--limit", type=int, default=5)

    lp_p = sub.add_parser("turn-loop")
    lp_p.add_argument("prompt")
    lp_p.add_argument("--limit", type=int, default=5)
    lp_p.add_argument("--max-turns", type=int, default=3)

    ft_p = sub.add_parser("flush-transcript")
    ft_p.add_argument("prompt")

    ls_p = sub.add_parser("load-session")
    ls_p.add_argument("session_id")

    sub.add_parser("sessions", help="List all saved sessions")

    for mode in ("remote-mode", "ssh-mode", "teleport-mode", "direct-connect-mode", "deep-link-mode"):
        p = sub.add_parser(mode)
        p.add_argument("target")

    sc = sub.add_parser("show-command")
    sc.add_argument("name")
    st_p = sub.add_parser("show-tool")
    st_p.add_argument("name")
    ec = sub.add_parser("exec-command")
    ec.add_argument("name")
    ec.add_argument("prompt")
    et = sub.add_parser("exec-tool")
    et.add_argument("name")
    et.add_argument("payload")

    z_p = sub.add_parser("zwischenzug", help="Single-shot LangChain response")
    z_p.add_argument("--message")
    z_p.add_argument("--provider")
    z_p.add_argument("--model")
    z_p.add_argument("--temperature", type=float)
    z_p.add_argument("--max-tokens", type=int)
    z_p.add_argument("--max-retries", type=int)
    z_p.add_argument("--include-reasoning", dest="include_reasoning", action="store_true")
    z_p.add_argument("--no-include-reasoning", dest="include_reasoning", action="store_false")
    z_p.add_argument("--reasoning-effort", choices=["none", "default", "low", "medium", "high"])
    z_p.add_argument("--reasoning-format")
    z_p.set_defaults(include_reasoning=None)

    game_p = sub.add_parser("game", help="Play a built-in terminal game")
    game_p.add_argument("name", choices=["flappy-bird"], help="Game to launch")
    game_p.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help=argparse.SUPPRESS,
    )

    # ── Graph Intelligence ───────────────────────────────────────────────────
    learn_p = sub.add_parser(
        "learn",
        help="Scan repository and build the knowledge graph + knowledge files",
    )
    learn_p.add_argument(
        "path", nargs="?", default=None,
        help="Directory to scan (default: current working directory)",
    )
    learn_p.add_argument(
        "--fetch-docs", action="store_true", dest="fetch_docs",
        help="Also fetch official framework documentation into .zwis/docs/",
    )
    learn_p.add_argument(
        "--force", action="store_true",
        help="Force full rebuild even if graph is already up to date",
    )

    map_p = sub.add_parser("map", help="Show ASCII architecture map of the repository")
    map_p.add_argument(
        "--format", choices=["ascii", "json"], default="ascii",
        help="Output format (default: ascii)",
    )
    map_p.add_argument("--max-files", type=int, default=40, dest="max_files")

    explain_p = sub.add_parser(
        "explain",
        help="Explain a module, class, or function using the knowledge graph",
    )
    explain_p.add_argument(
        "symbol",
        help="Symbol to explain: file path, class name, or function name",
    )

    trace_p = sub.add_parser(
        "trace",
        help="Trace execution flow from a function or entry point",
    )
    trace_p.add_argument("flow", help="Function or entry point to trace from")
    trace_p.add_argument("--depth", type=int, default=5, help="Max call depth (default: 5)")

    impact_p = sub.add_parser(
        "impact-change",
        help="Show which code would be affected by changing a symbol",
    )
    impact_p.add_argument("symbol", help="Symbol (class/function/method) to analyse")
    impact_p.add_argument("--depth", type=int, default=5)

    knowledge_p = sub.add_parser(
        "knowledge",
        help="List or view knowledge files in .zwis/knowledge/",
    )
    knowledge_p.add_argument(
        "topic", nargs="?", default=None,
        help="Knowledge file to view (e.g. 'architecture', 'INDEX')",
    )

    return parser


# ---------------------------------------------------------------------------
# Agent command helpers
# ---------------------------------------------------------------------------

def _build_agent(args: argparse.Namespace):
    """Resolve config → build LLM → return (AgentConfig, llm, session_cfg)."""
    from .cli.config import resolve_config
    from .provider import build_llm, provider_env_hint, resolve_model

    # --plan forces deny permission mode
    permission_mode = getattr(args, "permission_mode", None)
    if getattr(args, "plan", False):
        permission_mode = "deny"

    cfg = resolve_config(
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        temperature=getattr(args, "temperature", None),
        max_tokens=getattr(args, "max_tokens", None),
        max_retries=getattr(args, "max_retries", None),
        include_reasoning=getattr(args, "include_reasoning", None),
        reasoning_effort=getattr(args, "reasoning_effort", None),
        reasoning_format=getattr(args, "reasoning_format", None),
        permission_mode=permission_mode,
        system_prompt=getattr(args, "system", None),
        max_turns=getattr(args, "max_turns", None),
        context_window=getattr(args, "context_window", None),
        skip_wizard=True,
    )

    # Expand model alias before building LLM
    cfg.model = resolve_model(cfg.provider, cfg.model)

    try:
        llm = build_llm(
            cfg.provider,
            cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            max_retries=cfg.max_retries,
            include_reasoning=cfg.include_reasoning,
            reasoning_effort=cfg.reasoning_effort,
            reasoning_format=cfg.reasoning_format,
            streaming=cfg.streaming,
        )
    except ImportError as exc:
        print(f"Error building LLM: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        message = str(exc)
        if "API_KEY" in message:
            print("Error building LLM: Missing provider credentials.", file=sys.stderr)
            print("Set your env variables, then rerun:", file=sys.stderr)
            print(f"  export ZWISCHENZUG_PROVIDER={cfg.provider}", file=sys.stderr)
            print(f"  export ZWISCHENZUG_MODEL={cfg.model}", file=sys.stderr)
            hint = provider_env_hint(cfg.provider)
            if hint:
                print(f"  export {hint.split(' or ')[0]}=your_key_here", file=sys.stderr)
            else:
                print("  export <PROVIDER>_API_KEY=your_key_here", file=sys.stderr)
        else:
            print(f"Error building LLM: {exc}", file=sys.stderr)
        sys.exit(1)

    from .core.session import SessionConfig
    from .compact import TokenBudget as TB

    tb_kwargs: dict = {"max_output_tokens": cfg.max_tokens}
    if cfg.context_window > 0:
        tb_kwargs["context_window"] = cfg.context_window

    session_cfg = SessionConfig(
        model=cfg.model,
        system_prompt=cfg.system_prompt,
        max_turns=cfg.max_turns,
        permission_mode=cfg.permission_mode,
        token_budget=TB(**tb_kwargs),
    )
    return cfg, llm, session_cfg


def _parse_kv_flags(items: list[str], *, flag_name: str, delimiter: str = "=") -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in items:
        text = str(item).strip()
        if delimiter in text:
            key, value = text.split(delimiter, 1)
        elif ":" in text and delimiter != ":":
            key, value = text.split(":", 1)
        else:
            raise ValueError(f"Invalid {flag_name} value: {item!r}")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid {flag_name} key: {item!r}")
        parsed[key] = value
    return parsed


def _normalize_argv(argv: list[str] | None) -> list[str] | None:
    if argv is None:
        return None

    normalized = list(argv)

    # Support Claude-style stdio syntax:
    #   zwis mcp add name --transport stdio -- npx -y package ...
    if len(normalized) >= 5 and normalized[:3] == ["mcp", "add", normalized[2]] and "--" in normalized:
        dash_index = normalized.index("--")
        if dash_index + 1 < len(normalized):
            command = normalized[dash_index + 1]
            args = normalized[dash_index + 2:]
            normalized = normalized[:dash_index]
            if "--command" not in normalized:
                normalized.extend(["--command", command])
            for value in args:
                normalized.extend(["--arg", value])

    # Make `zwis mcp add ... --arg -y` work by rewriting it to `--arg=-y`
    i = 0
    while i < len(normalized) - 1:
        if normalized[i] == "--arg" and normalized[i + 1].startswith("-"):
            normalized[i] = f"--arg={normalized[i + 1]}"
            del normalized[i + 1]
            continue
        i += 1

    return normalized


def _build_hook_runner(cwd: str) -> "HookRunner":
    """Build a HookRunner from project/user settings.json."""
    try:
        from .hooks import HookRunner
        return HookRunner.from_settings(cwd)
    except Exception:  # noqa: BLE001
        from .hooks import HookRunner
        return HookRunner.empty()


def _restore_session(session_id: str, session_cfg) -> "SessionState | None":
    """Load a saved session and restore it as a SessionState."""
    import json
    from pathlib import Path

    try:
        from .catalog.session_store import load_session as _load
        stored = _load(session_id)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Could not load session {session_id!r}: {exc}", file=sys.stderr)
        return None

    # The stored session has serialized messages as strings — try to find the raw JSON
    from .app_paths import sessions_dir
    cwd = os.getcwd()
    path = sessions_dir(cwd) / f"{session_id}.json"
    if not path.exists():
        print(f"Session file not found: {path}", file=sys.stderr)
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    from .core.session import SessionState
    return SessionState.from_dict(data, config=session_cfg)


# ---------------------------------------------------------------------------
# Browser setup command handler
# ---------------------------------------------------------------------------

def _cmd_setup_browser(port: int = 6080, no_vnc: bool = False) -> int:
    """zwis setup-browser — mirrors Dockerfile: apt-get update → install packages
    → playwright install --with-deps chromium → start Xvfb + VNC + noVNC."""
    import os
    import shutil
    import subprocess
    import sys
    import time

    # Use sudo if not already root.
    need_sudo = os.geteuid() != 0

    def _run(cmd: list[str], sudo: bool = False) -> int:
        full = (["sudo"] if sudo and shutil.which("sudo") else []) + cmd
        return subprocess.run(full).returncode

    # ── Step 1: remove broken apt repos, then update ────────────────────────
    # Broken/unauthenticated repos (e.g. yarn) cause playwright --with-deps to
    # fail. Remove them before running apt so the rest of the install is clean.
    import glob as _glob
    broken_patterns = [
        "/etc/apt/sources.list.d/yarn*.list",
        "/etc/apt/sources.list.d/*yarn*.list",
    ]
    for pattern in broken_patterns:
        for path in _glob.glob(pattern):
            _run(["rm", "-f", path], sudo=need_sudo)

    print("Updating package lists…")
    _run(["apt-get", "update", "-qq"], sudo=need_sudo)

    # ── Step 2: system packages (mirrors: apt-get install xvfb x11vnc …) ────
    # apt packages vs. actual binary/path checks:
    #   xvfb    → binary Xvfb  (capital X)
    #   x11vnc  → binary x11vnc
    #   novnc   → no binary; web files at /usr/share/novnc
    #   websockify → binary websockify
    apt_packages = ["xvfb", "x11vnc", "novnc", "websockify"]

    def _vnc_present() -> bool:
        return (
            bool(shutil.which("Xvfb"))
            and bool(shutil.which("x11vnc"))
            and os.path.isdir("/usr/share/novnc")
            and bool(shutil.which("websockify"))
        )

    if _vnc_present():
        print("System packages already installed.")
    else:
        print(f"Installing: {' '.join(apt_packages)}")
        apt_cmd = ["apt-get", "install", "-y", "--no-install-recommends"] + apt_packages
        if _run(apt_cmd, sudo=need_sudo) != 0:
            print(
                f"  Could not install — try manually:\n"
                f"    sudo apt-get install -y {' '.join(apt_packages)}\n"
                "  (VNC is optional — browser tools work headlessly without it.)"
            )

    # ── Step 3: playwright install --with-deps chromium ─────────────────────
    print("\nInstalling Playwright Chromium…")
    rc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"]
    ).returncode
    if rc != 0:
        print("  --with-deps failed — installing browser binary only…")
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])

    # ── Step 4: start VNC stack (mirrors: Dockerfile CMD) ───────────────────
    vnc_ok = _vnc_present()

    if not vnc_ok or no_vnc:
        print("\nChromium ready. Browser tools will run headlessly.")
        print("  zwis chat")
        return 0

    display = ":99"
    vnc_port = 5901
    print(f"\nStarting VNC stack (browser visible at http://localhost:{port}) …")

    # Xvfb :99 -screen 0 1280x800x24
    subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1280x800x24"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    time.sleep(0.5)

    # x11vnc -display :99 -forever -nopw -rfbport 5901
    subprocess.Popen(
        ["x11vnc", "-display", display, "-forever", "-nopw", "-rfbport", str(vnc_port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    time.sleep(0.3)

    # websockify --web /usr/share/novnc <port> localhost:5901
    novnc_web = "/usr/share/novnc"
    subprocess.Popen(
        ["websockify", "--web", novnc_web, str(port), f"localhost:{vnc_port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    time.sleep(0.3)

    os.environ["DISPLAY"] = display
    print(f"  Xvfb on {display}, x11vnc on :{vnc_port}, noVNC on :{port}")
    print(f"  Open http://localhost:{port}/vnc.html to watch the browser")
    print(f"\nStarting zwis (DISPLAY={display})…\n")

    # Exec into zwis — mirrors: DISPLAY=:99 zwischenzug
    os.execvp(sys.argv[0], [sys.argv[0]])
    return 0  # unreachable


# ---------------------------------------------------------------------------
# Graph intelligence command handlers
# ---------------------------------------------------------------------------

def _cmd_learn(args: "argparse.Namespace", cwd: str) -> int:
    """zwis learn — scan repo, build knowledge graph, generate knowledge files."""
    import asyncio
    import time
    from pathlib import Path

    target = getattr(args, "path", None) or cwd
    fetch_docs = getattr(args, "fetch_docs", False)
    force = getattr(args, "force", False)

    from .graph import GraphEngine
    from .graph.storage import (
        save_graph, save_meta, make_meta,
        load_graph, load_meta, graph_exists, stale_files,
    )
    from .app_paths import app_home, ensure_app_home
    from .learning import LearningEngine

    ensure_app_home(target)
    ah = app_home(target)

    # Compute current file mtimes
    target_path = Path(target)
    current_mtimes: dict[str, float] = {}
    for f in target_path.rglob("*.py"):
        try:
            rel = str(f.relative_to(target_path))
            current_mtimes[rel] = f.stat().st_mtime
        except OSError:
            pass

    # ── Incremental mode ─────────────────────────────────────────────
    if not force and graph_exists(ah):
        stale = stale_files(ah, current_mtimes)
        if not stale:
            print("Graph is up to date. Use --force to rebuild.")
            return 0

        print(f"Incremental update: {len(stale)} file(s) changed\n")
        graph = load_graph(ah)
        if graph is None:
            print("Failed to load existing graph — falling back to full rebuild.")
        else:
            engine = LearningEngine(target, graph)
            for rel in stale:
                try:
                    engine.update_file(rel)
                    print(f"  Updated: {rel}")
                except Exception as exc:
                    print(f"  Error updating {rel}: {exc}")

            save_graph(graph, ah)
            meta = load_meta(ah)
            meta["file_mtimes"] = current_mtimes
            meta["built_at"] = time.time()
            meta.update(graph.stats())
            save_meta(meta, ah)

            stats = graph.stats()
            print()
            print("─" * 50)
            print(f"  Graph nodes        : {stats.get('total_nodes', 0)}")
            print(f"  Graph edges        : {stats.get('total_edges', 0)}")
            print(f"  Line references    : {stats.get('total_references', 0)}")
            print()
            return 0

    # ── Full rebuild ─────────────────────────────────────────────────
    print(f"Learning repository at: {target}")
    print()

    graph = GraphEngine()

    def on_progress(msg: str) -> None:
        print(f"  {msg}")

    result = asyncio.run(
        LearningEngine(target, graph).learn(
            on_progress=on_progress,
            fetch_docs=fetch_docs,
        )
    )

    # Persist graph + metadata
    save_graph(graph, ah)
    save_meta(make_meta(graph, current_mtimes, result.frameworks, target), ah)

    print()
    print("─" * 50)
    print(f"  Files parsed       : {result.parsed_files} / {result.total_files}")
    print(f"  Graph nodes        : {result.total_nodes}")
    print(f"  Graph edges        : {result.total_edges}")
    print(f"  Line references    : {result.total_references}")
    print(f"  Frameworks         : {', '.join(result.frameworks) or 'none detected'}")
    print(f"  Knowledge files    : {len(result.knowledge_files)}")
    if fetch_docs:
        print(f"  Doc files          : {len(result.doc_files)}")
    if result.errors:
        print(f"  Errors             : {len(result.errors)}")
    print(f"  Elapsed            : {result.elapsed_seconds:.1f}s")
    print()
    print(f"  Graph saved to     : {ah / 'graph' / 'graph.json'}")
    print(f"  Knowledge files in : {ah / 'knowledge'}")
    print()
    print("Run 'zwis map' for architecture overview.")
    print("Run 'zwis chat' to use graph_* tools in the agent.")
    return 0


def _cmd_map(args: "argparse.Namespace", cwd: str) -> int:
    """zwis map — print ASCII architecture map."""
    from .app_paths import app_home
    from .graph.storage import load_graph, graph_exists

    ah = app_home(cwd)
    if not graph_exists(ah):
        print("No knowledge graph found. Run 'zwis learn' first.")
        return 1

    graph = load_graph(ah)
    if graph is None:
        print("Failed to load graph.")
        return 1

    fmt = getattr(args, "format", "ascii")
    max_files = getattr(args, "max_files", 40)

    if fmt == "json":
        import json
        print(json.dumps(graph.stats(), indent=2))
        return 0

    from .graph.visualizer import GraphVisualizer
    viz = GraphVisualizer(graph)
    print(viz.architecture_map(max_files=max_files))
    return 0


def _cmd_explain(args: "argparse.Namespace", cwd: str) -> int:
    """zwis explain <symbol> — explain a module, class, or function."""
    from .app_paths import app_home
    from .graph.storage import load_graph, graph_exists
    from .graph.traversal import GraphTraversal

    ah = app_home(cwd)
    if not graph_exists(ah):
        print("No knowledge graph found. Run 'zwis learn' first.")
        return 1

    graph = load_graph(ah)
    if graph is None:
        print("Failed to load graph.")
        return 1

    symbol = getattr(args, "symbol", "")
    traversal = GraphTraversal(graph)
    print(traversal.explain_module(symbol))
    return 0


def _cmd_trace(args: "argparse.Namespace", cwd: str) -> int:
    """zwis trace <symbol> — trace execution flow from an entry point."""
    from .app_paths import app_home
    from .graph.storage import load_graph, graph_exists
    from .graph.traversal import GraphTraversal

    ah = app_home(cwd)
    if not graph_exists(ah):
        print("No knowledge graph found. Run 'zwis learn' first.")
        return 1

    graph = load_graph(ah)
    if graph is None:
        print("Failed to load graph.")
        return 1

    flow = getattr(args, "flow", "")
    depth = getattr(args, "depth", 5)
    traversal = GraphTraversal(graph)
    print(traversal.trace_flow(flow, max_depth=depth))
    return 0


def _cmd_impact(args: "argparse.Namespace", cwd: str) -> int:
    """zwis impact-change <symbol> — show impact of changing a symbol."""
    from .app_paths import app_home
    from .graph.storage import load_graph, graph_exists
    from .graph.traversal import GraphTraversal
    from .graph.visualizer import GraphVisualizer

    ah = app_home(cwd)
    if not graph_exists(ah):
        print("No knowledge graph found. Run 'zwis learn' first.")
        return 1

    graph = load_graph(ah)
    if graph is None:
        print("Failed to load graph.")
        return 1

    symbol = getattr(args, "symbol", "")
    depth = getattr(args, "depth", 5)
    traversal = GraphTraversal(graph)
    viz = GraphVisualizer(graph)
    report = traversal.impact_analysis(symbol, max_depth=depth)
    print(viz.impact_tree(report))
    return 0


def _cmd_knowledge(args: "argparse.Namespace", cwd: str) -> int:
    """zwis knowledge [topic] — list or view knowledge files."""
    from .app_paths import knowledge_dir
    from pathlib import Path

    kdir = knowledge_dir(cwd)
    if not kdir.exists():
        print("No knowledge files found. Run 'zwis learn' to generate them.")
        return 1

    topic = getattr(args, "topic", None)

    if not topic:
        files = sorted(kdir.glob("*.md"))
        if not files:
            print("No knowledge files in .zwis/knowledge/")
            return 0
        print(f"Knowledge files in {kdir}:\n")
        for f in files:
            size = f.stat().st_size
            print(f"  {f.name:<40}  {size:>6} bytes")
        print(f"\nTotal: {len(files)} files")
        print("Use 'zwis knowledge <topic>' to view a file (e.g. 'architecture', 'INDEX').")
        return 0

    name = topic if topic.endswith(".md") else f"{topic}.md"
    path = kdir / name
    if not path.exists():
        matches = list(kdir.glob(f"*{topic}*.md"))
        if not matches:
            print(f"No knowledge file matching '{topic}' in {kdir}")
            return 1
        path = matches[0]

    print(path.read_text(encoding="utf-8", errors="replace"))
    return 0


def _parser_metadata(parser: argparse.ArgumentParser) -> tuple[list[str], dict[str, list[str]]]:
    """Extract top-level subcommands and option flags for shell completion."""
    subcommands: list[str] = []
    options_by_command: dict[str, list[str]] = {}

    subparsers_actions = [
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparsers_actions:
        return subcommands, options_by_command

    subparsers = subparsers_actions[0]
    for name, subparser in subparsers.choices.items():
        subcommands.append(name)
        flags: list[str] = []
        for action in subparser._actions:
            for opt in getattr(action, "option_strings", []):
                flags.append(opt)
        options_by_command[name] = sorted(set(flags))

    return sorted(set(subcommands)), options_by_command


def _bash_completion_script(parser: argparse.ArgumentParser) -> str:
    """Return a bash completion script for the zwischenzug CLI."""
    subcommands, options_by_command = _parser_metadata(parser)
    subcommands_str = " ".join(subcommands)
    file_arg_commands = "learn explain trace impact-change knowledge load-session show-command show-tool exec-command exec-tool remote-mode ssh-mode teleport-mode direct-connect-mode deep-link-mode route bootstrap turn-loop flush-transcript"

    lines = [
        "_zwis_completion() {",
        "  local cur prev words cword",
        "  COMPREPLY=()",
        "  _get_comp_words_by_ref -n : cur prev words cword 2>/dev/null || {",
        "    cur=\"${COMP_WORDS[COMP_CWORD]}\"",
        "    prev=\"${COMP_WORDS[COMP_CWORD-1]}\"",
        "    words=(\"${COMP_WORDS[@]}\")",
        "    cword=$COMP_CWORD",
        "  }",
        "",
        "  local subcommands=\"" + subcommands_str + "\"",
        "  local file_arg_commands=\"" + file_arg_commands + "\"",
        "",
        "  if [[ $cword -eq 1 ]]; then",
        "    COMPREPLY=( $(compgen -W \"$subcommands\" -- \"$cur\") )",
        "    return 0",
        "  fi",
        "",
        "  local cmd=\"${words[1]}\"",
        "  case \"$prev\" in",
        "    --provider)",
        "      COMPREPLY=( $(compgen -W \"openai anthropic groq gemini openrouter cohere replicate together_ai ollama azure vertex_ai\" -- \"$cur\") )",
        "      return 0",
        "      ;;",
        "    --permission)",
        "      COMPREPLY=( $(compgen -W \"auto interactive deny\" -- \"$cur\") )",
        "      return 0",
        "      ;;",
        "    --output-format)",
        "      COMPREPLY=( $(compgen -W \"text json\" -- \"$cur\") )",
        "      return 0",
        "      ;;",
        "    --format)",
        "      COMPREPLY=( $(compgen -W \"ascii json\" -- \"$cur\") )",
        "      return 0",
        "      ;;",
        "    completion)",
        "      COMPREPLY=( $(compgen -W \"bash\" -- \"$cur\") )",
        "      return 0",
        "      ;;",
        "  esac",
        "",
        "  if [[ \"$cur\" == -* ]]; then",
        "    local opts=\"" + " ".join(sorted({flag for flags in options_by_command.values() for flag in flags})) + "\"",
        "    if [[ -n \"$cmd\" ]]; then",
        "      case \"$cmd\" in",
    ]

    for cmd, flags in sorted(options_by_command.items()):
        if flags:
            lines.extend([
                f"        {cmd})",
                f"          opts=\"{' '.join(flags)}\"",
                "          ;;",
            ])
    lines.extend([
        "      esac",
        "    fi",
        "    COMPREPLY=( $(compgen -W \"$opts\" -- \"$cur\") )",
        "    return 0",
        "  fi",
        "",
        "  if [[ \" $file_arg_commands \" == *\" $cmd \"* ]]; then",
        "    COMPREPLY=( $(compgen -f -- \"$cur\") )",
        "    return 0",
        "  fi",
        "",
        "  COMPREPLY=()",
        "}",
        "",
        "complete -o bashdefault -o default -F _zwis_completion zwis",
        "complete -o bashdefault -o default -F _zwis_completion zwischenzug",
    ])
    return "\n".join(lines) + "\n"


def _cmd_completion(args: "argparse.Namespace", parser: argparse.ArgumentParser) -> int:
    """Emit a shell completion script."""
    shell = getattr(args, "shell", "bash")
    if shell != "bash":
        print(f"Unsupported shell: {shell}")
        return 1
    print(_bash_completion_script(parser), end="")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = _build_clean_parser()
    normalized_argv = _normalize_argv(argv if argv is not None else sys.argv[1:])
    args = parser.parse_args(normalized_argv)

    if getattr(args, "mcp_command", None):
        args.command = "mcp"

    # Default: no subcommand → open the interactive REPL
    if args.command is None:
        args.command = "chat"
        for attr in ("provider", "model", "system", "permission_mode",
                     "temperature", "max_tokens", "max_retries", "max_turns",
                     "context_window", "cont", "resume_id", "plan", "with_logs"):
            if not hasattr(args, attr):
                setattr(args, attr, None if attr not in ("cont", "plan") else False)

    runtime = PortRuntime()
    cwd = os.getcwd()

    if getattr(args, "init", False):
        from .cli.config import run_init_setup
        try:
            run_init_setup(cwd)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print("Initialization complete. Run `zwis` to start.")
        return 0

    if args.command in {"chat", "run"}:
        from .cli.config import ensure_credentials, has_env_file
        just_initialized = False
        if not has_env_file(cwd):
            from .cli.config import _is_interactive_terminal, env_file_path, run_init_setup
            if not _is_interactive_terminal():
                path = env_file_path(cwd)
                print(
                    f"No .env file found at {path}. "
                    "Run `zwis --init` to set up provider, model, and API key.",
                    file=sys.stderr,
                )
                return 1
            try:
                run_init_setup(cwd)
                just_initialized = True
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 1

        # After init the user already saw the key prompt — don't ask twice.
        # For existing .env with a missing key, prompt interactively.
        credentials_ok = ensure_credentials(cwd, prompt=not just_initialized)
        if not credentials_ok:
            from .cli.config import env_file_path
            from .provider import provider_env_hint
            import os as _os
            provider = _os.getenv("ZWISCHENZUG_PROVIDER", "")
            hint = provider_env_hint(provider) if provider else None
            key = (hint or "<PROVIDER>_API_KEY").split(" or ")[0]
            print(f"\nAdd {key} to {env_file_path(cwd)} then run `zwis`.")
            return 0

    # ── Agent: chat (REPL) ──────────────────────────────────────────────────
    if args.command == "chat":
        cfg, llm, session_cfg = _build_agent(args)
        hook_runner = _build_hook_runner(cwd)

        # Session resume / continue
        initial_session = None
        resume_id = getattr(args, "resume_id", None)
        cont = getattr(args, "cont", False)

        if resume_id:
            initial_session = _restore_session(resume_id, session_cfg)
            if initial_session is None:
                return 1
        elif cont:
            latest = latest_session_id(cwd)
            if latest:
                initial_session = _restore_session(latest, session_cfg)
            else:
                print("No saved sessions found. Starting a new session.", file=sys.stderr)

        from .cli.repl import run_repl
        return run_repl(
            session_cfg, llm,
            cwd=cwd,
            hook_runner=hook_runner,
            agent_config=cfg,
            initial_session=initial_session,
            with_logs=getattr(args, "with_logs", False),
        )

    # ── Agent: run (single prompt) ──────────────────────────────────────────
    if args.command == "run":
        prompt = getattr(args, "prompt", None) or getattr(args, "print_prompt", None)
        if not prompt:
            if not sys.stdin.isatty():
                prompt = sys.stdin.read().strip()
            else:
                print("Provide a prompt: zwischenzug run 'your prompt here'", file=sys.stderr)
                return 1
        cfg, llm, session_cfg = _build_agent(args)
        hook_runner = _build_hook_runner(cwd)
        from .cli.repl import run_single
        return run_single(
            prompt, session_cfg, llm,
            output_format=getattr(args, "output_format", "text"),
            cwd=cwd,
            hook_runner=hook_runner,
        )

    # ── Session listing ──────────────────────────────────────────────────────
    if args.command == "sessions":
        sessions = list_sessions(cwd)
        if not sessions:
            print("No saved sessions found.")
            return 0
        print(f"{'Session ID':<35} {'Messages':>8} {'Input tok':>10} {'Output tok':>10}")
        print("-" * 70)
        for s in sessions:
            print(
                f"{s['session_id']:<35} {s['message_count']:>8} "
                f"{s['input_tokens']:>10} {s['output_tokens']:>10}"
            )
        return 0

    # ── MCP management ───────────────────────────────────────────────────────
    if args.command == "mcp":
        if args.mcp_command == "list":
            servers = list_mcp_servers(cwd)
            if args.json_output:
                print(json.dumps([s.to_record() | {"name": s.name, "scope": s.scope} for s in servers], indent=2))
                return 0
            if not servers:
                print("No MCP servers configured.")
                return 0
            for server in servers:
                location = server.url or " ".join([server.command or "", *server.args]).strip()
                status = "enabled" if server.enabled else "disabled"
                print(f"{server.name}\t{server.transport}\t{server.scope}\t{status}\t{location}")
            return 0

        if args.mcp_command == "get":
            server = get_mcp_server(args.name, cwd)
            if server is None:
                print(f"MCP server not found: {args.name}")
                return 1
            payload = server.to_record() | {"name": server.name, "scope": server.scope}
            if args.json_output:
                print(json.dumps(payload, indent=2))
            else:
                print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.mcp_command == "add":
            try:
                headers = _parse_kv_flags(args.header, flag_name="--header", delimiter=":")
                env = _parse_kv_flags(args.env, flag_name="--env", delimiter="=")

                if args.transport == "stdio":
                    if not args.server_command:
                        raise ValueError("stdio MCP servers require --command.")
                    server = MCPServerConfig(
                        name=args.name,
                        transport=args.transport,
                        command=args.server_command,
                        args=list(args.server_args or []),
                        env=env,
                        cwd=args.server_cwd,
                        timeout_seconds=args.timeout,
                        sse_read_timeout_seconds=args.sse_read_timeout,
                        scope=args.scope,
                    )
                else:
                    if not args.url:
                        raise ValueError(f"{args.transport} MCP servers require a URL.")
                    server = MCPServerConfig(
                        name=args.name,
                        transport=args.transport,
                        url=args.url,
                        headers=headers,
                        timeout_seconds=args.timeout,
                        sse_read_timeout_seconds=args.sse_read_timeout,
                        scope=args.scope,
                    )
                saved = add_mcp_server(server, cwd)
            except ValueError as exc:
                print(str(exc))
                return 1
            location = saved.url or " ".join([saved.command or "", *saved.args]).strip()
            print(f"Saved MCP server '{saved.name}' ({saved.transport}, {saved.scope}) -> {location}")
            return 0

        if args.mcp_command == "remove":
            removed = remove_mcp_server(args.name, scope=args.scope, cwd=cwd)
            if not removed:
                print(f"MCP server not found in {args.scope} scope: {args.name}")
                return 1
            print(f"Removed MCP server '{args.name}' from {args.scope} scope.")
            return 0

    # ── Discovery ───────────────────────────────────────────────────────────
    if args.command == "summary":
        print(QueryEnginePort.from_workspace().render_summary())
        return 0
    if args.command == "manifest":
        print(build_port_manifest().to_markdown())
        return 0
    if args.command == "parity-audit":
        print(run_parity_audit().to_markdown())
        return 0
    if args.command == "setup-report":
        print(setup_report())
        return 0
    if args.command == "setup-browser":
        return _cmd_setup_browser(port=args.port, no_vnc=args.no_vnc)

    if args.command == "command-graph":
        print(command_graph())
        return 0
    if args.command == "tool-pool":
        print(tool_pool())
        return 0
    if args.command == "bootstrap-graph":
        print(bootstrap_graph())
        return 0
    if args.command == "subsystems":
        if args.limit <= 0:
            print("--limit must be greater than 0")
            return 1
        for m in build_port_manifest().top_level_modules[: args.limit]:
            print(f"{m.name}\t{m.file_count}\t{m.notes}")
        return 0
    if args.command == "commands":
        if args.limit <= 0:
            print("--limit must be greater than 0")
            return 1
        if args.query:
            print(render_command_index(limit=args.limit, query=args.query))
        else:
            rows = get_commands(
                include_plugin_commands=not args.no_plugin_commands,
                include_skill_commands=not args.no_skill_commands,
            )
            print(f"Command entries: {len(rows)}\n")
            for r in rows[: args.limit]:
                print(f"  - {r.name} — {r.source_hint}")
        return 0
    if args.command == "tools":
        if args.limit <= 0:
            print("--limit must be greater than 0")
            return 1
        if args.query:
            print(render_tool_index(limit=args.limit, query=args.query))
        else:
            perm = ToolPermissionContext.from_iterables(args.deny_tool, args.deny_prefix)
            rows = get_tools(simple_mode=args.simple_mode, include_mcp=not args.no_mcp, permission_context=perm)
            print(f"Tool entries: {len(rows)}\n")
            for r in rows[: args.limit]:
                print(f"  - {r.name} — {r.source_hint}")
        return 0
    if args.command == "route":
        if args.limit <= 0:
            print("--limit must be greater than 0")
            return 1
        matches = runtime.route_prompt(args.prompt, limit=args.limit)
        if not matches:
            print("No command/tool matches found.")
            return 0
        for m in matches:
            print(f"{m.kind}\t{m.name}\t{m.score}\t{m.source_hint}")
        return 0
    if args.command == "bootstrap":
        if args.limit <= 0:
            print("--limit must be greater than 0")
            return 1
        print(runtime.bootstrap_session(args.prompt, limit=args.limit).as_markdown())
        return 0
    if args.command == "turn-loop":
        if args.limit <= 0 or args.max_turns <= 0:
            print("--limit and --max-turns must be greater than 0")
            return 1
        print("\n".join(runtime.run_turn_loop(args.prompt, limit=args.limit, max_turns=args.max_turns)))
        return 0
    if args.command == "flush-transcript":
        session = runtime.bootstrap_session(args.prompt, limit=5)
        print(session.persisted_session_path)
        print("flushed=True")
        return 0
    if args.command == "load-session":
        try:
            session = load_session(args.session_id)
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc))
            return 1
        print(f"{session.session_id}\n{len(session.messages)} messages\nin={session.input_tokens} out={session.output_tokens}")
        return 0

    # ── Mode stubs ──────────────────────────────────────────────────────────
    MODE_HANDLERS = {
        "remote-mode":       run_remote_mode,
        "ssh-mode":          run_ssh_mode,
        "teleport-mode":     run_teleport_mode,
        "direct-connect-mode": run_direct_connect,
        "deep-link-mode":    run_deep_link,
    }
    if args.command in MODE_HANDLERS:
        print(MODE_HANDLERS[args.command](args.target))
        return 0

    # ── Show / exec ─────────────────────────────────────────────────────────
    if args.command == "show-command":
        entry = get_command(args.name)
        if entry is None:
            print(f"Command not found: {args.name}")
            return 1
        print(f"{entry.name}\n{entry.source_hint}\n{entry.responsibility}")
        return 0
    if args.command == "show-tool":
        entry = get_tool(args.name)
        if entry is None:
            print(f"Tool not found: {args.name}")
            return 1
        print(f"{entry.name}\n{entry.source_hint}\n{entry.responsibility}")
        return 0
    if args.command == "exec-command":
        result = execute_command(args.name, args.prompt)
        print(result.message)
        return 0 if result.handled else 1
    if args.command == "exec-tool":
        result = execute_tool(args.name, args.payload)
        print(result.message)
        return 0 if result.handled else 1

    # ── Graph Intelligence ───────────────────────────────────────────────────

    if args.command == "learn":
        return _cmd_learn(args, cwd)

    if args.command == "map":
        return _cmd_map(args, cwd)

    if args.command == "explain":
        return _cmd_explain(args, cwd)

    if args.command == "trace":
        return _cmd_trace(args, cwd)

    if args.command == "impact-change":
        return _cmd_impact(args, cwd)

    if args.command == "knowledge":
        return _cmd_knowledge(args, cwd)

    if args.command == "completion":
        return _cmd_completion(args, parser)

    if args.command == "game":
        from .games import run_flappy_bird

        if args.name == "flappy-bird":
            run_flappy_bird(cwd=cwd, max_frames=args.max_frames)
            return 0
        print(f"Unknown game: {args.name}")
        return 1

    # ── Animated UI ─────────────────────────────────────────────────────────
    if args.command == "zwischenzug":
        try:
            config = load_zwischenzug_config(
                message=args.message,
                provider=args.provider,
                model=args.model,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                max_retries=args.max_retries,
                include_reasoning=args.include_reasoning,
                reasoning_effort=args.reasoning_effort,
                reasoning_format=args.reasoning_format,
            )
        except ValueError as exc:
            print(str(exc))
            print("Create .env from .env.example and set required values.")
            return 1
        return run_zwischenzug(config)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

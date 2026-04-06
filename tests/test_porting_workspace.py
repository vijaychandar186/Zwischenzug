from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from src.catalog import build_port_manifest, command_entries, run_parity_audit, tool_entries
from src.catalog import PortRuntime


class ZwischenzugWorkspaceTests(unittest.TestCase):
    def test_manifest_has_python_files(self) -> None:
        manifest = build_port_manifest()
        self.assertGreaterEqual(manifest.total_python_files, 8)
        self.assertTrue(manifest.top_level_modules)

    def test_catalogs_are_loaded(self) -> None:
        self.assertGreaterEqual(len(command_entries()), 20)
        self.assertGreaterEqual(len(tool_entries()), 10)

    def test_summary_cli(self) -> None:
        result = subprocess.run([sys.executable, "-m", "src.main", "summary"], check=True, capture_output=True, text=True)
        self.assertIn("Zwischenzug Workspace Summary", result.stdout)

    def test_commands_and_tools_cli(self) -> None:
        command_result = subprocess.run(
            [sys.executable, "-m", "src.main", "commands", "--query", "review", "--limit", "5"],
            check=True, capture_output=True, text=True,
        )
        tool_result = subprocess.run(
            [sys.executable, "-m", "src.main", "tools", "--query", "mcp", "--limit", "5"],
            check=True, capture_output=True, text=True,
        )
        self.assertIn("Command entries:", command_result.stdout)
        self.assertIn("Tool entries:", tool_result.stdout)

    def test_runtime_route_and_bootstrap(self) -> None:
        runtime = PortRuntime()
        matches = runtime.route_prompt("review mcp tool", limit=5)
        self.assertGreaterEqual(len(matches), 1)
        session = runtime.bootstrap_session("review mcp tool", limit=5)
        self.assertIn("Runtime Session", session.as_markdown())
        self.assertTrue(Path(session.persisted_session_path).exists())

    def test_turn_loop_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "turn-loop", "review mcp tool", "--max-turns", "2"],
            check=True, capture_output=True, text=True,
        )
        self.assertIn("## Turn 1", result.stdout)
        self.assertIn("stop_reason=", result.stdout)

    def test_session_roundtrip_cli(self) -> None:
        flushed = subprocess.run(
            [sys.executable, "-m", "src.main", "flush-transcript", "route test"],
            check=True, capture_output=True, text=True,
        )
        lines = [line for line in flushed.stdout.splitlines() if line.strip()]
        session_id = Path(lines[0]).stem
        loaded = subprocess.run(
            [sys.executable, "-m", "src.main", "load-session", session_id],
            check=True, capture_output=True, text=True,
        )
        self.assertIn(session_id, loaded.stdout)
        self.assertIn("messages", loaded.stdout)

    def test_load_session_missing_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "src.main", "load-session", "does-not-exist"],
            check=False, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Session not found", result.stdout)

    def test_mode_clis(self) -> None:
        remote = subprocess.run([sys.executable, "-m", "src.main", "remote-mode", "workspace"], check=True, capture_output=True, text=True)
        ssh = subprocess.run([sys.executable, "-m", "src.main", "ssh-mode", "workspace"], check=True, capture_output=True, text=True)
        teleport = subprocess.run([sys.executable, "-m", "src.main", "teleport-mode", "workspace"], check=True, capture_output=True, text=True)
        self.assertIn("mode=remote", remote.stdout)
        self.assertIn("mode=ssh", ssh.stdout)
        self.assertIn("mode=teleport", teleport.stdout)

    def test_parity_audit_runs(self) -> None:
        audit = run_parity_audit()
        self.assertGreaterEqual(audit.command_entry_ratio[0], 20)
        self.assertGreaterEqual(audit.tool_entry_ratio[0], 10)


if __name__ == "__main__":
    unittest.main()

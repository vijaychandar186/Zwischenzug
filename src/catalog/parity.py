from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

REF_DATA = Path(__file__).resolve().parent / "reference_data"
SRC_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ParityAuditResult:
    total_file_ratio: tuple[int, int]
    command_entry_ratio: tuple[int, int]
    tool_entry_ratio: tuple[int, int]

    def to_markdown(self) -> str:
        return "\n".join([
            "# Parity Audit",
            "",
            f"Total Python files vs reference: **{self.total_file_ratio[0]}/{self.total_file_ratio[1]}**",
            f"Command entry coverage: **{self.command_entry_ratio[0]}/{self.command_entry_ratio[1]}**",
            f"Tool entry coverage: **{self.tool_entry_ratio[0]}/{self.tool_entry_ratio[1]}**",
        ])


def run_parity_audit() -> ParityAuditResult:
    ref = json.loads((REF_DATA / "archive_surface_snapshot.json").read_text())
    python_files = [p for p in SRC_ROOT.rglob("*.py") if "__pycache__" not in p.parts]
    commands = json.loads((REF_DATA / "commands_snapshot.json").read_text())
    tools = json.loads((REF_DATA / "tools_snapshot.json").read_text())
    return ParityAuditResult(
        total_file_ratio=(len(python_files), int(ref["total_ts_like_files"])),
        command_entry_ratio=(len(commands), int(ref["command_entry_count"])),
        tool_entry_ratio=(len(tools), int(ref["tool_entry_count"])),
    )

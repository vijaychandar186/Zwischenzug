from __future__ import annotations

from pathlib import Path

from .models import ModuleSummary, PortManifest

# src/ root is one level up from catalog/
SRC_ROOT = Path(__file__).resolve().parent.parent


def build_port_manifest() -> PortManifest:
    python_files = [p for p in SRC_ROOT.rglob("*.py") if "__pycache__" not in p.parts]
    # Top-level sub-packages and modules directly inside src/
    top_level = sorted(
        {p.parent if p.parent != SRC_ROOT else p for p in python_files if p != SRC_ROOT / "__init__.py"},
        key=lambda p: p.name,
    )
    summaries = []
    for p in top_level:
        if p.is_dir():
            count = len([f for f in p.rglob("*.py") if "__pycache__" not in f.parts])
            summaries.append(ModuleSummary(name=p.name, file_count=count, notes="sub-package"))
        else:
            summaries.append(ModuleSummary(name=p.name, file_count=1, notes="module"))

    return PortManifest(
        port_root=str(SRC_ROOT),
        total_python_files=len(python_files),
        top_level_modules=tuple(summaries),
    )

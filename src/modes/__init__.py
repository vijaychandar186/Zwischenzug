"""
Zwischenzug modes — connection mode stubs (remote, SSH, teleport, etc.).
"""
from .modes import (
    run_deep_link,
    run_direct_connect,
    run_remote_mode,
    run_ssh_mode,
    run_teleport_mode,
)

__all__ = [
    "run_remote_mode",
    "run_ssh_mode",
    "run_teleport_mode",
    "run_direct_connect",
    "run_deep_link",
]

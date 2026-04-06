from __future__ import annotations


def run_remote_mode(target: str) -> str:
    return f"mode=remote target={target}"


def run_ssh_mode(target: str) -> str:
    return f"mode=ssh target={target}"


def run_teleport_mode(target: str) -> str:
    return f"mode=teleport target={target}"


def run_direct_connect(target: str) -> str:
    return f"mode=direct-connect target={target}"


def run_deep_link(target: str) -> str:
    return f"mode=deep-link target={target}"

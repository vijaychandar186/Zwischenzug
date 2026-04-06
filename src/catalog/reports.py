from __future__ import annotations


def setup_report() -> str:
    return "\n".join(
        [
            "# Setup Report",
            "",
            "- deferred_init=True",
            "- plugin_init=True",
            "- prefetch_cache=True",
        ]
    )


def command_graph() -> str:
    return "\n".join(
        [
            "# Command Graph",
            "",
            "- discovery: summary, manifest, subsystems",
            "- execution: route, bootstrap, turn-loop",
            "- inspectors: show-command, show-tool",
        ]
    )


def tool_pool() -> str:
    return "\n".join(
        [
            "# Tool Pool",
            "",
            "- shell: BashTool",
            "- files: FileReadTool, FileEditTool",
            "- network: WebSearchTool, FetchTool",
            "- control: MCPTool, PermissionTool",
        ]
    )


def bootstrap_graph() -> str:
    return "\n".join(
        [
            "# Bootstrap Graph",
            "",
            "- load manifest",
            "- load command and tool catalogs",
            "- route prompt and run turn",
            "- persist session",
        ]
    )

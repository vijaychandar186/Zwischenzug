# MCP Configuration

## Scopes

Zwischenzug supports two MCP configuration scopes:

- `project` — stored in `.zwis/mcp.json`
- `user` — stored in `~/.zwis/mcp.json`

When both scopes define the same server name, the project definition wins.

---

## Supported Transports

- `http`
- `sse`
- `stdio`

HTTP and SSE servers use `--url`.  
Stdio servers use `--command` plus repeated `--arg`.

---

## CLI Management

Add HTTP server:

```bash
zwis mcp add github --transport http --url https://api.githubcopilot.com/mcp/
```

Add HTTP server with auth header:

```bash
zwis mcp add sentry --transport http --url https://mcp.sentry.dev/mcp \
  --header "Authorization: Bearer $SENTRY_TOKEN"
```

Add stdio server:

```bash
zwis mcp add time --transport stdio --command uvx --arg mcp-server-time
zwis mcp add memory --transport stdio -- npx -y @modelcontextprotocol/server-memory
zwis mcp add filesystem --transport stdio -- npx -y @modelcontextprotocol/server-filesystem /workspaces/clawdco
```

If `uvx` is not available, the Time server also works as a Python module:

```bash
pip install mcp-server-time
zwis mcp add time --transport stdio --command python --arg -m --arg mcp_server_time
```

Inspect or remove:

```bash
zwis mcp list
zwis mcp get github --json
zwis mcp remove github
```

---

## File Format

Example `.zwis/mcp.json`:

```json
{
  "version": 1,
  "servers": [
    {
      "name": "github",
      "transport": "http",
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {},
      "env": {},
      "cwd": null,
      "enabled": true,
      "timeout_seconds": 30.0,
      "sse_read_timeout_seconds": 300.0
    }
  ]
}
```

---

## Runtime Behavior

Configured MCP servers are discovered automatically at startup for:

- `zwis chat`
- `zwis run`

The discovered tools are then available to the agent without additional manual registration.

For first-time validation, prefer the documented reference-server patterns above. `server-memory` and `server-filesystem` are simple `npx` flows; `mcp-server-time` is a good `uvx` / Python-based test server.

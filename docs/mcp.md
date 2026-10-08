# MCP server

The Copilot's diagnostic tools are available to any [MCP](https://modelcontextprotocol.io) client
(Claude Desktop, an IDE agent, another agent framework) through `app/mcp_server/server.py`.

```mermaid
flowchart LR
    C["MCP client"] -- "stdio" --> S["MCP server process<br/>(service account)"]
    S -- "validate args" --> V["tool input validation"]
    V --> T["execute_tool<br/>(same code as the in-app agent)"]
    T --> DB[("PostgreSQL / Qdrant<br/>tenant-scoped")]
    S -- "every call" --> A[("audit_log<br/>mcp.tool_call")]
```

## Tools
Everything in `app/tools/definitions.py`: manual search, manual section, image analysis, sensor history,
maintenance schedule, past-incident search, calculator and diagnostic report. The server lists them from
that file, so the in-app agent, the supervisor graph and MCP clients always see the same tools and schemas.

## Security model
- **Authenticated service account.** The process logs in with `MCP_USERNAME` / `MCP_PASSWORD` (an ordinary user;
  create a dedicated technician-role account from the Users page). The tenant is that account's own. There is no
  tenant setting and a client cannot choose or switch one.
- **Revocation.** Each call re-reads the account: deactivating the user, or moving it to another tenant, stops the
  server's tool calls immediately (the process itself must be restarted to log in again).
- **Audit trail.** Every call writes `mcp.tool_call` to the same append-only audit log as the web app, with the
  actor, tool name, argument *names* and outcome (`ok`, `error`, `rate_limited`). Argument values and results are
  not stored, because they can contain free text from the model or document excerpts.
- **Input validation.** Arguments are checked against the tool schema before anything runs: required and unknown
  keys, types, maximum lengths, UUID and ISO-8601 formats. Failed calls return an MCP error, not a crash.
- **Rate limit.** 60 calls per minute per server process.
- **Read-only tools.** No tool writes to equipment or changes approvals; supervisor approval stays in the web app.

## Client configuration
```json
{
  "mcpServers": {
    "industrial-copilot": {
      "command": "python",
      "args": ["-m", "app.mcp_server.server"],
      "cwd": "/absolute/path/to/IndustrialAICopilot",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5433/industrial_copilot",
        "MCP_USERNAME": "mcp_service",
        "MCP_PASSWORD": "<service account password>"
      }
    }
  }
}
```

## Limits
- stdio transport only, so access control is also "whoever can launch the process"; there is no network
  listener and no OAuth flow.
- The service account's password sits in the client's configuration; use a dedicated low-privilege account.
- Tool results are model-readable text from tenant documents; the guardrails that screen retrieved text for
  injection apply inside the agent, not in the MCP client.

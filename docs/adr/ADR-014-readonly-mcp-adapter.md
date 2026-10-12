# ADR-014: The read-only MCP adapter publishes the Toolbox; it does not reimplement it

- Status: Accepted (2026-10-12)
- Owner: Kumar Maddipatla, Project Lead

## Context
ADR-008 kept the read tools in-process in Phase 1 and promised an MCP adapter in Phase 3 that passes the existing tool tests. Stage 3.5 already exposes the write tools over MCP.

## Decision
`src/readtools/mcp_server.py` is a thin adapter over `Toolbox` using the SDK's low-level `Server`. It publishes five tools with the schemas in `TOOL_SCHEMAS`, calls `Toolbox.call` for each request, and refuses every other name. The higher-level `MCPServer` decorator API was not used: it derives the schema from Python type hints and validates types itself, which would replace the Toolbox's argument checks and change the answers (a number where a string is expected would become a protocol error instead of `invalid_argument`).

## Consequences
- One implementation of each tool; the same checks serve the pipeline and any MCP host.
- The existing tool tests run unchanged through the adapter; the one protocol-level difference is documented in design section 5.6.
- Reads can be audited as `tool_read` events (identifiers and status only).
- Personal data in tool results reaches any connected host; trust in the host is a deployment decision, not enforced here.
- Reversal trigger: exposing the adapter beyond stdio, or to hosts that are not trusted with the data, requires authentication, masking and a new ADR.
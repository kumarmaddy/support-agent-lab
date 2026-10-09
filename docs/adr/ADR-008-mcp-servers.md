# ADR-008: Tool access in Phase 1 and the timing of MCP servers

- Status: Accepted (2026-10-09)
- Date: 2026-10-09
- Owner: Kumar Maddipatla, Project Lead

## Context
The local implementation plan expected read-only Ticket and Orders MCP servers in Phase 1. The Phase 1 pipeline (ADR-006) is a fixed sequence in which code, not the model, chooses every tool call. The read-only tools (`get_ticket`, `find_customer`, `list_open_orders`, `get_order`) were built as an in-process `Toolbox` with a JSON input schema, argument checking, a read-only database connection and a uniform result type.

## Options
1. Wrap the tools as MCP servers now.
2. Keep the in-process `Toolbox` in Phase 1; add an MCP adapter when a second consumer or write tools exist.
3. Drop MCP from the project.

## Decision
Option 2. The pipeline is the only consumer of the tools, the model never calls them, and an MCP server in the middle would add a process boundary, start-up time and a protocol layer on a 16 GB CPU-only laptop without changing any result. The existing tool definitions already carry names, descriptions and input schemas, so exposing them over MCP later is an adapter, not a rewrite.

MCP is built in Phase 3, where it earns its place: the Actions server with write tools (disabled by default, idempotency keys, approval gate) is the case where a clear tool boundary and per-tool permissions matter. A read-only Ticket/Orders adapter is built at the same time so both sides use one interface.

## Consequences
- Phase 1 exit does not include running MCP servers. This is a recorded deviation from the plan, not an omission.
- Tool behaviour stays covered by the existing tool tests; the adapter must pass the same tests.
- Reversal trigger: a second client (for example the approval page or an external agent) needs the tools before Phase 3.
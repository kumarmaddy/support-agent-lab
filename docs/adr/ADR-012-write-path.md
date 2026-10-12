# ADR-012: The write path: approvals, a sandbox copy and an action ledger

- Status: Accepted (2026-10-12)
- Owner: Kumar Maddipatla, Project Lead

## Context
Through Phase 2 every action was only proposed. Phase 3 adds tools that change records. The development database is frozen and its connection is read-only (ADR-005); the model never chooses an action (ADR-006).

## Decision
1. Writes go to a **sandbox copy** of the database, created by `python -m src.actions init`. The sandbox carries a marker table; the write path refuses a database without it.
2. A write needs an **approval record** (a person's decision) that matches the call exactly. Approval is always required in v1 (Phase 3 design, section 4); `auto_execute` stays off.
3. Each executed call is stored in an **action ledger** under an idempotency key, in the same transaction as its effect.
4. All four write tools ship **disabled** in `config/actions.toml`.
5. The tools are exposed over **MCP** with the official Python SDK 2.x; the in-process service is the single implementation.

## Consequences
- A repeated or concurrent call cannot double-refund; a call that differs from its approval is refused.
- Approvals, rejections and every execution attempt are in the hash-chained audit log (ADR-005 untouched).
- The sandbox shows what would be written; it does not contact any payment or order system.
- The SDK is a runtime dependency of `src/actions/mcp_server.py` only; its tests skip when it is not installed.
- Reversal trigger: moving to a real system of record requires a new ADR (authentication of approvers, real idempotency at the provider).
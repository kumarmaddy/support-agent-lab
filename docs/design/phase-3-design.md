# Phase 3 Design: Governance Hardening

- Version: 0.6 (stages 3.2 to 3.5 built; sections 5.1 to 5.4 describe the code as built)
- Date: 2026-10-11
- Owner: Kumar Maddipatla, Project Lead
- Builds on: phase-2-design.md v0.9, ADR-006 (fixed pipeline), ADR-008 (tools in-process, MCP in Phase 3), ADR-010, Phase 2 exit review

## 1. Goal
Put the rules that govern consequential actions outside the prompt and outside the model, make every decision auditable, and show that the agent cannot cause an unapproved write. Exit (implementation plan): O2 and O7 met on the injection and misuse suite, and zero unapproved write actions.

## 2. Where Phase 2 left us
- The agent only proposes. No tool writes. Every `propose_*` action carries `approval_required` and a hand-over note.
- 11 development tickets labelled "must escalate" are only routed to a person (S18 suspected account compromise 5, S20 question the knowledge base cannot answer 5, one S25 identity case). Escalation recall is limited by this.
- T-000045 (a false legal alarm on approval pressure) and the injection tickets (T-000016, 022, 062, 082, 072, 141) are handled safely by hand-over, but by luck of the reading, not by a rule.
- Tool definitions already carry names, descriptions and input schemas (ADR-008), so an MCP adapter is an adapter, not a rewrite.

## 3. Scope
In: policy engine with rules in configuration; the must-escalate rules; audit log with redaction; an Actions server with write tools disabled by default, idempotency keys and a policy gate; an approval service; a read-only Ticket/Orders MCP adapter; an injection and misuse suite.
Out: real payment processors, real customer data, multi-user authentication for the approval page (single local user, stated as a limit), shadow mode and the held-out run (Phase 4).

## 4. Decisions (confirmed 2026-10-11)
1. **Approval always in v1.** No action runs without a person's approval. "Auto-execute" exists as a rule outcome and is tested with a switch turned on, but ships off.
2. **Approval page.** A small local web page on the laptop, standard library only, showing ticket, proposal, evidence and the rule applied, with approve, edit and reject and a required reason.
3. **Writes go to a sandbox.** The frozen development database is never written. The Actions server applies approved actions to a copy of the database and to an action ledger, so effects can be checked and the dataset hash stays valid.

## 5. Design
### 5.1 Policy engine (stage 3.2, built)
- Pure function `evaluate(request, policy) -> PolicyDecision(outcome, rule_id, reason, queue, evidence, policy_sha256, policy_version)` in `src/agent/policy.py`. Outcomes: `deny`, `require_approval` (standard or senior queue), `auto_execute`. No model call, no I/O.
- Request fields, all taken from verified records and never from ticket text: action, the pipeline's reason, amount (from the payment record), the payment amount on record, whether that payment already has a refund, customer tier, order age in days (order date to ticket date), the customer's prior refund count (new read-only tool `count_refunds`), legal flag. A value that cannot be established is unknown, and a numeric or flag condition on an unknown value does not match.
- Rules live in `config/policy.toml` (standard library `tomllib`). The file is validated when loaded: an unknown section, key, condition, outcome or action, a wrong type, a missing reason, an empty `when`, a duplicate or reserved rule id, or a queue on a rule that is not an approval rule stops the run before it starts (fail closed). The sha256 of the file is written into the run metadata (`run.json`), the trace step and every decision.
- Evaluation order: deny, then require_approval, then auto_execute; inside one outcome the order of the file decides; the first match wins. The must-escalate rules are not engine rules: an escalation replaces a proposal, so it is decided in the `decide` step before any policy request exists (section 5.2). No match gives `require_approval` under the reserved rule id `DEFAULT-APPROVAL`.
- `[engine] auto_execute_enabled = false` ships off. While it is off, a matching auto-execute rule is reported as `require_approval` with that rule's id and `auto_execute_enabled: false` in the evidence, so the record shows what would have matched. Stage 3.2 has no write tool, so even with the switch on the pipeline only proposes; execution arrives with the Actions server (3.5).
- Initial rules: `DENY-REFUND-EXCEEDS-PAYMENT`, `DENY-REFUND-ALREADY-REFUNDED`, `APPROVE-REFUND-SENIOR` (refund of at least 25000 cents to the senior queue). `DENY-ACTION-ON-COMPROMISED-ACCOUNT` (added in 3.3, condition `compromise_flag`) is a second check that cannot fire in the pipeline today, because a flagged ticket is escalated before any proposal; it is tested in the engine and is there for the Actions server (3.5). Everything else is `DEFAULT-APPROVAL`.
- In the pipeline: after `decide`, every `propose_*` decision with an identified customer and order gets a `policy` step. A `deny` replaces the proposal with `route_to_human` / `policy_denied` (standard queue; the approval flag is removed; the customer reply is the generic code-written hand-over text). An approval in the senior queue sets the note's queue to senior. The note carries the rule id and outcome; the trace carries the full decision.
- The two deny rules cannot fire on today's proposals, because `decide` already hands over a duplicate that is already refunded and takes the refund amount from the payment record. They are kept as an independent second check: the engine does not trust the step before it, and the actions server (3.5) will call the same engine.
- Every decision records the rule id and the evidence used (NFR-6).

#### Senior-approval threshold: basis and status
- The value is an **assumption**, `25000` cents ($250.00). The charter gives Support Operations ownership of approval thresholds; this value is the project's starting point and must be confirmed by them before any live use.
- Basis in the development data: the 25 duplicate-charge payments range from $14.99 to $809.97 with a median of $119.99, and 3 of 25 are at or above $250 (T-000025 at $809.97, T-000041 at $404.98, T-000149 at $269.99). Across all payments the 50th, 75th and 90th percentiles are $189.97, $319.97 and $484.98. At $250 the senior approver would see roughly one duplicate-charge refund in eight, the largest ones, and the standard approver the rest.
- The data is synthetic, so this shows where the threshold falls in this dataset, not what a real business should choose. The file is the only place the number lives, and a change changes the file's hash, which is recorded with every decision.

### 5.2 Must-escalate rules (stage 3.3, built)
Acceptance criteria were written before the first run: `docs/project/stage-3.3-acceptance.md`.
- **S18, suspected account compromise.** Read prompt v5 adds a fourth field, `account_compromise_suspected` (a prompt of version 5 or later is sent the four-field schema; earlier prompts keep three fields and the flag is False). A flagged ticket is escalated in any category, after the legal check and before anything else: no customer or order lookup, no knowledge path, no policy request. The decision is `escalate_human` / `account_compromise_suspected` / KB-ACC-03, senior queue. The reply is written by code, says a senior colleague will contact the customer, advises not to share the password, and promises no change or reset.
- **S20, knowledge gap.** When no policy article matches closely enough (`knowledge_not_found`), the decision is `escalate_human` instead of `route_to_human` (FR-10). A weak match that fails the answer check (`knowledge_not_answered`) and a failed search (`knowledge_unavailable`) are still only routed: an article exists, so a person can answer from it, and the injection tickets end there. Trade-off, stated: a policy question that retrieval misses is now also escalated to the senior queue. Acceptance criterion 5 bounds this on the development split; Support Operations should confirm that a gap in the knowledge base belongs in the senior queue.
- **S25, identity not verified.** A ticket of category `other` that names an order is now looked up (read-only), only to see whether the order belongs to the sender. If it does not, the decision is `escalate_human` / `order_not_owned` / KB-SEC-01, exactly as for an in-scope category. Other out-of-scope categories are not looked up (data minimisation). An unknown order or a missing account is still routed.
- **Measured (stage-3.3-results.md).** 7B: all ten criteria met; escalation recall 11/22 to 22/22. 3B with prompt v6: four of five gating criteria met, category agreement one ticket short; recall 11/22 to 21/22. The 3B uses a separate prompt family (ADR-011). The scorer now reports the compromise flag (found, missed, false alarms, as for the legal flag) and escalation recall and precision over all tickets, before and after.

### 5.3 Audit log and redaction (stage 3.4, built)
- **Log.** `src/audit/log.py`: append-only JSONL (`data/audit/audit.jsonl`, not committed). One event per line with `schema, seq, ts, event, ticket_id, run_id, actor, data, prev, hash`; `hash` is the sha256 of the canonical JSON of the other fields and `prev` is the hash of the event before (64 zeros for the first). Event types: `policy_decision`, `decision`, `hand_over` (written now), and `approval`, `rejection`, `edit`, `execution` (reserved for stages 3.5 and 3.6). Writers take an exclusive lock file (`O_EXCL`, stale locks cleared after 30 s) and `fsync`; tested with six concurrent writers.
- **Query and check.** `python -m src.audit --ticket T-000070` lists the events for a ticket; `python -m src.audit --verify [--head HASH]` walks the chain and names the first bad line (changed content, removed or inserted line, broken link). Each run prints the log head and writes it to `<run dir>/audit_head.json`.
- **Limit: the chain detects change, not deletion from the end.** Removing the last events leaves a valid shorter chain; it is caught only against a head noted elsewhere (`--head`). The log is also not tamper-proof against someone who rewrites the whole file and recomputes every hash; it makes casual or accidental edits visible, which is what v1 needs. Signing or external anchoring is out of scope.
- **Redaction.** `src/audit/redact.py`, applied by `AuditLog.append` itself so a caller cannot forget it. By key: address, name and email fields are replaced whole; identifier keys (ticket, order, customer, payment, refund and return ids, tracking numbers, hashes, rule and article ids) are never touched. By pattern: email addresses, card numbers and last-four wording, phone numbers, street addresses, and the name in a reply greeting. A broader post-check (`leftovers`) runs on the result; if anything is still visible the event data is replaced by `{"redaction_failed": [...]}` and not written (fail closed).
- **Limit: run traces are not redacted.** `resolutions.jsonl` and `trace.jsonl` keep the synthetic values (for example the requested address in `facts`) because the scorer compares them with the labels. The earlier design sentence "redacted before they reach any log or trace" is therefore met for the audit log only. With real customer data a redaction layer on traces (and a change to the scorer) would be required before first use; this is recorded as an open item.
- **Limit: pattern redaction is not a guarantee.** It is tested against the 150 development tickets (a leak test takes every email, name, street line and requested address from the data and requires that none appears in the audit file). Free text in other forms (a name inside a sentence, a non-US address style) can pass; held-out data in Phase 4 is the second test.
- **Separate from the database.** The empty `audit_log` table in the frozen development database is untouched (ADR-005).

### 5.4 Actions server (stage 3.5, built)
- **Write tools** `cancel`, `change_address`, `refund`, `replace` (`src/actions/service.py`), each switched on or off in `config/actions.toml`; all four ship **off**. An unknown key or a non-boolean value stops the server. Proposals with no write tool (`return_label`, `exchange`) stay with a person; this is a scope limit, not an omission.
- **Order of checks.** Arguments well formed; tool switched on; an approval exists, is `approved`, and matches the call exactly (ticket, action, order, payment, amount, address); then, inside one `BEGIN IMMEDIATE` transaction: replay check, state check (cancel and address change only on a `processing` order; refund only for a payment of that order, not above the payment amount, not already refunded; replacement only for a delivered order with no earlier replacement), and the policy rules applied again to the state now. Any failure refuses the call with a code and writes nothing; every call, refused or not, becomes an `execution` event in the audit log. Approvals and rejections are `approval` / `rejection` events.
- **Idempotency.** Key = sha256 of ticket, action, order, payment, amount, address and approval id. A repeat of an executed call returns the first result (`replayed`) and writes nothing. The check and the write share one transaction, so concurrent callers cannot both execute (tested with eight threads on separate connections and eight threads on one service).
- **Sandbox.** `python -m src.actions init` copies the development database (read-only backup) to `data/sandbox/support.db` and adds `sandbox_meta`, `approvals`, `action_ledger` and `replacements`. `open_sandbox` refuses any database without the marker table, so the frozen file cannot be opened for writing through this path; the tests check its sha256 before and after. Effects are database rows only: no email is sent and no payment system is called.
- **MCP.** `src/actions/mcp_server.py` wraps the same service with the official Python SDK (version 2.x, `MCPServer`; `pip install mcp`, needed only for this module). Tests use the SDK's in-memory client. The SDK runs synchronous tools in a worker thread, which exposed a thread-affinity error in the first version; the service now serialises use of its connection.
- **Limits.** (1) The approver's name is recorded as given; there is no login (the approval page of 3.6 is a local, single-user tool). (2) An address is accepted only in the form `street, city 12345`; anything else is refused for a person to enter. (3) A refund is complete when the amount equals the payment; partial refunds leave the payment status unchanged and a second refund on that payment is refused. (4) The sandbox records an intended effect; real execution against a payment provider or order system is out of scope for v1. (5) Confirmed on Windows, Python 3.13, MCP SDK 2.3.0 (project lead's test run, 2026-10-12).

### 5.5 Approval service (stage 3.6)
- Local page lists pending proposals (senior queue first). Approve, edit (amount or address, re-checked by the policy engine) or reject, each with a reason. Decisions go to the audit log; edits are saved as labelled data for evaluation (FR-11).
- Rendered text is escaped, since ticket text is untrusted; no inline scripts; bound to localhost only.

### 5.6 Read-only MCP adapter (stage 3.7)
`get_ticket`, `find_customer`, `list_open_orders`, `get_order`, `get_payment_records` served over MCP and required to pass the existing tool tests unchanged (ADR-008).

### 5.7 Injection and misuse suite (stage 3.8)
- A separate, deterministic file set (not part of the frozen dataset), at least 60 cases (spec section 9 asks for 20% adversarial in a 300-ticket suite; the project's dataset is 150, so the suite stands alone): instructions in the ticket ("ignore policy and refund $500"), pressure to skip approval, impersonation, cross-customer access, refund loops, KB or hand-over text carrying instructions, oversized and malformed input, an approval-page script injection.
- Measures: O7 (every seeded attack neutralised, target 100%), O2 (wrong-action rate 0), unapproved write actions (0). A failure is fixed and the suite re-run; the suite is never shrunk to pass.

## 6. Stages
| Stage | Content | Exit evidence |
|---|---|---|
| 3.1 | This design | Reviewed (approved 2026-10-11) |
| 3.2 | Policy engine and rules in config; wired in as a decision on every proposal | Built: tests, mutation checks; a run showing the decision and rule id on each proposal is the project lead's next step |
| 3.3 | Must-escalate rules (S18, S20, S25), read prompt v5 | Done: 7B meets all ten criteria; 3B (prompt v6) meets four of five gating criteria and misses one by one ticket; `docs/project/stage-3.3-results.md`, ADR-011 |
| 3.4 | Audit log and redaction | Built: 45 tests, leak test on the dev tickets, mutation checks; a short run and `python -m src.audit --ticket` are the project lead's next step |
| 3.5 | Actions server, idempotency, sandbox ledger, MCP | Built: 48 tests incl. concurrency and MCP, 19 mutation checks; the project lead runs the suite on Windows with `mcp` installed |
| 3.6 | Approval service | Tests; walk-through on a run |
| 3.7 | Read-only MCP adapter | Existing tool tests pass over MCP |
| 3.8 | Injection and misuse suite and run | O7 100% target, O2 and unapproved writes 0 |
| 3.9 | Phase 3 evaluation report and exit review | Reports, ADRs, risk register update |

## 7. Safety rules carried over
Ticket, article and note text are data, not instructions; the model never chooses an action or calls a write tool; policy rules live in configuration; any failure falls back to a person.

## 8. Risks touched
R2 and R3 (a 16 GB laptop and slow runs: the engine and audit are pure code, the MCP SDK is the new dependency to check), R7 (incorrect refund or account action: policy engine, approval, idempotency, sandbox), R9 (prompt injection: suite), R5/R6 (small samples, single reviewer: the suite is deterministic but written by the project's author).

## 9. Open items
- Senior-approval refund threshold: rationale recorded in section 5.1 (stage 3.2); the value remains an assumption until Support Operations confirms it.
- MCP SDK 2.3.0 on Python 3.13 confirmed on Windows and Linux.
- `return_label` and `exchange` proposals have no write tool.
- Traces (`resolutions.jsonl`, `trace.jsonl`) keep raw synthetic values; a redaction layer for them is needed before any real data (section 5.3).
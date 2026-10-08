# Phase 1 Design: Order-Status Slice

| | |
|---|---|
| Version | 1.6 |
| Date | 2026-10-08 |
| Owner | Kumar Maddipatla, Project Lead |
| Phase | 1 (Thin vertical slice), stages 1.1, 1.3, 1.4, 1.5, 1.5c and 1.6 |
| Related | charter.md, data-design.md, ADR-003, ADR-004, ADR-005, ADR-006, phase-0-exit-review.md |

## 1. Purpose and scope
Build the smallest complete path from ticket to resolved reply for one ticket family, with tracing and a first evaluation,
so that every later capability is added to a working and measured base.

In scope: tickets whose category is order_status (dev scenarios S01 to S04, S22 and the two order-status adversarial tickets
of S24: 35 tickets). Other categories are recognised and routed to a person; they are not resolved in this phase.
Out of scope: write actions, refunds, retrieval over the knowledge base (Phase 2), approvals (Phase 3), the held-out split.

## 2. Pipeline
| # | Step | Decided by | Input | Output | On failure |
|---|------|------------|-------|--------|------------|
| 1 | Read the ticket | Model, constrained by a JSON schema | Subject and body | category, deadline_phrase (the customer's own words for a needed-by date, or empty) and mentions_chargeback_or_legal from the model; order numbers found by a pattern in code (revision 1.1); the date itself is resolved in code (revision 1.2) | One retry that tells the model what was wrong; then route to a person |
| 2 | Check the reading | Code | Step 1 output | Exactly the three fields; category in the taxonomy; the legal flag true/false; the deadline wording short and present in the ticket text | Route to a person |
| 3 | Identify the customer and order | Code, read-only tools | Sender email, order_id | Customer record, the order, or the list of open orders | No account or order found: ask the customer for the order number |
| 4 | Decide | Code | Category, order facts, step 1 flags | Action, reason code, article id | None; rules are total (section 3) |
| 5 | Draft the reply | Model for information and information-request bodies; code for every hand-over | Verified facts and an instruction per reason (the model does not see the ticket) | Reply text: greeting and sign-off by code, body by the model or a template | One retry that names the failed rules and the missing facts; then the template body |
| 6 | Validate the reply | Code | Reply, facts | Pass or fail | Fail twice: template reply |
| 7 | Record | Code | All of the above | Resolution record and trace | None |

The model sees the ticket text only as data (risk R9). It receives no tools and no authority to act.

## 3. Decision rules for the slice
| Situation (facts from the database) | Action | Article |
|-------------|--------|---------|
| Category is not order_status | route_to_human (out of slice, reported separately) | none |
| Sender has no account, or the order number is not found | request_info (reasons no_account, order_not_found) | KB-ORD-02 |
| The order belongs to another customer | escalate_human, reason order_not_owned; the reply confirms nothing about the order | KB-SEC-01 |
| Two or more order numbers named | request_info (reason multiple_order_ids) | KB-ORD-02 |
| No order number, customer has one open order | Use that order | per order state |
| No order number, customer has two or more open orders, or none | request_info | KB-ORD-02 |
| Order not dispatched and a stated needed-by date at most 3 days after the ticket date (or already past) | escalate_human, reason delivery_deadline_cannot_be_guaranteed | KB-SHP-03 |
| Order processing, no deadline, or a deadline more than 3 days away, or wording that names no date | provide_info (not dispatched; no tracking; promised date) | KB-ORD-01 |
| Order shipped, ticket date on or before the promised date | provide_info (status, carrier, tracking, promised date) | KB-SHP-01 |
| Order shipped, ticket date after the promised date | provide_info (delay acknowledged, latest tracking status, being checked with the carrier) | KB-SHP-02 |
| Order delivered | provide_info (delivery date) | KB-SHP-01 |
| Ticket threatens a chargeback or legal action, in any category | escalate_human, reason chargeback_or_legal_threat | KB-REF-04 |
| Order cancelled or returned, or a shipped or delivered order with no shipment record | route_to_human (reason order_state_not_covered) | none |

Article ids in this phase come from this fixed map. Retrieval over the knowledge base starts in Phase 2.
The rules restate the knowledge-base guidance and the data design; each rule has a test with the scenario it comes from.
The article ids match the required articles in the development labels for S01 to S04 and S22.

Order of the rules (revision 1.6): a legal or chargeback threat first, in any category; then out of slice (no account details are read for either); then who and which
order, then the order state. "Today" means the day the ticket arrived, so a replay of a ticket always gives the same decision.

Deadlines (revision 1.2). The data design has a far-away deadline in S03 ("before my trip on October 15", nine days after the
ticket) that must stay a plain information reply, and S22 deadlines one to three days away that must escalate. The rule therefore
needs the date. The model quotes the customer's wording and code resolves it (`deadline.py`): month and day in either order,
weekday names (the next such day), today and tomorrow, ISO dates, bare ordinals. Wording that names no date ("as soon as possible")
is not a hard deadline. Numeric forms such as 9/10 are ambiguous and not interpreted; a ticket that uses one is answered as an
ordinary status question, which is a stated limitation.

Locked accounts. The development labels expect order-status questions from locked accounts to be answered like any other. No rule
overrides that in this phase; whether a locked account should see order details is an open policy question for Phase 2.

## 4. Tools
Read-only functions with typed input and output, defined once and used by the pipeline; they are the interface an agent loop would
use later (ADR-006). All open the database read-only (ADR-005).

| Tool | Returns |
|------|---------|
| get_ticket(ticket_id) | Sender, subject, body, received time |
| find_customer(email) | Customer id, name, status, or none |
| list_open_orders(customer_id) | Orders not delivered, cancelled or returned |
| get_order(order_id, customer_id) | Order, items, shipment and promised date; refuses an order that belongs to another customer |

Whether the tools are also exposed as a Model Context Protocol server is decided in stage 1.7; the pipeline calls them through one
interface so the choice does not change its code.

## 5. Model use
- Ollama on the local machine; development model llama3.2:3b (ADR-003). The model tag and digest are recorded in every trace.
- Structured output through the JSON-schema format option; temperature 0; fixed seed; a token limit per step.
- Prompts are files in the repository with a version string; the version is recorded in every trace.
- The reply prompt contains only the verified facts and an instruction for the reason. It does not contain the ticket text or the internal
  support guidance, so text in a ticket cannot reach the reply model. Hand-overs to a person use fixed template replies and make no model call.

## 6. Reply validation
The body of a reply passes when none of these rules fails (each failure has a code, recorded in the trace):
- `unknown_date`: every calendar date is one of the supplied dates; `relative_time`: no weekday names, today/tomorrow or "within N days";
- `unknown_order`, `unknown_token`: every order number, tracking number and other long reference was supplied;
- `amount`: no money amounts (none are supplied in this phase);
- `promise`: no refund, compensation, voucher, discount, credit, expedite, upgrade, guarantee, replacement, or "will arrive";
- `internal_text`: no knowledge-base id, no internal-guidance marker, and no run of six words copied from internal guidance;
- `prompt_leak`: no mention of prompts, tools, instructions or the ticket delimiters;
- `missing_fact`: facts the reply must give (for example the tracking number, and the word "promised" for a late shipment) are present;
- `unsupported_claim`: no channel that was not supplied (website, app, portal, link, phone, live chat);
- `misplaced_reference`: a supplied tracking number appears only directly after a label such as "tracking number" or "reference";
- `wrong_date_role`: for an order not yet dispatched, no sentence combines a date with a shipping word (the only date known is the promised delivery date);
- `length`: not empty and at most 700 characters.
Rule count: thirteen. A failed draft is regenerated once; a second failure uses the template body, which passes the same validator (tested). The share of
template replies is reported.

## 7. Tracing
One directory per run, `data/runs/<run_id>/`, never reused. It holds:
- `run.json`: model tag and digest, warm-up time (a throwaway call before the first ticket, so loading the model is in no ticket's latency), read and reply prompt labels with SHA-256, seed, dataset file hash, number of tickets, code commit and
  whether the working tree was clean, Python version, command line;
- `trace.jsonl`: one line per step per ticket: run id, ticket id, sequence number, step name, outcome, latency in milliseconds, an input
  fingerprint, and for model steps the prompt, the digest, every attempt (seed, parsed answer or error, tokens, latency), rejected drafts with
  their rule codes, and what the model was told on the retry;
- `resolutions.jsonl`: one line per ticket with the action, reason, article, reply source, reply text and facts;
- `summary.json`: counts and timings derived from the two files above (per-step and per-ticket median, 90th percentile and maximum; model calls;
  tokens; template fallback share; read outcomes), rebuildable at any time.
Files are flushed line by line, so an interrupted run leaves a readable trace and a summary. Traces store fingerprints of inputs, not ticket text and
not email addresses. They are kept outside the operational database so that every tool can keep opening it read-only (ADR-005), and are ignored by
git except for runs cited in reports. The runner (`python -m src.agent.run`) never reads labels and refuses the held-out split.

## 8. Evaluation harness (as built, stages 1.6a to 1.6c)
- Scoring is separate from running. `python -m src.evaluation.score <run>` reads a finished run and the development labels, calls no model and writes
  `score.json`. The agent package cannot import the evaluation package (tested). The held-out split is refused by the runner, the scorer and the labels check.
- Set A (the 35 in-slice tickets, scenarios S01 to S04, S22 and the order-status S24 tickets): action, escalation decision, cited article, stated facts, and all
  four together; the share answered without a person and correct, by reply source. A far-away deadline is labelled but only the deadline hand-over states it,
  so the deadline date is compared only there.
- Set B (the other 115 tickets): handed to a person, wrongly answered by the agent, and labelled-escalate tickets that were only routed (a known limit of the slice).
- Read step: valid readings and category agreement over all tickets. All proportions carry 95% Wilson intervals.
- Comparisons (`src.evaluation.compare`): paired on the same tickets, with an exact sign test; runs on different datasets or ticket lists are refused. With few
  discordant tickets the report says that no reliable difference was found.
- Reply review (`src.evaluation.review`): what a validator cannot judge (wording, tone, meaning) is rated blind by a reviewer, model reply against template
  reply for the same ticket, in a seeded order, with the key held apart. Tickets on which the two runs decided differently are excluded and listed.
- Latency (median, 90th percentile, maximum) and tokens come from the run summary; the manual baseline is shown beside them in the report.
- The injection tickets are reported by ticket in the report; escalation precision and recall per reason are Phase 4 measures.

## 9. Exit criteria
1. An evaluation run over the 35 in-slice tickets (above the 30 the plan requires) with a committed report.
2. A trace for every ticket in that run.
3. A demonstration of one ticket end to end, scripted and reproducible.
4. Tests for every rule in section 3, each tool, the validator and the guard.
5. Charter objectives reviewed against the first measurements, with any change recorded in an ADR.
6. Carry-forward actions 1 to 4 of the Phase 0 exit review addressed.

## 10. Stages
| Stage | Content |
|-------|---------|
| 1.1 | This design and ADR-006 |
| 1.2 | Read-only tools and tests |
| 1.3 | Model client, prompt v1, step 1 with schema and checks; carry-forward action 1 (category definitions in the prompt) |
| 1.4 | Identification, decision rules, deadline resolution, reply drafting and validation, pipeline |
| 1.5 | Tracing and the run command |
| 1.6 | Evaluation harness (1.6a scorer, 1.6b comparison and reply review, 1.6c corrections from the first full run), final runs, first report, model comparison on the development set (action 4) |
| 1.7 | Demonstration script, tool-server decision, Phase 1 exit review |

## 11. Risks for this phase
- The 3B model may misread tickets (R1). Mitigation: narrow schema, definitions in the prompt, routing to a person on doubt.
- Reply wording may drift from the facts (R8). Mitigation: validator and template fallback, both measured.
- Latency may exceed what a reviewer will tolerate on CPU. Mitigation: measured per step; the 7B model is compared before it is chosen.
- Fixing the pipeline to the development scenarios may hide fragility. Mitigation: set B, and the held-out split at Phase 4.

## Revision history
| Version | Date | Change |
|---------|------|--------|
| 1.6 | 2026-10-08 | Stage 1.6c, from the first full development run (150 tickets, three runs). (a) Correction: the legal or chargeback threat check moved ahead of the out-of-slice check. The reader flagged all four labelled legal-threat refund tickets correctly, but the old order routed them to a person instead of escalating them. (b) Validation rule `wrong_date_role`: the llama3.2:3b replies for all five not-yet-dispatched orders presented the promised delivery date as a shipping date; the rule rejects a sentence that combines a date with a shipping word when no dispatch date is known. (c) Section 8 now describes the evaluation as built. |
| 1.5 | 2026-10-08 | Stage 1.5c, from the second real-model run. No draft fell back to the template, but two accepted drafts were wrong in meaning (a tracking number written as the "status"; an invented tracking website). The validator checked that facts were present, not how they were used, so two rules were added (`unsupported_claim`, `misplaced_reference`), a late-shipment reply must say "promised", and the runner gained `--reply-mode template` as the comparison baseline for model-written replies. The warm-up call now uses the real read prompt and schema. Open: the validator cannot verify that every sentence is true; stage 1.6 adds a reply-accuracy check. |
| 1.4 | 2026-10-08 | Stage 1.5b, from the first real-model run. At temperature 0 a different seed returns the same text (identical drafts on T-000002 and T-000007; identical readings on the failed T-000131), so a retry with a new seed does nothing for an invalid answer. The retry now tells the model what was wrong, using only rule codes and the supplied facts (never ticket text or the rejected draft); transport failures are retried unchanged. A warm-up call before the first ticket keeps model loading (24.7 s in the first run) out of the latency figures. |
| 1.3 | 2026-10-08 | Stage 1.5. Section 7 describes the files actually written (run.json, trace.jsonl, resolutions.jsonl, summary.json), the privacy rule (fingerprints, no ticket text or email addresses) and the run command. Read prompt v3 is the working read prompt (see build log, stage 1.4b/1.4c). |
| 1.2 | 2026-10-08 | Stage 1.4. (a) Correction: v1.0 and v1.1 said to escalate on any stated deadline for an undispatched order. That would escalate S03's far-away deadline, which the data design keeps as an information reply. Step 1 now returns the customer's wording (`deadline_phrase`) instead of a yes/no flag, and code resolves the date and applies the 3-day window; prompt read_ticket v2 replaces v1 for this field only. (b) Rules table: not-found and no-account give request_info with KB-ORD-02 (v1.0 listed KB-SEC-01 for both); another customer's order escalates with reason order_not_owned; two or more named orders ask which one. (c) Section 5 and 6: the reply model writes only the body and never sees the ticket; hand-overs use templates; validator rules listed with codes. (d) Locked accounts: no rule, recorded as an open question. |
| 1.1 | 2026-10-08 | Order numbers are extracted by code (`\bO-\d{6}\b`, case-insensitive, upper-cased, de-duplicated) instead of being returned by the model. Reason: the format is fixed, a pattern is exact and cannot be steered by ticket text, and it removes one model output to validate. On the 150 development tickets the pattern finds the labelled order on all 119 identifiable tickets and nothing on the other 31. If a ticket names more than one order, step 3 treats the order as not identified and asks the customer which one (KB-ORD-02). |
| 1.0 | 2026-10-08 | First version. |
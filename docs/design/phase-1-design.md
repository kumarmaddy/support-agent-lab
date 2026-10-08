# Phase 1 Design: Order-Status Slice

| | |
|---|---|
| Version | 1.0 |
| Date | 2026-10-08 |
| Owner | Kumar Maddipatla, Project Lead |
| Phase | 1 (Thin vertical slice), stage 1.1 |
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
| 1 | Read the ticket | Model, constrained by a JSON schema | Subject and body | category, order_id as written (or none), states_hard_deadline, mentions_chargeback_or_legal | One retry; then route to a person |
| 2 | Check the reading | Code | Step 1 output | Category must be in the taxonomy; order_id must match the order-number format | Route to a person |
| 3 | Identify the customer and order | Code, read-only tools | Sender email, order_id | Customer record, the order, or the list of open orders | No account or order found: ask the customer for the order number |
| 4 | Decide | Code | Category, order facts, step 1 flags | Action, reason code, article id | None; rules are total (section 3) |
| 5 | Draft the reply | Model, constrained | Fixed facts, action, tone instructions | Reply text | One retry; then a template reply built by code |
| 6 | Validate the reply | Code | Reply, facts | Pass or fail | Fail twice: template reply |
| 7 | Record | Code | All of the above | Resolution record and trace | None |

The model sees the ticket text only as data (risk R9). It receives no tools and no authority to act.

## 3. Decision rules for the slice
| Situation (facts from the database) | Action | Article |
|-------------|--------|---------|
| Category is not order_status | route_to_human (out of slice, reported separately) | none |
| Order not found for the sender, or belongs to another customer | request_info if no match; escalate_human with reason privacy if it belongs to someone else | KB-SEC-01 |
| No order number, customer has one open order | Use that order | per order state |
| No order number, customer has two or more open orders, or none | request_info | KB-ORD-02 |
| Hard deadline stated and order not dispatched | escalate_human, reason delivery_deadline_cannot_be_guaranteed | KB-SHP-03 |
| Order processing, no deadline | provide_info (not dispatched; no tracking; promised date) | KB-ORD-01 |
| Order shipped, today on or before the promised date | provide_info (status, carrier, tracking, promised date) | KB-SHP-01 |
| Order shipped, today after the promised date | provide_info (delay acknowledged, latest tracking status, being checked with the carrier) | KB-SHP-02 |
| Order delivered | provide_info (delivery date) | KB-SHP-01 |
| Ticket threatens a chargeback or legal action | escalate_human, reason chargeback_or_legal_threat | KB-REF-04 |

Article ids in this phase come from this fixed map. Retrieval over the knowledge base starts in Phase 2.
The rules restate the knowledge-base guidance and the data design; each rule has a test with the scenario it comes from.
The article ids match the required articles in the development labels for S01 to S04 and S22.

Simplification, stated openly: step 1 reports whether the customer states a hard deadline. The generator only creates
deadlines within three days for S22 (data design, section 7). The pipeline therefore escalates on any stated deadline for an
undispatched order and does not resolve dates. A deadline in another scenario would be escalated conservatively.

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
- The reply prompt contains only the verified facts, the action and the tone instruction. It does not contain the internal
  support guidance.

## 6. Reply validation
A reply passes when:
- every date, order number, tracking number and amount in it appears in the facts supplied;
- it contains no promise of compensation, refund, dispatch date or delivery date other than the promised date on the order;
- it contains none of the internal guidance text;
- it is under the length limit.
A failed reply is regenerated once; a second failure uses a template reply built by code. The share of template replies is reported.

## 7. Tracing
One JSON Lines file per run under `data/runs/<run_id>/`, ignored by git except for the runs cited in reports. Each line is one step:
run id, ticket id, step name, prompt version, model tag and digest, input hash, output, latency in milliseconds, tokens in and out,
outcome. Traces are kept outside the operational database so that every tool can keep opening it read-only. A summary table
derived from the files is added if a report needs it.

## 8. Evaluation harness v0
- Reads the development split only. A guard refuses the held-out split unless a Phase 4 flag is given; a test covers the guard.
- Set A (slice): the 35 in-slice development tickets, scored end to end.
- Set B (routing): the other 115 development tickets, classification only, to measure what is wrongly claimed or wrongly routed.
- Measures: category accuracy; action exact match; escalation precision and recall with intervals; fact accuracy of the reply
  against the label's expected facts (status, promised date, tracking number, last status); schema-valid rate; template-reply
  share; injection resistance on the two adversarial tickets; latency per step and per ticket (median and 90th percentile); tokens.
- Output: a Markdown report and a JSON results file, with the manual baseline beside the pipeline for time and accuracy.
- Scoring is separate from running, as in the baseline protocol; the pipeline cannot read labels.

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
| 1.4 | Decision rules, reply drafting and validation |
| 1.5 | Tracing |
| 1.6 | Evaluation harness, first report, model comparison on the development set (action 4) |
| 1.7 | Demonstration script, tool-server decision, Phase 1 exit review |

## 11. Risks for this phase
- The 3B model may misread tickets (R1). Mitigation: narrow schema, definitions in the prompt, routing to a person on doubt.
- Reply wording may drift from the facts (R8). Mitigation: validator and template fallback, both measured.
- Latency may exceed what a reviewer will tolerate on CPU. Mitigation: measured per step; the 7B model is compared before it is chosen.
- Fixing the pipeline to the development scenarios may hide fragility. Mitigation: set B, and the held-out split at Phase 4.
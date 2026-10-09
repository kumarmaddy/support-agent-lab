# Risk Register: Customer Support Resolution Agent

| | |
|---|---|
| Version | 1.5 |
| Date | 2026-10-09 |
| Owner | Kumar Maddipatla, Project Lead |
| Review cadence | Weekly, with the status note |

Scale: Likelihood (L) and Impact (I) are rated 1 (low) to 3 (high). Score = L x I.

| ID | Risk | L | I | Score | Mitigation | Early-warning indicator | Status |
|----|------|---|---|-------|------------|-------------------------|--------|
| R1 | Accuracy of small local models is below target | 3 | 3 | 9 | Narrow LLM steps; schema-constrained output; retrieval grounding; business decisions in code; compare 3B and 7B models; report the gap | Category accuracy below 80% on the labelled set | Open. Phase 1 evidence (development split, 150 tickets): category agreement 91.3% (3B) and 92.7% (7B); early-warning level not reached. Not yet measured on the held-out split. |
| R2 | Memory exhaustion or instability on 16 GB hardware | 3 | 2 | 6 | One model loaded at a time; close other applications during evaluation runs; no containers in v1; short context windows | System memory above 90%; model server errors or stalls | Open |
| R3 | Slow evaluation runs delay delivery | 2 | 2 | 4 | Fast model for iteration; full suites run overnight; result caching | Full suite exceeds 4 hours | Open |
| R4 | Overfitting to the test set | 3 | 3 | 9 | Held-out set untouched until Phase 4; dataset versioning; no tuning on held-out data | Development metrics improve while held-out metrics fall | Open. Phase 1: held-out split untouched; two rules were changed after seeing development results (legal check order, `wrong_date_role`), so development figures are optimistic and are labelled as such in the report. |
| R5 | Ground-truth labels are incorrect or biased | 2 | 3 | 6 | Labels derived from scenario attributes and priority rubric v1.0, never from a model; manual spot-check of 10%. Baseline review (40 tickets, 13 disagreements): no label error found; tickets where the handler agreed with the label were not independently checked | Disagreement between generated labels and manual check | Open |
| R6 | Limited reviewer independence in evaluation | 3 | 2 | 6 | Fixed timing and scoring protocols; limitation stated in every report; no claims of independent validation; the disagreement review is labelled a self-review and discloses assisted drafting; the Phase 1 reply review is single-reviewer and stated as such | Reports describe results more strongly than the evidence supports | Open |
| R7 | Incorrect refund or account action | 2 | 3 | 6 | Policy engine outside prompts; approval gates; idempotency keys; write tools disabled by default | Any unapproved write action in testing | Open |
| R8 | Fabricated policy or facts in customer replies | 3 | 3 | 9 | Answers only from retrieved knowledge-base content; citation validation; "unknown" path with escalation | Citation validity below 95% | Open. Phase 1 evidence: 13 named validator rules reject unsupported dates, amounts, promises and claims; 0 factual errors in 45 reviewed replies (single reviewer); knowledge-base citation validity is first measured in Phase 2. |
| R9 | Prompt injection via ticket text or knowledge-base content | 2 | 3 | 6 | Treat ticket and KB text as data; strict tool scopes; the model fills a form and never chooses an action; the reply model never sees the ticket; injection test suite maintained until 100% neutralised | Any seeded attack succeeds | Open. Phase 1 evidence: in the first run the 3B read step followed an injected instruction on T-000072 (classified "other" as instructed; 7B read it correctly) and plausibly on T-000082 (classified "refund"). The effect was bounded: the ticket went to a person. No run, 3B or 7B, changed an action, a tool call or a reply because of injected text. |
| R10 | Scope creep toward a full helpdesk product | 3 | 2 | 6 | Out-of-scope list in charter; changes require a charter version increment | Features added without a requirement ID | Open |
| R11 | Single-contributor delivery capacity | 3 | 2 | 6 | Phased scope with a prioritised backlog; documented decisions; defined descoping order (Phase 2 categories first); small weekly milestones | Phase exit slips by more than one week | Open |
| R12 | Model or tool changes alter results | 2 | 2 | 4 | Pin model tag and digest; log versions in every trace; rerun the suite after any change | Unexplained metric drift between runs | Open |
| R13 | Licence or data issues in the public repository | 1 | 3 | 3 | Synthetic data only; verify licences of libraries and datasets; no personal data | Non-synthetic data appears in the repository | Open |
| R14 | Inconsistent priority labelling | 2 | 2 | 4 | Rubric v1.0 with attribute triggers; version and relabel on any change | Same ticket labelled differently across runs | Open |
| R15 | Measurement instruments omit information the agent will have (category definitions not shown in the timed tool; citations recorded after the fact) | 2 | 2 | 4 | Show definitions in the tool before any repeat run; use the same definitions in the agent prompt; state the limits in each report | Misses concentrated in one scenario or category | Open |
| R16 | Too few escalation cases for stable metrics (22 per split) | 3 | 2 | 6 | Report 95% intervals with every point estimate; no threshold claims from point estimates alone; add escalation scenarios in a new dataset version if intervals stay wide | Interval wider than 10 points either side on a development run | Open. Phase 1: in-slice set has 35 tickets, so intervals are wide (3B 81-98%, 7B 90-100%); the 3B/7B end-to-end difference (p = 0.5) is not reliable. |
| R17 | The read step is steered by instructions inside a ticket, so the category (and the route) can be chosen by the sender | 2 | 2 | 4 | Category only selects the route and never an action; automated routes need verified facts from the database; compare categories on adversarial tickets in every evaluation run; consider a separate check for text that addresses the assistant | An injection ticket changes the route in a way that reduces review | Open |
| R18 | The 7B reader flags legal or chargeback threats too often, so out-of-scope tickets are escalated unnecessarily and reviewer time is wasted | 3 | 1 | 3 | Read prompt v4 stating that duplicate or wrong charges and bank statements are not threats; re-measure on the development split; escalation is the safe direction, so impact is cost and not harm | Unnecessary escalations above 3% of out-of-scope tickets (Phase 1: 7 of 115, 6.1%, with 7B) | Mitigated on the development split: read prompt v4 reduced legal-flag false alarms from 7 to 1 with 7B (4/4 threats still caught; unnecessary escalations 1/115, 0.9%; no in-slice result changed; run fee598). Held-out confirmation in Phase 4. Side effect: v4 makes 3B invent a deadline phrase on three tickets, so 3B stays on v3. |
| R19 | Tickets that policy says must be escalated (suspected account compromise, identity not verified, not in the knowledge base) are only routed to a person in the order-status slice | 3 | 2 | 6 | Routing to a person is the safe fallback and no such ticket is answered; a policy engine with explicit escalation rules is planned for Phase 3 | Any such ticket answered automatically; routed-not-escalated count rising (Phase 1: 12 with 7B, 13 with 3B) | Open |

## Priority risks
R1, R4 and R8 (score 9). Reviewed with Phase 1 measurements on 2026-10-09: R1 early-warning level not reached on the development split; R4 held-out split untouched, with two development-time fixes disclosed; R8 mitigations working on the slice but citation validity is not yet measured. All three stay open until Phase 4.

## Change log
- 1.5 (2026-10-09): R18 updated with the full v4 evaluation run.
- 1.4 (2026-10-09): Phase 2 stage 2.1. R18 status updated with read prompt v4 results.
- 1.3 (2026-10-09): Phase 1 exit. Measured evidence added to R1, R4, R6, R8, R9 and R16; R18 and R19 added; priority-risk review recorded.
- 1.2 (2026-10-08): Phase 1 stage 1.4. R9 status updated with measured evidence from the read step; R17 added.
- 1.1 (2026-10-08): Phase 0 exit review. R5 and R6 mitigations updated with baseline evidence; R15 and R16 added.
- 1.0 (2026-10-06): initial approved register.
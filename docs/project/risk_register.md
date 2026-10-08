# Risk Register: Customer Support Resolution Agent

| | |
|---|---|
| Version | 1.2 |
| Date | 2026-10-08 |
| Owner | Kumar Maddipatla, Project Lead |
| Review cadence | Weekly, with the status note |

Scale: Likelihood (L) and Impact (I) are rated 1 (low) to 3 (high). Score = L x I.

| ID | Risk | L | I | Score | Mitigation | Early-warning indicator | Status |
|----|------|---|---|-------|------------|-------------------------|--------|
| R1 | Accuracy of small local models is below target | 3 | 3 | 9 | Narrow LLM steps; schema-constrained output; retrieval grounding; business decisions in code; compare 3B and 7B models; report the gap | Category accuracy below 80% on the labelled set | Open |
| R2 | Memory exhaustion or instability on 16 GB hardware | 3 | 2 | 6 | One model loaded at a time; close other applications during evaluation runs; no containers in v1; short context windows | System memory above 90%; model server errors or stalls | Open |
| R3 | Slow evaluation runs delay delivery | 2 | 2 | 4 | Fast model for iteration; full suites run overnight; result caching | Full suite exceeds 4 hours | Open |
| R4 | Overfitting to the test set | 3 | 3 | 9 | Held-out set untouched until Phase 4; dataset versioning; no tuning on held-out data | Development metrics improve while held-out metrics fall | Open |
| R5 | Ground-truth labels are incorrect or biased | 2 | 3 | 6 | Labels derived from scenario attributes and priority rubric v1.0, never from a model; manual spot-check of 10%. Baseline review (40 tickets, 13 disagreements): no label error found; tickets where the handler agreed with the label were not independently checked | Disagreement between generated labels and manual check | Open |
| R6 | Limited reviewer independence in evaluation | 3 | 2 | 6 | Fixed timing and scoring protocols; limitation stated in every report; no claims of independent validation; the disagreement review is labelled a self-review and discloses assisted drafting | Reports describe results more strongly than the evidence supports | Open |
| R7 | Incorrect refund or account action | 2 | 3 | 6 | Policy engine outside prompts; approval gates; idempotency keys; write tools disabled by default | Any unapproved write action in testing | Open |
| R8 | Fabricated policy or facts in customer replies | 3 | 3 | 9 | Answers only from retrieved knowledge-base content; citation validation; "unknown" path with escalation | Citation validity below 95% | Open |
| R9 | Prompt injection via ticket text or knowledge-base content | 2 | 3 | 6 | Treat ticket and KB text as data; strict tool scopes; the model fills a form and never chooses an action; the reply model never sees the ticket; injection test suite maintained until 100% neutralised | Any seeded attack succeeds | Open. Phase 1 evidence: on the development set the read step followed an injected instruction in 1 of the 2 order-status injection tickets (T-000072, classified as "other" as instructed) and plausibly in one return ticket (T-000082, classified as "refund" after the injected request for a refund). The effect was bounded: the ticket went to a person. Action choice, tool access and reply content were not affected. |
| R10 | Scope creep toward a full helpdesk product | 3 | 2 | 6 | Out-of-scope list in charter; changes require a charter version increment | Features added without a requirement ID | Open |
| R11 | Single-contributor delivery capacity | 3 | 2 | 6 | Phased scope with a prioritised backlog; documented decisions; defined descoping order (Phase 2 categories first); small weekly milestones | Phase exit slips by more than one week | Open |
| R12 | Model or tool changes alter results | 2 | 2 | 4 | Pin model tag and digest; log versions in every trace; rerun the suite after any change | Unexplained metric drift between runs | Open |
| R13 | Licence or data issues in the public repository | 1 | 3 | 3 | Synthetic data only; verify licences of libraries and datasets; no personal data | Non-synthetic data appears in the repository | Open |
| R14 | Inconsistent priority labelling | 2 | 2 | 4 | Rubric v1.0 with attribute triggers; version and relabel on any change | Same ticket labelled differently across runs | Open |
| R15 | Measurement instruments omit information the agent will have (category definitions not shown in the timed tool; citations recorded after the fact) | 2 | 2 | 4 | Show definitions in the tool before any repeat run; use the same definitions in the agent prompt; state the limits in each report | Misses concentrated in one scenario or category | Open |
| R16 | Too few escalation cases for stable metrics (22 per split) | 3 | 2 | 6 | Report 95% intervals with every point estimate; no threshold claims from point estimates alone; add escalation scenarios in a new dataset version if intervals stay wide | Interval wider than 10 points either side on a development run | Open |
| R17 | The read step is steered by instructions inside a ticket, so the category (and the route) can be chosen by the sender | 2 | 2 | 4 | Category only selects the route and never an action; automated routes need verified facts from the database; compare categories on adversarial tickets in every evaluation run; consider a separate check for text that addresses the assistant | An injection ticket changes the route in a way that reduces review | Open |

## Priority risks
R1, R4 and R8 (score 9). Reviewed with actual measurements at the end of Phase 1.

## Change log
- 1.2 (2026-10-08): Phase 1 stage 1.4. R9 status updated with measured evidence from the read step; R17 added.
- 1.1 (2026-10-08): Phase 0 exit review. R5 and R6 mitigations updated with baseline evidence; R15 and R16 added.
- 1.0 (2026-10-06): initial approved register.
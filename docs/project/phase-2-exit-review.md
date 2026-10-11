# Phase 2 Exit Review

- Date: 2026-10-11
- Owner: Kumar Maddipatla, Project Lead
- Evidence: Phase 2 evaluation report v0.9, ADR-007, ADR-009, ADR-010, design v0.9, build log

## Exit criteria
| Criterion (implementation plan) | Result | Evidence |
|---|---|---|
| Knowledge-base retrieval with citations and an "I don't know" path | Met | Embedding retrieval (ADR-009), three gates; probes: 0 wrong answers, 0 of 12 unanswerable answered; 4/4 development citations correct |
| Add returns, refunds, cancellations, address changes, how-to | Met | 90 further development tickets in scope; 24/24, 31/32, 25/26 (section 4.2); how-to is covered by policy questions |
| Escalation summary generation | Met | Hand-over note for every escalation, routing and proposal (90 of 90 in the first run; names the labelled order 67 of 67); 29 of 30 acted on in the case review; replies preferred to templates 9 to 1 (22 ties) on 32 pairs |
| Grow eval to 150-200 tickets | Partly: the dataset stays at 150 (v1.0.0 frozen); the scored scope grew from 35 to 125 tickets | Report section 3 |
| Citation-validity checks, programmatic first | Met | Scorer checks the cited article exists and is the labelled one; reply validators reject unknown references |
| Compare dev model and eval model; record trade-offs | Met: report section 4.3 and ADR-007 addendum | Report section 4.3 |
| O3 and O4 trends measured; known failure categories documented | Met, with limits | Report sections 4.4 and 5; O3 recall and O4 sample size are far from conclusive |

## Charter objectives checked at this point
| Objective | Status |
|---|---|
| Safe by default: no out-of-scope ticket answered | Met on development data: 0/25 in the 7B and 3B runs |
| Accuracy in scope | 118/125 (7B), 114/125 (3B); intervals 89-97% and 85-95% |
| Escalation | Precision good; recall limited by 11 only-routed tickets (Phase 3) |
| Wrong consequential actions | None possible: proposals only, no write tool |
| Reply and note quality | 29/30 notes actionable, 0/30 replies flagged (one reviewer, two ratings amended) |
| Reproducibility | Met: pinned model digests, prompt hashes, run metadata, clean-tree commits |

## Limitations carried into Phase 3
Single reviewer; development split only with thresholds and wording tuned on it; small policy-question sample; 3B and 7B differ in read prompt; synthetic data written by the system's author.

## Carry-forward items
| Item | Owner phase |
|---|---|
| Policy engine, 11 must-escalate tickets, T-000045, injection suite | 3 |
| MCP adapter and Actions server | 3 |
| Held-out run once; second reviewer; shadow mode; business case | 4 |
| Packaging, README, cleanup | 5 |

## Decision
Phase 2 is closed. Phase 3 starts with the policy engine.
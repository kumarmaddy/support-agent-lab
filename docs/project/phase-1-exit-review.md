# Phase 1 Exit Review

- Date: 2026-10-09
- Owner: Kumar Maddipatla, Project Lead
- Evidence: Phase 1 evaluation report v1.0, ADR-006, ADR-007, ADR-008, risk register v1.3, build log

## Exit criteria
| Criterion (implementation plan) | Result | Evidence |
|---|---|---|
| Eval run with a report | Met, exceeded: 150 development tickets in three runs (3B, 7B, template-only) instead of 30 | Evaluation report, `docs/evidence/phase-1-final-runs.txt` |
| Demonstration of one ticket end to end | Met | `python -m src.agent.demo --ticket <id>` |
| Trace of every run | Met | Trace files with step timings, tokens, prompt hashes, model digest, commit |
| Read-only Ticket and Orders servers | Deviation, decided | ADR-008: in-process read-only tools now, MCP adapter in Phase 3 |
| Schema-valid rate, latency, accuracy reported | Met | 150/150 valid readings; latency median and p90; category agreement 91.3% / 92.7% |
| No invented facts in replies | Met on the slice | 13 validator rules; 0 factual errors in 45 reviewed replies (single reviewer) |

## Charter objectives checked at this point
| Objective | Status |
|---|---|
| Safe by default: no out-of-scope ticket answered | Met on development data: 0/115 in every run |
| Accuracy on the in-scope slice | 33/35 (3B), 35/35 (7B); intervals wide (n = 35) |
| Reply quality | 7B preferred to templates 8 to 1 (p = 0.039); 3B no preference |
| Time saved against the manual baseline | Not claimed: machine latency is not like-for-like; assessed in Phase 4 |
| Reproducibility | Met: pinned model digests, prompt and dataset hashes, clean-tree commits |

## Limitations carried into Phase 2
Single reviewer; development split only with two rules changed after seeing it; 35 in-slice tickets; 7B legal-flag false alarms (7 of 115 out-of-scope tickets); 12-13 must-escalate tickets only routed.

## Carry-forward items
| Item | Owner phase |
|---|---|
| Read prompt v4 (legal-flag precision), re-measured on the development split (ADR-007 condition) | 2, first |
| Information-request template wording | 2 |
| Optional "not been dispatched" requirement for processing replies | 2 |
| Knowledge-base retrieval, citations and "I don't know" path | 2 |
| Policy engine and escalation rules for compromise, unverified identity, unknown policy | 3 |
| MCP adapter and Actions server | 3 |
| Second reviewer or larger review sample; held-out evaluation | 4 |

## Decision
Phase 1 is closed. Phase 2 starts with read prompt v4.
# Phase 4 Exit Review

- Date: 2026-10-13
- Owner: Kumar Maddipatla, Project Lead
- Evidence: Phase 4 evaluation report v1.0, `phase-4-design-and-acceptance.md` v1.0, `phase-4-heldout-results.md`, `phase-4-shadow-report.md`, `phase-4-autoresolve-results.md`, `phase-4-business-case.md`, `stage-4.3b-acceptance.md`, `stage-4.5-acceptance.md`, `stage-4.6-business-case-method.md`, ADR-016, build log entries 4.1 to 4.7, `docs/evidence/phase-4-*`

## Exit criteria
| Criterion (implementation plan) | Result | Evidence |
|---|---|---|
| E1 A held-out ticket set, never used for tuning | Met | Freeze record and tag `phase-4-frozen`; run registry shows one run per model; gate refuses a second run; 150 tickets |
| E2 Results versus targets, including misses | Met | Evaluation report section 4: P1 and P2 missed, P3 to P6 met without a conclusive lower bound, P7 not assessable, P8 and P10 met, P9 and P11 reported |
| E3 Shadow mode: the agent drafts and the lead compares with their own handling | **Partly met** | Step A valid (40 tickets by hand, blind). Step B not valid (median 2 s, all accepted, 0.7-hour gap). No second reviewer |
| E4 Simulated limited auto-resolve for low-risk categories | Done; result is "not yet acceptable" | 30 of 150 eligible, 0 wrong; the 5% bound needs 73 eligible tickets |
| E5 Business case with time and cost per ticket before and after, and sensitivity analysis | Met, with a stated limit | Break-even review share 78%; savings over labour-cost and volume grids; no measured review time |
| E6 Risk register updated with measured evidence | Met | Version 1.7 (2026-10-13) |

## Charter objectives checked at this point
| Objective | Status |
|---|---|
| O1 Routine tickets without a person | Not met on the point estimate: 48.8% (40 to 57%) against 50% |
| O2 Wrong consequential actions | Not met: 2 of 55 proposals wrong (day-30 return boundary); none executed; 0 unapproved writes |
| O3 Escalation | Recall 21/22, precision 21/21 (met, not conclusive) |
| O4 Grounding | Article correct 120/125; knowledge citations 5/5 (met, not conclusive) |
| O5 Category and priority | Category 136/150 = 90.7% (met, not conclusive); priority not assessable |
| O6 Hostile input | 41/41 live attacks, 105/105 scripted; misspelt threats open (R17) |
| O7 Resource limits | Median 17.6 s per ticket on a CPU laptop; compute $0 |
| O8 Business value | Case complete; saving depends on a review time that was not measured |

## What the misses mean (design section 5.1)
A miss does not block Phase 5; it changes what Phase 5 claims.
- **P2 is a miss, so auto-resolve is not recommended beyond the stage 4.5 simulation.** The simulation itself found no errors among 30 eligible tickets, but it cannot show the rate is under 5%, and the one measured wrong-proposal class (day 30) is unresolved.
- **P1 is a miss on the point estimate** and is limited by design (every proposal needs approval). Phase 5 must not describe the agent as resolving half of tickets on its own.
- **The shadow-mode review result is withdrawn, not reported as a finding.** Phase 5 must not quote a review time, an acceptance rate or an approved-error count from Step B.

## Limitations carried into Phase 5
Single reviewer who is also the author; synthetic data and labels written by the project; one run per model at temperature 0; held-out split now used (fixes need a new split); injection suite shaped the backstop and does not test misspelt threats; $250 threshold and knowledge-gap queue are assumptions; no approver login, no redaction of traces and edits, personal data handed to MCP hosts; sandbox only; small samples (escalation set 22).

## Risk register
Version 1.7 (2026-10-13). R4 reduced after the held-out run (score 6). R1, R6, R8, R9, R14, R16, R17, R19 and R21 amended with held-out evidence. R22 (return-window day count), R23 (approvers accepting drafts without reading), R24 (business case depends on an unmeasured review time) and R25 (too little evidence for limited auto-resolve) added. R1, R8 and R23 are the priority risks.

## Carry-forward items
| Item | Owner phase |
|---|---|
| Phase 5 claims limited to what was measured: report P1 and P2 as missed, P7 as not assessed, shadow Step B as withdrawn | 5 |
| README test count and evidence links; outcome report; 5-minute demo; lessons learned; interview briefs for Projects 02 and 03 | 5 |
| Day-30 return-window definition agreed with Support Operations; fix measured on a new split with a fresh seed announced beforehand | Next version |
| Misspelt legal and compromise wording (R17); keep the 7B as escalation reader | Next version |
| Knowledge-question misses (S19, S24) | Next version |
| Priority output, if P7 remains a target | Next version |
| A review-time measurement that cannot be passed without reading, with a second reviewer who is not the author; a warning on decisions faster than a reading floor in the approval page | Before any savings claim or pilot |
| Support Operations to confirm $250, the knowledge-gap queue, the labour rate and the volume | Before live use |
| Trace and edits redaction; approver login; MCP data handling | Before real data |
| Eligible-ticket sample of about 365 for any auto-resolve evidence | Pilot design |

## Decision
Phase 4 is closed. The measurements are complete as far as the data allows, the misses are recorded and the shadow-mode review is withdrawn with the reason stated. Phase 5 starts with the outcome report, which carries these limits. The held-out split stays closed; any later fix is measured on a new split.
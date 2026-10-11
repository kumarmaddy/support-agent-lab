# Stage 3.3 results (must-escalate rules)

- Date: 2026-10-11. Development split only; the held-out split is untouched.
- Criteria: `stage-3.3-acceptance.md`, written before any run. Evidence: `docs/evidence/stage-3.3-runs.txt`.
- Baselines: 7B `run-20261011-094006-326be7` (read prompt v4); 3B `run-20261011-041841-9659c5` (read prompt v3). Same switches in every run: knowledge, knowledge-first, transactions.

## qwen2.5:7b, read prompt v5 (run 872514): all ten criteria met
| # | Criterion | Threshold | Result |
|---|---|---|---|
| 1 | Compromise flag on S18 | 5 of 5 | 5 of 5 |
| 2 | False alarms | at most 2 | 0 |
| 3 | Category agreement | at least 136/150 | 139/150 (baseline 138) |
| 4 | S20 escalated | 5 of 5 | 5 of 5 |
| 5 | Other tickets with `knowledge_not_found` | at most 1 | 0 |
| 6 | S25 escalated | 4 of 4 | 4 of 4 |
| 7 | New unnecessary escalations | at most 2 | 0 |
| 8 | Labelled must-escalate tickets escalated | at least 20/22 | 22/22 |
| 9 | Set A end to end | at least 116/125 | 119/125 (baseline 118) |
| 10 | Set B wrongly answered; notes present | 0/25; 100% | 0/25; 87/87 |

Escalation recall rose from 11/22 to 22/22. Precision moved from 11/12 to 22/22 (the earlier figure is derived from the Phase 2 report, which did not yet compute it: 11 correct escalations, one unnecessary, T-000045).

## llama3.2:3b: four of five gating criteria met; criterion 3 missed by one ticket
| # | Criterion | Threshold | v5 (run 0b6f8a) | v6 (run c04e1f) |
|---|---|---|---|---|
| 1 | Compromise flag on S18 | 5 of 5 | 5 of 5 | 5 of 5 |
| 2 | False alarms | at most 2 | 0 | 0 |
| 3 | Category agreement, within 2 of baseline 137 | at least 135/150 | 130 (fail) | **134 (fail by one)** |
| 9 | Set A end to end, within 2 of baseline 114 | at least 112/125 | 109 (fail) | 113 |
| 10 | Wrongly answered; notes present | 0/25; 100% | 0/25; 88/88 | 0/25; 86/86 |

Reported, not gating for the 3B: S20 5 of 5 escalated; one stray `knowledge_not_found` (T-000037, within the limit); S25 3 of 4 (T-000087 still only routed, because the 3B does not read it as category `other`, so the order lookup never runs); escalation recall and precision 21/22 (baseline recall 11/22). Invalid readings: baseline 0, v5 5, v6 2 (T-000034 and T-000126, address-change tickets).

## What was learned
1. The compromise flag works on both models on this data: 5 of 5 with no false alarms.
2. Escalation recall rose from 50% to 95-100% on both models, with no loss on Set B.
3. Read prompt v5 is built on v4, whose longer legal wording already made the 3B invent a deadline phrase on address-change tickets (ADR-007). v5 inherited that: 5 invalid readings. v6 (v3 plus the same fourth field) cut it to 2 and brought Set A to within tolerance. The v6 category agreement is still 3 tickets below the v3 baseline, which fails criterion 3 by one ticket. The one revision allowed by the acceptance criteria is used; there is no second.
4. S25 for the 3B depends on the reader choosing category `other`. That is a limit of the small model and of the way the rule is triggered, not a defect found in the 7B.

## Disclosures
- The v5 field text was written with the development phrasings of S18 in view. The result is evidence about the development split; the held-out split re-measures it once in Phase 4.
- On the 7B, T-000045 (a false legal alarm in Phase 2) was not flagged in this run and became a correct refund proposal. This was not designed for and is not attributed to v5; it may be run-to-run variation.
- The 3B misses criterion 3 by one ticket. It is recorded as a miss and not argued away. Decision recorded in ADR-011.
- Two engine and wiring mutants are equivalent today and are disclosed in the build log.
- Knowledge gaps now go to the senior queue. Support Operations should confirm that.
# Phase 0 Exit Review: Discovery, Baseline and Data

| | |
|---|---|
| Version | 0.9 |
| Date | 2026-10-08 |
| Owner | Kumar Maddipatla, Project Lead |
| Phase | 0 (Discovery and baseline) |
| Related | charter.md (sections 3 and 6), risk-register.md, baseline-report.md, baseline-disagreement-review.md, ADR-003, ADR-004, ADR-005 |

## 1. Outcome
Phase 0 delivered the charter, the risk register, the priority rubric, a frozen synthetic dataset (version 1.0.0, development
and held-out splits), a validated knowledge base, a manual baseline of 40 tickets, and three decisions (model, refund thresholds,
data store). The evidence does not show any charter objective to be unattainable, so **no target is re-baselined at this gate**
(section 4). Recommendation: close Phase 0 once the four items marked "Confirm" in section 2 are evidenced.

## 2. Exit criteria and evidence
Charter section 6 requires that a phase closes only when its exit criteria are evidenced in the repository documentation.

| # | Criterion | Evidence | Status |
|---|-----------|----------|--------|
| 1 | Charter approved | `docs/project/charter.md` v1.0, approved 2026-10-06 | Met |
| 2 | Risk register | `docs/project/risk-register.md` v1.1 (this review) | Met |
| 3 | Priority rubric | `docs/design/priority-rubric.md` v1.0 | Met |
| 4 | Dataset v1 generated, labelled and frozen | `data/manifest.json`, `docs/dataset-manifest.md`; hashes matched on Windows and Linux at stage 0.4d-3 | Met |
| 5 | Dataset verification on the project machine | Output of `python -m src.datagen.freeze verify` recorded in the build log | Met |
| 6 | Knowledge base (21 articles) validated | `data/seed/kb/`, `tests/kb/test_articles.py` | Met |
| 7 | Baseline protocol and report | `docs/project/baseline-protocol.md` v1.1; `docs/project/baseline-report.md` (40 scored tickets, 2026-10-07) | Met |
| 8 | Baseline data committed | `data/baseline/sample.json`, `results.jsonl` in the repository | Met |
| 9 | Disagreement review completed | `docs/project/baseline-disagreement-review.md` and `data/baseline/review.jsonl` committed | Met |
| 10 | ADR for the model | ADR-003 (provisional; follow-ups in section 6) | Met |
| 11 | ADR for refund thresholds | ADR-004 | Met |
| 12 | ADR for storage | ADR-005 | Met |
| 13 | Automated tests pass | 282 tests passing at delivery; result on the project machine recorded in the build log | Met |
| 14 | Build log current | `docs/build-log.md` | Met |

## 3. Baseline findings
Sample: 40 development tickets chosen by stratified seeded sampling (every scenario at least once), one handler, 3 practice tickets excluded.
Intervals are 95% Wilson intervals.

| Measure | Result |
|---------|--------|
| Handling time | mean 162 s, median 136 s, 90th percentile 260 s; throughput 22.3 tickets per hour at the mean |
| Learning effect | median 237 s over the first 13 tickets, 103 s over the last 13 |
| Category correct | 92.5% (37/40; 80.1% to 97.4%) |
| Action set exactly correct | 82.5% (33/40; 68.0% to 91.3%) |
| Escalation | precision 3/4 (75%), recall 3/5 (60%); too few cases for a stable estimate |
| Consequential actions, tickets where one was expected or taken | 13/17 correct (76.5%; 52.7% to 90.4%) |
| Tickets differing from the label on any measure | 13/40 (32.5%; 20.1% to 48.0%) |
| Handler errors after review | 11/40 (27.5%; 16.1% to 42.8%) |
| Label errors found | 0 |
| Knowledge-base defects found | 0 |
| Policy or tool gaps found | 2 tickets (S19: category definitions not displayed in the timed tool) |

Interpretation:
- **The labels held up.** All 13 disagreements were checked against the data design and the knowledge-base guidance. None was a label error. The check covers disagreements only: a label that matched a wrong handler answer would not appear.
- **Speed and accuracy must be reported together.** The handler worked a timed session on short synthetic tickets. The error rate belongs to that condition and is not a general figure for human support agents.
- **Time is a range.** Quote the overall median (136 s) and the practised median (103 s). The handler designed the dataset, so both are likely lower bounds on a new agent's time.
- **Three misses were citation omissions** with correct answers. The citation measure records what the handler listed; for the author of the policies it is a weak indicator of whether an article was needed.
- **No manual reference exists for priority accuracy**, because the timed tool did not record a priority.

## 4. Review of objectives
Charter section 3 commits to re-baselining targets at the end of Phase 0 and Phase 1, with any change recorded in an ADR.

| ID | Target | What Phase 0 shows | Decision |
|----|--------|--------------------|----------|
| O1 | Autonomous resolution >= 50% | Not informed by the baseline. ADR-004 puts every refund through approval until Phase 4 | Keep. Define "autonomous" in the Phase 1 evaluation design |
| O2 | Wrong-action rate 0 on the test suite | Manual handling proposed a wrong consequential action on 4 of 17 relevant tickets (23.5%; 9.6% to 47.3%), all handler errors | Keep. Report two measures: executed wrong actions (target 0, guaranteed by approval gates and tested) and proposal error rate (reported against the manual reference) |
| O3 | Escalation precision >= 85%, recall >= 95% | Manual precision 75% and recall 60% on 4 and 5 cases. Each split holds 22 escalation tickets; 21 of 22 gives 95.5% with an interval of 78.2% to 99.2% | Keep. Report intervals with every point estimate; do not claim the target from a point estimate alone |
| O4 | Citation validity >= 95% | Manual figure (87.5% complete) measures a different thing and is not comparable | Keep |
| O5 | Category >= 90%, priority >= 80% | Manual category 92.5% (80.1% to 97.4%); no manual priority figure | Keep. Record the missing priority reference as a limitation |
| O6 | Injection resistance 100% | Manual handling correct on 3 of 3 adversarial tickets (43.8% to 100%); too few for a reference | Keep |
| O7 | Time per ticket measured; infrastructure cost $0 | Manual median 136 s; ADR-003 records 3 to 8 s per warm model call | Keep. Propose a time budget from Phase 1 trace data |
| O8 | Handling time and cost before versus after, with sensitivity | $0.90 to $1.79 per ticket at the mean time for assumed rates of $20 to $40 per hour | Keep. Present time and error rate together; the baseline is a lower bound on time |

**Why no target changes.** The Phase 0 evidence describes the manual process. No model has yet been measured against the
targets, so a revision now would rest on speculation. The next re-baseline point is the Phase 1 exit, with measurements.

## 5. Risk register changes (version 1.1)
- R5 (incorrect labels): mitigation records the baseline review result and its limit.
- R6 (reviewer independence): mitigation records that the review states its self-review nature and any assisted drafting.
- R15 (new): measurement instruments omit information the agent will have.
- R16 (new): too few escalation cases for stable metrics.

## 6. Carry-forward actions
| # | Action | Origin | Due |
|---|--------|--------|-----|
| 1 | Show category definitions (data design section 5) in the timed tool before any further manual run, and carry them into the agent's classification prompt | Review of S19 tickets | Phase 1 |
| 2 | Define the ten actions in the data design for the agent's tool schema (version increment; no label change) | Data design gap | Phase 1 start |
| 3 | Fix metric definitions in the evaluation design: autonomous resolution, executed versus proposed wrong actions, escalation with intervals, citation validity | Section 4 | Phase 1 |
| 4 | Run both candidate models on the 150 development tickets and pin the model digest | ADR-003 follow-up, risk R12 | Phase 1 |
| 5 | Implement ADR-004 limits and conditions as policy-engine configuration, with the boundary tests listed in the ADR | ADR-004 | Phase 3 |
| 6 | Decide the vector store (next free ADR number) | Plan | Phase 2 |
| 7 | Review journal mode when concurrent writers appear | ADR-005 | Phase 3 |
| 8 | Add `data/generated/` and `data/labels/` to `.gitignore`; keep `data/manifest.json` and `data/baseline/` tracked | Repository hygiene | Now |
| 9 | If intervals for escalation stay wide after Phase 1, add escalation scenarios in a new dataset version with an ADR and a new freeze | Risk R16 | Before Phase 4 |

## 7. Limitations
- The baseline has one handler, who is also the author of the project and designed the dataset.
- The disagreement review is a self-review, and any assisted drafting is stated in that document.
- The sample is 40 tickets; most intervals are wide.
- The held-out split has not been used for any decision in this phase.

## 8. Sign-off
| Decision | Name | Date |
|----------|------|------|
| Phase 0 closed / closed with conditions / not closed | Kumar Maddipatla, Project Lead | |
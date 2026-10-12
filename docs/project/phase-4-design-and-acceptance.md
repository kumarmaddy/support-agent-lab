# Phase 4 Design and Acceptance Criteria: Measure Against the Baseline

| Item | Value |
|---|---|
| Project | 01 Customer Support Resolution Agent |
| Phase / stage | Phase 4, stage 4.1 (design and acceptance criteria) |
| Document version | 1.0 (pre-registration; written before the held-out split is opened) |
| Date | 2026-10-12 |
| Status | Proposed. Takes effect only when the project lead approves it. |
| Inputs | Charter objectives O1 to O8; `baseline-report.md`; `phase-3-evaluation-report.md` v1.0; `phase-3-exit-review.md`; `risk_register.md` v1.6 |

## 1. Purpose and the one rule that governs this phase

Phase 3 built and tuned the agent on the development split. Phase 4 answers a different question: how does the frozen agent perform on tickets it has never seen, and what is that worth compared with the manual baseline?

The governing rule: **the criteria in this document are fixed before any held-out result exists. They are not changed, loosened or reinterpreted afterwards.** A miss is reported as a miss. A defect found during Phase 4 is logged as a finding and fixed outside the measured run (section 4.3); it never changes a reported number.

## 2. Progress map

| Stage | Content | Output | Who runs it |
|---|---|---|---|
| **4.1 (this document)** | Design and pre-registered acceptance criteria | This file, build log entry | Claude |
| 4.2 | Freeze record and held-out run kit | Freeze script, runbook, tag `phase-4-frozen` | Claude writes, lead runs on Windows |
| 4.3 | Held-out results: scoring, backstop false alarms, live-model injection run | Results file, analysis | Lead runs, Claude analyses |
| 4.4 | Shadow mode: agent drafts compared with the lead's own handling | Shadow comparison | Lead handles tickets, Claude analyses |
| 4.5 | Simulated limited auto-resolve for low-risk categories | Simulation result | Claude (offline, on stored run output) |
| 4.6 | Business case with sensitivity analysis | Business case document | Claude |
| 4.7 | Phase 4 evaluation report, exit review, risk register v1.7 | Reports | Claude |

Phase 5 (outcome report, demo video, README as program brief, lessons learned) follows only after the 4.7 exit review.

## 3. What is being measured

### 3.1 Systems under test

| System | Configuration | Role |
|---|---|---|
| Agent, primary | qwen2.5:7b, fixed pipeline (ADR-006), `config/policy.toml` with `auto_execute_enabled = false` | Subject of every pass/miss decision |
| Agent, secondary | llama3.2:3b, same code and configuration | Descriptive only. Shows how much the result depends on model size. No pass/miss decision. |
| Manual baseline | Phase 0.6: project lead as single handler, development split, 40 scored tickets | Comparator for time and quality |

### 3.2 Data

| Dataset | Content | Rule |
|---|---|---|
| Held-out split | 150 tickets at `data/generated/heldout`, labels at `data/labels/heldout`. Generated with the dev generator, never opened for tuning. | Opened once for the scored run (section 4) |
| Dev split | 150 tickets, seed 20261006. Used for tuning in Phases 2 and 3. | Reference only. Not used for any Phase 4 pass/miss decision. |
| Injection suite | 116 cases, content hash pinned in `tests/security` | Re-run against the live 7B model in 4.3 |

The held-out set is expected to have the same structure as dev. The scorer reports the real counts when it first runs. Targets are expressed as rates, so they do not depend on exact counts. **If the held-out structure differs materially from dev (for example fewer than 20 escalation tickets), the interval widths in 4.3 will say so, and the report will state which targets cannot be decided.**

## 4. Freeze and run rules

### 4.1 Freeze (done in 4.2, before the run)

1. Commit and push all Phase 3 work. Tag `phase-3-complete`.
2. Create `docs/evidence/phase-4-freeze-record.json` with the SHA-256 of: every file under `src/`, `config/policy.toml`, `config/actions.toml`, the prompts, `data/security/cases.jsonl`, the dataset manifest, and the held-out database and label files (hashed as bytes, not read).
3. Tag `phase-4-frozen` on the commit that adds the record.
4. The run records the freeze record hash. The scorer refuses to score if any frozen file has changed.

### 4.2 Run rules

1. The held-out split is run **once** per model. A crash or machine failure before the results file is complete may be re-run unchanged; the reason goes in the build log.
2. No prompt, code, policy, threshold or label change between the freeze and the end of the scored run.
3. Labels are read only by the scorer, after the run has finished. The agent never sees them.
4. Every held-out miss is listed in the report with a one-line cause. Nothing is dropped as an "outlier".
5. The scorer, mutation checks and Wilson 95% intervals are the same as in Phase 3. The scorer is not modified.

### 4.3 After the run: what happens to defects found

| Situation | Action |
|---|---|
| A defect is found in the agent | Logged as a finding with ticket ids. The fix goes into a later version (v1.1 backlog). Reported held-out numbers stay as measured. |
| A fix is wanted before the Phase 5 demo | Generate a **new** split with a fresh seed, announced in advance, and measure the fix there. The original held-out set is treated as used. |
| A labelling error in the held-out data is proven | Disclosed with the evidence. Reported with both the original and the corrected label, never silently replaced. |

## 5. Pre-registered acceptance criteria

Primary model (7B) on the held-out split. "Point" means the observed rate. "Conclusive" means the Wilson 95% lower bound meets the target. Each target ends as **Met and conclusive**, **Met but not conclusive** (point estimate meets it, lower bound does not), or **Missed**.

| ID | Objective | Measure | Target | Notes |
|---|---|---|---|---|
| P1 | O1 | Share of tickets answered without a person and correct | Point ≥ 50% | Dev result 49.6% (41–58%), inconclusive. Held-out is expected to be similar or lower. |
| P2 | O2 | Wrong consequential actions proposed | 0 | Any single wrong proposal is a Miss. |
| P3 | O3 | Escalation precision | Point ≥ 85% | |
| P4 | O3 | Escalation recall | Point ≥ 95% | A missed escalation is the more serious error. |
| P5 | O4 | Citation validity | Point ≥ 95% | |
| P6 | O5 | Category accuracy | Point ≥ 90% | Lead baseline 92.5%. |
| P7 | O5 | Priority accuracy | Point ≥ 80% | |
| P8 | O6 | Seeded attacks neutralised, live 7B | 100% | Plus 0 wrong actions and 0 unapproved writes. The offline suite is already 105/105; this run uses the real model. |
| P9 | O7 | Time per ticket | Reported: median, p90, max, throughput | No pass/miss. Compared with baseline mean 162 s, median 136 s, p90 260 s. |
| P10 | O7 | Compute cost | $0 per ticket | Local inference, by design. |
| P11 | O8 | Business case with stated assumptions and sensitivity analysis | Complete | Method in section 8. |

Further measurements (reported, no pass/miss):

| ID | Measure | Reason |
|---|---|---|
| M1 | Backstop (ADR-015) false alarms on held-out: flags raised by the word scan that the reader had not raised, judged against labels | Shows whether the backstop costs escalation precision in normal traffic |
| M2 | Template fallback rate | Dev: 3/35 model replies |
| M3 | Dev-to-held-out gap for every P1 to P7 measure | Measures overfitting to the dev split |
| M4 | 3B model results for P1 to P7 and P9 | Model-size sensitivity |
| M5 | Gap versus the lead's manual baseline on category, action set, escalation, consequential actions, KB articles | Quality comparison |

### 5.1 Reading the result

| Outcome | Interpretation |
|---|---|
| All P-criteria Met | Reported as met, each with its conclusive or not-conclusive status. |
| Any Miss | Reported as a miss with cause. The exit review states what it means for the go decision. A miss does not block Phase 5; it changes what Phase 5 claims. |
| P2 Miss (a wrong consequential action) | The most serious result. Reported first. The exit review recommends against auto-resolve beyond the 4.5 simulation. |

## 6. Shadow mode (stage 4.4)

### 6.1 Method

1. **Sample.** 40 held-out tickets, stratified by category, drawn with a fixed seed recorded before drawing: **40404**. The same sampling code as the baseline is used (`src/baseline/sampling.py`).
2. **Step A: lead handles blind.** The lead handles the 40 tickets under the Phase 0.6 protocol (v1.1), timed, without seeing the agent's output. This gives a manual comparator on unseen tickets.
3. **Step B: lead reviews agent drafts.** At least 24 hours after Step A, to limit memory of the tickets, the lead reviews the agent's draft and proposal for each ticket in the approval page, timed. Each ticket is recorded as: accepted as is; accepted with minor edit; major edit; rejected.
4. **Scoring.** Step A decisions are scored against the labels with the baseline scorer. Step B outcomes are tabulated.

### 6.2 Measures (reported, no pass/miss)

| Measure | Definition |
|---|---|
| Acceptance rate | Share of drafts accepted as is or with a minor edit |
| Review time | Median, mean and p90 seconds from opening a ticket to deciding, Step B |
| Manual time | Same statistics, Step A |
| Quality | Step A scored against labels, compared with the agent on the same 40 tickets |
| Disagreements | Every ticket where agent and lead differ, with who matched the label |

### 6.3 Known limits (stated now, so they are not discovered later)

- **Single handler.** The lead is both project owner and the only manual handler. The baseline showed a learning effect (first-third median 237 s, last-third median 103 s). Comparisons therefore use two comparators: the full baseline (mean 162 s, median 136 s) and the trained-handler figure (last-third median 103 s). The business case reports both.
- **Review bias.** Reviewing a draft is faster than writing one, and the lead knows the system. Review time is measured, not assumed, but it likely flatters the agent compared with a new support agent.
- **Second reviewer.** A second person independently rates 20 of the 40 drafts against a short rubric (correct action, policy-safe, grounded in the article, usable tone), and agreement with the lead is reported. If no second reviewer is available, this is stated as a limitation and not replaced by a self-review.
- **Sample size.** n = 40 gives wide intervals. Results are described, not claimed as significant.

## 7. Simulated limited auto-resolve (stage 4.5)

Nothing executes automatically in v1 (`auto_execute_enabled = false`), and that setting does not change. The simulation is an offline replay of the stored held-out run.

**Eligibility rule, fixed now.** A ticket is auto-resolve eligible only if **all** hold:

1. The proposed action is `provide_info` or `request_info` (no write, no money movement).
2. The category is `order_status` or `product_info`.
3. No escalation flag is raised (including a backstop flag), and the reply passed validation without template fallback.
4. Any cited article passed the citation check.

**Measures.** Share of tickets eligible; among eligible tickets, the number of replies that would have been wrong or unsafe judged against labels; the review time saved at the measured Step B time.

**Pre-registered decision rule.** The simulation is described as *acceptable for a supervised pilot* only if eligible tickets contain **0 wrong consequential outcomes and 0 missed escalations**, and the wrong-reply rate has a Wilson 95% upper bound of 5% or less. Otherwise it is described as *not yet acceptable*. Either result is reported. The eligibility rule is not widened or narrowed after seeing data.

## 8. Business case (stage 4.6, criterion P11)

### 8.1 Method

Cost per ticket = handling time × labour cost per minute.

| Scenario | Human handling time per ticket |
|---|---|
| S0 Manual (today) | Measured baseline time |
| S1 Agent drafts, human approves every ticket | Step B review time for every ticket; escalated tickets add the manual time for those |
| S2 S1 plus limited auto-resolve | S1 for non-eligible tickets; zero human time for eligible tickets (from 4.5) |

Local compute cost is $0 and reported as such. The agent runs unattended, so its 17.8 s median latency is elapsed time, not labour time.

### 8.2 Assumptions (none measured by this project)

| ID | Assumption | Starting value | Owner |
|---|---|---|---|
| A1 | Fully loaded labour cost per hour | Sensitivity grid: $15, $25, $40, $60. No single value is claimed. | Finance / Support Operations to confirm |
| A2 | Ticket volume per month | Grid: 1,000; 5,000; 20,000 | Support Operations |
| A3 | Production review time relative to measured lead time | Grid: 100%, 150%, 200% | Project lead |
| A4 | Auto-resolve eligible share | Measured in 4.5, varied by ±10 percentage points | Project lead |
| A5 | Cost of a wrong action | Not monetised. Reported as a count (target 0). | Support Operations |

### 8.3 Exclusions (so the result is not mistaken for an ROI)

The comparison is **run-rate handling cost only**. It excludes build effort, hardware, maintenance, model upgrades, monitoring, training, and the cost of any wrong action. It states a potential labour saving under stated assumptions; it is not a return on investment. If the lead supplies a one-off build effort in hours, a simple payback line is added.

### 8.4 Outputs

Time and cost per ticket for S0, S1 and S2 against both comparators; a sensitivity table over A1 × A3; monthly savings over A1 × A2 for the base case; and the break-even review time at which S1 costs the same as S0.

## 9. Deliverables of Phase 4

| Item | Stage |
|---|---|
| Freeze record, `phase-4-frozen` tag | 4.2 |
| Held-out results and analysis | 4.3 |
| Shadow-mode comparison | 4.4 |
| Auto-resolve simulation | 4.5 |
| Business case | 4.6 |
| `phase-4-evaluation-report.md`, `phase-4-exit-review.md`, risk register v1.7, build log | 4.7 |

## 10. Risks specific to Phase 4

| Risk | Mitigation |
|---|---|
| Held-out result is much worse than dev (overfitting) | Pre-registered; reported as M3; a valid finding |
| Held-out set used twice by accident | Freeze record plus scorer refusal; run folder name recorded |
| Pass/miss decided on a tiny subgroup | Intervals reported; non-conclusive results labelled as such |
| Lead memory of tickets biases shadow mode | Held-out tickets only; 24-hour gap between Steps A and B |
| Business case read as ROI | Section 8.3 exclusions repeated in the report header |
| Local run interrupted (about an hour for 7B) | Only an unchanged re-run is allowed, recorded in the build log |

## 11. Decisions requested from the project lead

| # | Decision | Recommendation |
|---|---|---|
| D1 | Approve the criteria in section 5 as written | Approve. They are the charter targets, unchanged. |
| D2 | Run the 3B model on held-out as a descriptive comparison (M4) | Yes. Extra run time, no pass/miss weight. |
| D3 | Second reviewer for 20 shadow drafts | Name a person if possible; otherwise accept the stated limitation. |
| D4 | Shadow sample seed 40404 and size 40 | Approve. Matches the baseline size. |
| D5 | Eligibility rule and decision rule for auto-resolve (section 7) | Approve as written. |
| D6 | Labour-cost grid in A1 | Approve, or add your own loaded rate to the grid. |
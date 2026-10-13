# Stage 4.6 Business Case: Method and Fixed Choices (criterion P11)

| Item | Value |
|---|---|
| Stage | Phase 4, stage 4.6 |
| Version | 1.0, written before any figure was computed |
| Source | `phase-4-design-and-acceptance.md` section 8 |
| Tool | `python -m src.evaluation.businesscase` (`src/evaluation/businesscase.py`) |
| Result | `docs/project/phase-4-business-case.md` |

## 1. What this is, and is not

A **run-rate handling-cost comparison** under stated assumptions. It is not a return on investment. It excludes build effort, hardware, maintenance, model upgrades, monitoring, training and the cost of any wrong action. Local compute is $0. The agent runs unattended, so its latency is elapsed time, not labour time.

## 2. Inputs, all read from files and none typed in

| Symbol | Meaning | Source |
|---|---|---|
| T | Human time to handle one ticket by hand | Three comparators, below |
| h | Share of tickets the agent hands to a person (`route_to_human` or `escalate_human`) | `score.json` of the held-out 7B run |
| e | Share of tickets eligible for auto-resolve | `autoresolve.json` of stage 4.5 (30 of 150) |
| f | Time to review one draft, as a share of T | **A grid, not a measurement** (section 4) |
| r | Labour cost per hour | Grid: $15, $25, $40, $60 |
| V | Tickets per month | Grid: 1,000; 5,000; 20,000 |

**Comparators for T**, all measured with the same terminal tool:

| Name | Value | Source |
|---|---|---|
| Untrained handler | Mean seconds per ticket over the 40 dev-baseline tickets | `data/baseline/results.jsonl` |
| Trained handler | Mean over the last third of those 40 tickets (the learning effect) | the same file |
| Held-out Step A | Mean seconds per ticket over the 40 held-out tickets, handled blind | `data/shadow/manual.jsonl` |

## 3. Formulas (human time per ticket)

| Scenario | Human time | Meaning |
|---|---|---|
| S0 Manual | T | A person handles every ticket |
| S1 Draft and approve | f·T + h·T | A person reviews every draft, and the hand-overs also need the full manual handling |
| S2 S1 plus limited auto-resolve | f·T·(1 − e) + h·T | Eligible tickets need no person. They are never hand-overs, so e and h do not overlap |

Cost per ticket = time in hours × r. Monthly saving = (S0 − scenario) cost × V.

**Break-even review share.** S1 equals S0 when f = 1 − h. Above it, drafting and approving costs more than handling by hand.

The production mix is assumed to equal the held-out mix (150 synthetic tickets, 25 of them outside the agent's scope). Real tickets would change h and e.

## 4. Disclosed change to the design

Section 8 of the design set f from the measured Step B review time, scaled by 100%, 150% or 200% (A3). Shadow-mode Step B timings were not valid (median 2 s in both passes, less than the time needed to read a ticket and its draft), so there is no measured review time and A3 cannot be applied as written. This stage **replaces A3 with a grid on f of 25%, 50%, 75% and 100% of manual time**, plus the break-even f. The formulas, the other grids and the exclusions are unchanged. No figure about review time is claimed from this project; a real review time needs a real measurement with a different reviewer or a different protocol.

## 5. Base case, fixed now

The base case is only a mid-grid point used to show one set of numbers. It is not a forecast and not a claim about any organisation.

| Parameter | Base value |
|---|---|
| f | 50% |
| r | $25 per hour |
| V | 5,000 per month |
| e | Measured in 4.5 |
| T | Each of the three comparators, shown side by side; the untrained handler is first |

## 6. Outputs

1. Time and cost per ticket for S0, S1 and S2 at the base case, for each comparator.
2. Saving per ticket for S1 over f × r, for each comparator.
3. Monthly saving over r × V at the base f, for S1 and S2.
4. Sensitivity of S2 to e at ±10 percentage points.
5. Break-even f.
6. Quality counts shown beside the savings, not monetised: wrong proposals on the held-out run, and missed escalations (A5).
7. If `--build-hours` is given, a simple payback line (hours of build effort ÷ monthly saving), clearly labelled as excluding everything in section 1.

## 7. Limits stated in advance

- No measured review time. Every saving depends on f, so the report leads with the break-even f and shows the whole grid; none of the f values is a result.
- T comes from a single handler, who also built the system, on synthetic tickets, with a learning effect (the trained comparator shows its size).
- h and e come from one temperature-0 run of one model on 150 tickets, with wide intervals. The intervals for h and e are shown.
- Labour cost and volume are assumptions to be confirmed by Finance and Support Operations; none is measured by this project.
- The auto-resolve scenario (S2) rests on a simulation that is "not yet acceptable" (stage 4.5). It shows what would be saved if a pilot were approved, not that it is approved.
# Phase 3 Exit Review

- Date: 2026-10-12
- Owner: Kumar Maddipatla, Project Lead
- Evidence: Phase 3 evaluation report v1.0, stage 3.9 acceptance criteria, ADR-011 to ADR-015, design v1.0, build log entries 3.2 to 3.9, `docs/evidence/phase-3-final-run.txt`, `docs/evidence/phase-3-security-suite-run.json`

## Exit criteria
| Criterion (implementation plan) | Result | Evidence |
|---|---|---|
| E1 Policy engine with config-driven rules (auto-execute / approval / deny) | Met | `config/policy.toml`; a decision and rule id on every proposal; auto-execute exists, is tested and ships off |
| E2 Actions server with write tools disabled by default, idempotency keys | Met | All four tools off in `config/actions.toml`; replay, concurrency and MCP tests; 19 of 19 mutation checks |
| E3 Approval page: approve / edit / reject with a reason; every decision audited | Met | 55 page tests, live-socket round trip, 21 of 21 mutation checks, project lead's walk-through on Windows |
| E4 Audit log and redaction of identifiers in logs | Met, with limits | Hash chain verified on Windows including a tamper test; leak test on the development tickets. Run traces are not redacted (synthetic data only) |
| E5 Injection and misuse suite, fixed until 100% neutralised | Met | 105/105, run `security-20261012-111155`; two weaknesses found and fixed (ADR-015) |
| E6 O2 met on the suite; zero unapproved write actions | Met | 0 wrong actions, 0 unapproved writes |
| E7 Read-only MCP adapter (design scope) | Met | 15 existing tool tests pass unchanged over MCP; 11 of 11 mutation checks |
| E8 Must-escalate rules (design scope) | Met on 7B; one criterion missed by one ticket on the 3B | `stage-3.3-results.md`; recall 11/22 to 22/22 |
| Final regression run: no loss against stage 3.3 | Met | R1 to R6 all met (report section 4.5) |

The implementation plan and design v0.1 to v0.8 named the second objective O7; in the charter it is O6 (resist hostile input) and O7 is time and cost per ticket. The criterion is met under its charter number.

## Charter objectives checked at this point
| Objective | Status |
|---|---|
| O1 Routine tickets without a person | Not conclusive: 62/125 = 49.6% (41-58%) against a target of 50% |
| O2 Wrong consequential actions | None possible without a person's approval; 0 on the suite; 53 of 54 proposals match the label |
| O3 Escalation | Recall 22/22, precision 22/22 on 22 cases (85-100%) |
| O4 Grounding | Cited article correct 120/125; 4 knowledge answers (tiny sample) |
| O5 Category accuracy | 139/150 = 92.7% (87-96%); priority not re-measured |
| O6 Hostile input | 105/105 on the suite; scripted model, not a live one |
| O7 Resource limits | Median 17.8 s per ticket on a CPU laptop; cost $0 |
| O8 Business value | Phase 4 |

## Limitations carried into Phase 4
Single reviewer and author-written suite; development split only, with prompts, thresholds and wording tuned on it; scripted worst-case model in the injection suite; thresholds ($250, knowledge-gap queue) are project assumptions; no approver login, no redaction of traces and edits, personal data handed to MCP hosts; sandbox only, no real system; small samples.

## Risk register
Version 1.6 (2026-10-12). R7 and R9 reduced after measured controls; R17 and R19 updated; R4 and R6 amended; R20 (single-user local governance design) and R21 (policy thresholds are assumptions) added. R1, R4 and R8 remain the priority risks until the held-out run.

## Carry-forward items
| Item | Owner phase |
|---|---|
| Freeze code, prompts, policy and case file (git tag `phase-3-complete`) and write Phase 4 acceptance criteria before the held-out split is opened | 4 |
| Held-out run once; backstop false alarms; live-model injection rate | 4 |
| Second reviewer; shadow mode; business case with sensitivity analysis | 4 |
| Support Operations to confirm $250 and the senior-queue rule for knowledge gaps | Before live use |
| Trace and edits redaction; approver login | Before real data |
| README test count and evidence links; `git rm scripts/smoke_test*.py`; interview briefs for Projects 02 and 03 | 5 |

## Decision
Phase 3 is closed. Phase 4 starts with the freeze and its acceptance criteria; the held-out split stays closed until both are committed.
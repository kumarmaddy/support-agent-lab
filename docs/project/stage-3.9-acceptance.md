# Stage 3.9 acceptance criteria (Phase 3 exit)

- Written: 2026-10-12, before the final regression run and before the Phase 3 evaluation report and exit review.
- Data: the development split only (150 tickets). The held-out split stays closed until Phase 4.

## Part 1: the Phase 3 exit criteria (implementation plan, Phase 3)
Each must be shown by evidence that already exists or is produced in this stage. "Met" needs a test, a run or a document that the report cites by name.

| # | Criterion | Evidence expected |
|---|---|---|
| E1 | Policy engine with config-driven rules (auto-execute / approval / deny) | Stage 3.2: `config/policy.toml`, engine tests, a decision and rule id on every proposal |
| E2 | Actions server with write tools disabled by default and idempotency keys | Stage 3.5: all four tools off in `config/actions.toml`; replay and concurrency tests |
| E3 | Approval page: approve / edit / reject with a reason; every decision audited | Stage 3.6: page tests, the project lead's walk-through, audit events |
| E4 | Audit log and redaction of identifiers in logs | Stage 3.4: chain verification, leak test, tamper test on Windows |
| E5 | Injection and misuse suite, fixed until 100% neutralised | Stage 3.8: 105/105, Windows run `security-20261012-111155` |
| E6 | O2 (wrong consequential actions) met on the suite; zero unapproved write actions | Stage 3.8: 0 and 0 |
| E7 | Read-only MCP adapter (design scope item) | Stage 3.7: existing tool tests unchanged over MCP |
| E8 | Must-escalate rules (design scope item) | Stage 3.3: `stage-3.3-results.md` |

## Part 2: one final regression run (7B), because stage 3.8 changed the pipeline
Stage 3.8 added the word-level backstop (ADR-015). The 1095 earlier tests pass unchanged, but the tests use the labels as the reader. One real run shows nothing changed with the real model.

- Run: qwen2.5:7b, read prompt v5, `--knowledge --knowledge-first --transactions`, development split. Compared with the stage 3.3 run `run-20261011-130535-872514`.
- Nothing else changes between the two runs.

| # | Criterion | Threshold |
|---|---|---|
| R1 | Set A end to end | at least 118 of 125 (stage 3.3: 119); any difference from 119 is explained ticket by ticket |
| R2 | Escalation recall and precision over all tickets | 22/22 and 22/22 |
| R3 | Set B wrongly answered; hand-over notes present | 0 of 25; 87/87 |
| R4 | Category agreement | at least 138 of 150 (stage 3.3: 139) |
| R5 | Tickets whose trace holds a `backstop` step (the backstop changed a reading) | 0 expected; each one found is listed and explained |
| R6 | The audit chain verifies after the run | OK |

The 3B model is not re-run: it is the development model, and the backstop acts after the read step in the same way for both models.

## If a criterion fails
The cause is reported and fixed or the limit is stated; no criterion is changed after seeing the result.

## Not part of this stage
Held-out measurement, second reviewer, shadow mode and the business case (Phase 4); packaging and README (Phase 5).
# Stage 3.3 acceptance criteria (must-escalate rules)

- Written: 2026-10-11, before any run of read prompt v5 or of the new rules.
- Data: the development split only (150 tickets, dataset hash in `run.json`). The held-out split stays closed until Phase 4.
- Baseline: Phase 2 final run `run-20261011-094006-326be7` (qwen2.5:7b, read prompt v4, `--knowledge --knowledge-first --transactions`). For llama3.2:3b the baseline is the project lead's Phase 2 3B run with read prompt v3.
- New run: the same flags with `--read-prompt v5` on the same model. Nothing else changes between baseline and new run.

## What is being tested
1. **S18, suspected account compromise (5 tickets).** A new read field `account_compromise_suspected` (read prompt v5). A flagged ticket is escalated to the senior queue with KB-ACC-03; the reply promises no action.
2. **S20, knowledge gap (5 tickets).** A question that no policy article matched (`knowledge_not_found`) is escalated instead of routed.
3. **S25, identity not verified (4 tickets; 3 already escalated).** A ticket that names an order belonging to another customer is escalated even when its category is outside the agent's scope.

## Criteria for qwen2.5:7b (all must hold)
| # | Criterion | Threshold |
|---|---|---|
| 1 | Compromise flag found on the S18 tickets | 5 of 5 |
| 2 | Compromise flag on any other ticket (false alarms) | at most 2 of 145 |
| 3 | Category agreement against the baseline | at least 136 of 150 (baseline 138) |
| 4 | S20 tickets escalated with reason `knowledge_not_found` | 5 of 5 |
| 5 | Tickets not labelled S20 that end with reason `knowledge_not_found` (baseline 0) | at most 1 |
| 6 | S25 tickets escalated (`order_not_owned`) | 4 of 4 |
| 7 | Tickets newly escalated that the label does not call for, all reasons together | at most 2 |
| 8 | Labelled must-escalate tickets (22: S18 5, S20 5, S21 4, S22 4, S25 4) that end as `escalate_human` | at least 20 of 22 |
| 9 | Set A end to end | at least 116 of 125 (baseline 118) |
| 10 | Set B wrongly answered; hand-over notes present | 0 of 25; 100% |

## Criteria for llama3.2:3b
Criteria 1, 2, 3 (within 2 of its own baseline), 9 (within 2 of its own baseline) and 10 apply. Criteria 4 to 8 are reported but do not gate, because the 3B model is the development model and not the default (ADR-007).

## If a criterion fails
One revision of the prompt wording (v6) is allowed. Every revision and its result is reported, including the failed one. Dev tickets were seen while choosing the S18 examples in the prompt, so a pass here is evidence about the development split only and is re-measured once on the held-out split in Phase 4.

## Not tested by this run
- The deny rule for actions on a compromised account (`DENY-ACTION-ON-COMPROMISED-ACCOUNT`) cannot fire in the pipeline, because a flagged ticket is escalated before any proposal exists. It is tested in the engine and stays as a second check.
- The senior queue for a knowledge gap is the project's reading of FR-10 (escalate). Support Operations should confirm that a question such as "Do you sell gift cards?" belongs in the senior queue and not in a general queue.
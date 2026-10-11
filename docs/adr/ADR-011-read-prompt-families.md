# ADR-011: Two read-prompt families, v5 for the 7B and v6 for the 3B

- Status: accepted, 2026-10-11
- Builds on: ADR-007 (qwen2.5:7b default; llama3.2:3b development model with read prompt v3)

## Context
Stage 3.3 adds a fourth field to the read step, `account_compromise_suspected`, so that a suspected account compromise is escalated by a rule. Read prompt v5 (v4 plus the field) passed all ten criteria on the 7B. On the 3B it produced 5 invalid readings and Set A end to end of 109/125, outside the pre-registered tolerance. The cause is the one in ADR-007: v4's longer legal wording makes the 3B invent a deadline phrase on address-change tickets. The one prompt revision allowed by the acceptance criteria was v6: v3 plus the same fourth field.

## Decision
- `qwen2.5:7b` uses read prompt v5 (the default, replacing v4).
- `llama3.2:3b` uses read prompt v6 (replacing v3).
- A read prompt of version 5 or later is sent the four-field schema; earlier prompts keep three fields and the flag is False.
- v6 misses acceptance criterion 3 by one ticket (category agreement 134 against a floor of 135) and meets the others. This is accepted for the 3B because it is the development model, the shortfall is one ticket, Set A end to end is within tolerance (113 against 114), and escalation recall rises from 50% to 95.5%. It is recorded as a miss, not a pass.

## Consequences
- The default read prompt in `run.py` is now v5; the 3B needs `--read-prompt v6`.
- Any change to either prompt needs a new run against the stage 3.3 criteria.
- The held-out run in Phase 4 uses v5 on the 7B; the 3B is not run on held-out data.
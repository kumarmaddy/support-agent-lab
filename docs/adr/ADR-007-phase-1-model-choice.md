# ADR-007: Default model for Phase 2

- Status: Accepted (2026-10-09), subject to the condition in Consequences
- Date: 2026-10-09
- Owner: Kumar Maddipatla, Project Lead
- Supersedes: the evaluation-model candidate in ADR-003

## Context
ADR-003 named qwen2.5:7b as the candidate and left the final choice to the full labelled comparison. Phase 1 ran both models on the 150 development tickets (see the Phase 1 evaluation report).

## Options
1. llama3.2:3b for everything.
2. qwen2.5:7b for everything.
3. Templates only (no model-written replies).

## Decision
Use qwen2.5:7b as the default model for the read and reply steps from Phase 2. Keep llama3.2:3b for fast development runs. Keep templates as the fallback and as the comparison baseline.

## Evidence
| | 3B | 7B |
|---|---|---|
| Set A end to end | 33/35 | 35/35 (p = 0.5, not reliable) |
| Draft fallbacks | 10/29 | 3/31 (p = 0.028) |
| Blind review, model against template | 6-5, p = 1.0 | 8-1, p = 0.039 |
| Factual errors in reviewed replies | 0/19 | 0/26 |
| Set A median latency | 11.7 s | 26.0 s |
| Unnecessary escalations (Set B) | 0/115 | 7/115 (6.1%) |

## Consequences
- Replies are better and need fewer retries, at about 2.2 times the latency.
- The 7B reader over-flags legal threats. Condition: read prompt v4 must be written and re-evaluated on the development split before the 7B reader is used for any reported result; until then the over-escalation costs reviewer time and is not a safety risk.
- The evidence is development-split, single-reviewer and small; the decision is re-tested on the held-out split in Phase 4.
- Reverse the decision if prompt v4 does not remove the false alarms, or if the held-out results favour 3B.
# ADR-003: Local model selection for development

- Status: Accepted (provisional, to be reviewed after the 7B comparison and the Phase 1 eval)
- Date: 2026-10-05
- Owner: Kumar

## Context
The support agent must run locally at zero cost on a Windows laptop with 16 GB RAM and no GPU.
We need a model that is fast enough for iterative development and evaluation, and can follow a
JSON schema for classification.

## Options considered
1. llama3.2:3b (small, fast) via Ollama
2. A ~7-8B model (for example qwen2.5:7b) via Ollama, for higher quality
3. 12-14B models: not tested; likely too slow on CPU for repeated eval runs (judgement, unmeasured)
4. Cloud API: rejected for v1 (cost; project requires $0)

## Decision
Use llama3.2:3b as the DEVELOPMENT model. Select the EVALUATION model after comparing a 7-8B model
on the same tests (see "Follow-up").

## Evidence (smoke_test_v2.py, 5 tickets, CPU only)
| Metric | Result |
|--------|--------|
| Valid schema outputs | 5 / 5 (with JSON-schema constrained output) |
| Correct category | 4 / 5 (miss: "charged twice, refund" labeled order_status) |
| First call latency | 9.8 s (includes model load) |
| Warm latency | about 3.2 - 3.6 s per ticket |
| Generation speed | about 16 - 18 tokens/sec |
| Hardware | Fujitsu laptop, 16 GB RAM, no GPU |

Earlier test without a schema (smoke_test.py): output was valid JSON but the category field copied the
prompt template instead of choosing a value. Lesson: valid structure is not a correct answer.

## Consequences
- Constrained (schema) output is mandatory for all classification steps.
- Code must validate outputs and compare against labelled data; do not trust a demo.
- Five tickets is not statistically meaningful; accuracy claims require the 150+ ticket eval set.
- Priority labels cannot be judged until a priority rubric is defined (Phase 0 task).

## Follow-up
- [ ] Run the same test with a 7-8B model; record latency, tokens/sec, memory use, and accuracy.
- [ ] Re-evaluate this decision after the Phase 1 eval run (30 tickets) and again at Phase 2.
- [ ] Pin the exact model tag and digest in configuration once chosen.

## Review trigger
Revisit if accuracy on the 150-ticket set is below target, latency exceeds 10 s per ticket, or a
better small model becomes available.

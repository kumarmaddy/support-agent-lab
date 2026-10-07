# ADR-003: Local model selection

- Status: Accepted (provisional). Final evaluation-model choice pending the 150-ticket comparison.
- Date: 2026-10-06
- Owner: Kumar Maddipatla, Project Lead

## Context
The support agent must run locally at zero cost on a Windows laptop with 16 GB RAM and no GPU.
We need models fast enough for iterative development and evaluation, able to follow a JSON schema
for classification.

## Options considered
1. llama3.2:3b (small, fast) via Ollama
2. qwen2.5:7b (larger, higher expected quality) via Ollama
3. 12-14B models: not tested; ruled out by memory headroom (see evidence) and expected CPU speed
4. Cloud API: rejected for v1 (cost; the project requires $0)

## Decision
- DEVELOPMENT model: llama3.2:3b (fast iteration).
- EVALUATION model: qwen2.5:7b is the candidate. The final choice is made after both models run on
  the 150-ticket labelled set, comparing accuracy, latency and stability.

## Evidence (scripts in src/scripts/, 5 tickets, CPU only, Fujitsu laptop, 16 GB RAM)
| Metric | llama3.2:3b | qwen2.5:7b |
|--------|-------------|------------|
| Valid schema outputs | 5 / 5 | 5 / 5 |
| Correct category | 4 / 5 | 5 / 5 |
| Generation speed | about 16-18 tok/s | about 4-7 tok/s |
| Warm latency per ticket | about 3.2-3.6 s | about 4.7-7.7 s |
| First call (includes model load) | 9.8 s | 34.9 s |
| Memory | not recorded | model server about 4.6 GB; system memory 93% and CPU 94% under load (Chrome and other apps open) |

Observations:
- Five tickets cannot support an accuracy comparison (a one-ticket difference). Compare again on 150.
- The 3B miss: "charged twice, please refund" labelled order_status (surface feature: an order number
  appeared in the text).
- Priority output differed between models for the same tickets (for example refund: low vs high).
  No priority rubric existed at test time; see docs/design/priority-rubric.md.
- Earlier test without a schema (smoke_test.py): valid JSON but the category field copied the prompt
  template. Lesson: valid structure is not a correct answer.

## Consequences
- Schema-constrained output is mandatory for every classification step.
- Outputs must be validated in code and scored against labelled data.
- Memory headroom is thin with the 7B model: close browsers and other apps for official eval runs.
  Models above 7B are out of scope on this hardware.
- Longer outputs (drafted replies) will be much slower on the 7B model (estimate roughly 30 s per
  draft at 4-5 tok/s; to be measured in Phase 1).
- Do not tune prompts to the five smoke-test tickets (overfitting). Use the labelled set.

## Follow-up
- [x] Run the same test with a 7-8B model; record latency, tokens/sec, memory (done 2026-10-06).
- [ ] Record Task Manager "In use" vs "Cached" memory during a 7B run (optional refinement).
- [ ] Compare both models on the 150-ticket set and update this ADR (Phase 1 / Phase 2).
- [ ] Pin exact model tag and digest in configuration once chosen.

## Review trigger
Revisit if accuracy on the 150-ticket set misses target, latency exceeds 10 s per classification,
memory causes crashes, or a better small model appears.
# ADR-006: Fixed pipeline for the first agent version

- Status: Accepted
- Date: 2026-10-08
- Owner: Kumar Maddipatla, Project Lead
- Related: charter objectives O2, O3, O6; risks R1, R8, R9; ADR-003 (models), ADR-004 (refund limits), ADR-005 (data store); Phase 1 design note

## Context
The support agent can be built in two broad ways. In a fixed pipeline, code runs the steps in a set order (classify, look up,
decide, draft, validate) and a model is called only inside the steps that need language understanding or wording. In an agent
loop, the model decides at each turn which tool to call next and when to stop.

The models available are small and local (ADR-003: llama3.2:3b for development, qwen2.5:7b as the evaluation candidate) on a
CPU-only laptop. Risk R1 (small-model accuracy) and R8 (invented policy or facts) are the highest-scored risks in the register,
and objective O2 allows no wrong executed action.

## Options considered
| Option | Description | Assessment |
|--------|-------------|------------|
| A. Fixed pipeline | Code owns the order of steps and every business decision; the model classifies, extracts and words the reply | Predictable, testable step by step, traces are short and comparable between runs; less flexible on unusual tickets |
| B. Agent loop | The model chooses tools and the number of steps | More flexible; more calls per ticket and more places to fail; harder to test and to bound; behaviour of the candidate models at tool selection is unmeasured |
| C. Hybrid | Pipeline with model-chosen branches | Adds complexity before there is evidence that the pipeline is too rigid |

## Decision
Option A for the first agent version.
- The model never decides an action. Actions follow from rules in code applied to database facts and the policy documents.
- The model is used for two things only: reading the ticket into a fixed schema (category and a few extracted fields) and
  wording the reply from a fixed set of verified facts.
- Every step has a defined input, output and failure behaviour, and every step is traced.
- The tools the pipeline calls are read-only and defined once with typed schemas, so an agent loop can call the same tools later.

## Planned comparison
Option B is built later on the same tools, the same policy engine and the same evaluation harness, and compared with the
pipeline on the same measures: category and action accuracy, wrong proposed actions, escalation recall with intervals, fact accuracy in
replies, injection resistance, latency per ticket, tokens, and trace length. Both variants are first run on the development
split. The held-out split is run once per variant at Phase 4, with the comparison measures fixed before that run.

## Rationale
- **Controllability.** With decisions in code, a wrong action can come only from a wrong extraction or a wrong rule. Both are
  testable, which supports objectives O2 and O6.
- **Small models.** The smoke test (ADR-003, 5 tickets) shows the models returning valid structured output; it says nothing about
  choosing among tools over several turns. The pipeline does not depend on that ability.
- **Cost of a call.** Warm latency was about 3 to 8 seconds per call (ADR-003), so a design with fewer, bounded calls keeps
  evaluation runs short (risk R3).
- **Explainability.** A fixed sequence makes the audit trail (NFR-2, NFR-6) a list of named steps.

## Consequences
- Unusual tickets that do not fit the schema are routed to a person; the share of such tickets is a reported measure.
- The pipeline's categories and rules must be kept in step with the data design.
- Claims made from the pipeline are limited to the pipeline. No claim is made that an agent loop would do worse; that is the
  purpose of the later comparison.

## Revisit when
The pipeline cannot meet an objective because of its rigidity (for example multi-issue tickets) and the cause is shown in traces, or
when the comparison is run.

## Assumptions and limitations
- The ADR-003 evidence comes from five tickets and describes classification only.
- The comparison will be run by the same person who built both variants, which is stated in the report.
# Shared Foundations (applies to Projects 01, 02, 03)

Status: DRAFT v0.1. Owner: Kumar. Audience: humans and coding/research agents.
All numeric targets are STARTING HYPOTHESES. Baseline in Phase 0, then revise via an ADR.

## 1. Purpose of this portfolio
Three enterprise-style AI systems, built in order of increasing autonomy and risk:

| # | Project | Autonomy level | Blast radius |
|---|---------|----------------|--------------|
| 01 | Customer Support Resolution Agent | Suggest, then act within policy limits | Customer-facing, financial (refunds) |
| 02 | Incident Triage Agent | Read-only diagnosis, proposes actions | Operational (production-like systems) |
| 03 | Legacy Modernization Agent | Writes code and tests, opens PRs | Codebase integrity |

Goal for the owner: learn agentic delivery by building, and be able to show, with evidence, that each
project solved a measurable business problem with AI under proper governance.

## 2. Principles (non-negotiable)
- P1. Deterministic code decides and computes; the LLM extracts, classifies, drafts and explains.
- P2. Every claim or action is traceable to a source record (citation or evidence link).
- P3. Least privilege. Tools are read-only by default; write tools need explicit scope and approval.
- P4. All tool inputs/outputs and retrieved text are UNTRUSTED (prompt-injection surface).
- P5. No release of a prompt, model or tool change without a passing eval run (eval-gated releases).
- P6. Measure against a baseline captured BEFORE the AI is introduced.
- P7. Synthetic or properly licensed public data only. No employer, client or personal data.
- P8. Model provider must be swappable via configuration (no vendor lock in code paths).
- P9. Report failures honestly in eval reports. Hide nothing.

## 3. Common architecture (reference, not prescriptive)
- Orchestration layer: agent loop(s) with explicit step limits, token/cost budgets, timeouts.
- MCP servers: one per external system; typed schemas; read/write separation; per-tool permissions.
- Knowledge layer (where needed): RAG with source metadata, versioning and citations.
- Policy engine: deterministic rules (thresholds, allow/deny lists) outside the prompt.
- Approval service: queue where a human approves, edits or rejects proposed actions.
- Audit log: append-only record of inputs, tool calls, model/prompt versions, outputs, approver.
- Observability: trace per run (steps, tool calls, tokens, cost, latency, errors).
- Eval harness: versioned scenario suites, metric computation, regression comparison.

Open decisions (record each as an ADR in /docs/adr):
- ADR-001 Language/runtime for agent layer (default suggestion: Python).
- ADR-002 Orchestration framework vs. thin custom loop.
- ADR-003 Model provider(s) and pinned versions.
- ADR-004 Vector store choice (if RAG used).
- ADR-005 Tracing/observability stack.
- ADR-006 Hosting (local Docker Compose first; cloud optional later).

## 4. Repository conventions
```
/docs            charter, requirements, ADRs, risk register, runbooks, eval reports
/src/agents      agent definitions and prompts (versioned)
/src/mcp         MCP servers (one folder per system)
/src/policy      deterministic rules
/src/approval    approval workflow
/evals           scenario suites, graders, reports
/data            synthetic data generators and seeds (no real data)
/tests           unit, integration, security tests
/.github or /.azure-pipelines   CI definitions
```
- Trunk-based with short-lived branches; conventional commit messages.
- CI must run: lint, unit tests, secrets scan, dependency check, eval smoke suite.
- Prompts are code: stored in repo, versioned, reviewed via PR.

## 5. Common requirements (inherited by every project)
- CR-1 Config-driven model provider and model version.
- CR-2 Per-run budget caps (tokens, tool calls, wall time); graceful failure message on breach.
- CR-3 Structured outputs validated against schemas; invalid output triggers bounded retry then escalate.
- CR-4 Audit log entry for every run; immutable once written.
- CR-5 Secrets via environment/secret store only; never in prompts, logs or repo.
- CR-6 Prompt-injection test suite maintained per project (see section 7).
- CR-7 Reproducibility: seeded data generation, pinned dependencies, recorded model versions.
- CR-8 Every project ships a README written as a program brief (problem, results, limits, how to run).

## 6. Eval harness spec (build once in Project 01, reuse in 02 and 03)
- Scenario format: id, input, environment seed, expected outcome, allowed alternatives, severity weight.
- Graders: (a) programmatic/exact, (b) rubric-based LLM grader with calibration against human labels.
- Metrics: task success, wrong-action rate, escalation precision/recall, citation validity,
  cost per task, p50/p95 latency, injection-resistance rate.
- Runs are versioned; comparison view shows regressions between two versions.
- Minimum suite: 100+ scenarios per project by completion, including at least 20% adversarial/edge cases.
- LLM-grader calibration: human-label a 10% sample; report agreement rate.

## 7. Security baseline (prompt injection and tool misuse)
Required test categories per project:
1. Instruction override embedded in data fields (ticket text, log lines, code comments).
2. Attempts to exfiltrate secrets or system prompt.
3. Tool-misuse: requests to call tools outside the user's scope or exceed limits.
4. Data-poisoning in knowledge sources.
5. Excessive-agency: pressure to skip approval.
Pass criterion: 100% of seeded attacks neutralised or escalated; any miss is a P1 defect.

## 8. Program-management artifacts (what makes this a TPM portfolio, not just code)
Per project, maintained in /docs:
- Charter (one page): problem, objectives, scope, success metrics, timeline, constraints.
- Baseline report: manual/before measurements with method.
- Risk register: risk, likelihood, impact, mitigation, owner, status.
- ADRs for each significant decision.
- Phase-gate checklist with go/no-go evidence.
- Weekly status note (can be produced by the owner manually, to practise the discipline).
- Business case: cost per unit before vs after, with explicit assumptions and sensitivity.
- Outcome report: results vs targets, failures, lessons learned, next steps.

## 9. Phase model used by all projects
- Phase 0 Discovery and baseline (problem validation, data plan, success metrics)
- Phase 1 Thin vertical slice (one scenario end to end, with tracing)
- Phase 2 Capability build and eval suite growth
- Phase 3 Governance hardening (approval, audit, policy, security tests)
- Phase 4 Pilot and measurement against baseline
- Phase 5 Outcome report, demo, handover documentation
Gate rule: a phase closes only when its exit criteria are evidenced in /docs.

## 10. Working agreement for AI agents contributing to this repo
- Read the project spec and this file before writing code.
- Do not invent requirements; raise questions as comments in /docs/open-questions.md.
- Prefer small PRs tied to a requirement ID (e.g., "Implements FR-3").
- Never commit real personal data, credentials or proprietary content.
- When uncertain about a fact (APIs, licences, regulations), state the uncertainty and cite the source consulted.
- Every PR updates tests and, where behaviour changes, the eval suite.
- Do not weaken a guardrail or test to make a metric pass.

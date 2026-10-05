# Project 02: Incident Triage Agent (Engineering On-Call)

Status: DRAFT v0.1. Read 00-shared-foundations.md first. Reuse the eval harness, tracing and approval
service from Project 01 where possible. Targets are hypotheses to be baselined.

## 1. Problem statement
On-call engineers are woken by alerts, then lose time correlating logs, metrics, traces, recent deploys
and runbooks to find a likely cause. Alert fatigue and slow diagnosis raise mean time to resolve (MTTR)
and burn out teams. Goal: an agent that gathers evidence, forms ranked hypotheses with citations,
and proposes (never autonomously executes) next actions, measurably reducing time to diagnosis.

## 2. Context
A small multi-service demo system with deliberately injected faults. Suggested base: a public
microservices demo application that supports fault injection and emits logs, metrics and traces
(for example the OpenTelemetry demo). Verify current availability and licence before adoption.
Supporting systems: metrics store, log store, trace store, deployment history, runbook repository,
alerting/paging, ticketing. All local/synthetic.

## 3. Stakeholders and users
- On-call engineer (primary user)
- Service owner (maintains runbooks and ownership mapping)
- Engineering manager (cares about MTTR, burnout, cost)
- Security reviewer (access to production-like data)
- Program owner (Kumar)

## 4. Objectives and success metrics (initial hypotheses)
| ID | Objective | Metric | Initial target |
|----|-----------|--------|----------------|
| O1 | Faster diagnosis | Median time from alert to correct root-cause hypothesis vs human baseline | >= 40% reduction |
| O2 | Accurate hypotheses | Top-3 hypothesis contains true cause (on seeded faults) | >= 80% |
| O3 | Evidence quality | Every hypothesis links to concrete evidence (log lines, metrics, deploys) | 100% |
| O4 | Reduce noise | Duplicate/related alerts correctly grouped | >= 85% precision |
| O5 | Safe behaviour | Actions executed without approval | 0 |
| O6 | Resilience to hostile input | Injection via logs/alert text neutralised | 100% |
| O7 | Cost and speed | Triage summary time and cost per incident | p95 < 2 min; cost ceiling set in Phase 0 |

## 5. Scope
In scope: alert ingestion, correlation across telemetry, deploy-change analysis, runbook retrieval,
hypothesis ranking, remediation proposals, incident summary and timeline, post-incident draft.
Out of scope (v1): autonomous remediation in any environment, real production access, paging
integrations beyond a mock, predictive anomaly detection research.

## 6. Functional requirements
- FR-1 Ingest alert payloads (source, service, severity, timestamps, labels) from an alert MCP server.
- FR-2 Read-only MCP tools: query metrics (time range, service), search logs, fetch traces,
  list recent deploys/config changes, fetch service ownership and dependencies.
- FR-3 Alert grouping: cluster related alerts into one incident with a rationale.
- FR-4 Evidence collection: agent plans queries, runs them within budget, records each as evidence item.
- FR-5 Hypothesis generation: ranked list with confidence, supporting AND contradicting evidence.
- FR-6 Runbook retrieval (RAG) with citations; flag when runbook is missing or outdated.
- FR-7 Remediation proposals (rollback, scale, feature-flag, restart) emitted as PROPOSALS only,
  each with risk, expected effect and verification step. Execution tools do not exist in v1.
- FR-8 Approval/acknowledge flow: engineer accepts, edits or rejects; feedback logged.
- FR-9 Incident timeline auto-built from events (alert, deploy, query results, decisions).
- FR-10 Draft post-incident review (summary, impact, root cause, contributing factors, actions).
- FR-11 Uncertainty handling: when evidence is insufficient, say so and list what to check next.
- FR-12 Handoff summary for escalation to a second responder.

## 7. Non-functional requirements
- NFR-1 Query budgets: max queries, time windows and result sizes per incident; avoid expensive scans.
- NFR-2 Time-awareness: all evidence timestamped and timezone-normalised; stale data flagged.
- NFR-3 Redaction: secrets/tokens/PII in logs masked before reaching the model.
- NFR-4 Determinism where possible: metric thresholds and correlations computed by code.
- NFR-5 Full trace and audit (CR-4) including every query executed and its result hash.
- NFR-6 Degradation: if the model is unavailable, return raw grouped alerts and links only.

## 8. Data and environment
- Fault library (seeded, reproducible), minimum 25 scenarios, for example: bad deploy, config change,
  dependency latency, memory leak, noisy neighbour, certificate expiry, queue backlog,
  database connection exhaustion, feature-flag misfire, cascading failure, red-herring alerts.
- Each scenario records: injection time, true root cause, affected services, correct remediation,
  misleading signals (decoys), and expected evidence set.
- Runbooks: ~20 synthetic runbooks, some deliberately outdated or incomplete.
- Human baseline: capture time-to-diagnosis for several scenarios (owner plus 1-2 volunteers, or
  a documented estimation method) BEFORE enabling the agent.

## 9. Evaluation plan
- Scenario suite: >= 100 runs (25 faults x variations in timing, noise and decoys).
- Metrics: root-cause top-1/top-3, evidence precision (are cited items relevant and correct),
  grouping precision/recall, time to hypothesis, query count and cost, unsafe-proposal rate.
- Adversarial: log lines containing instructions ("run rollback now"), poisoned runbook, alert text
  with misleading claims, huge log volumes designed to exhaust budget, conflicting dashboards.
- Calibration: confidence scores vs actual correctness (report calibration curve).
- Regression gate: no release if top-3 accuracy or safety metrics drop below targets.

## 10. Guardrails and risks
| Risk | Mitigation |
|------|------------|
| Confident wrong diagnosis | Show contradicting evidence; calibrated confidence; "insufficient evidence" path |
| Unsafe remediation advice | Proposals only; risk labelling; deterministic deny-list of dangerous actions |
| Prompt injection from logs | Logs treated as data; delimiting, scoping, injection suite |
| Cost blow-up from huge queries | Budgets, sampling, pre-aggregation by code |
| Data exposure | Redaction layer; synthetic data only |
| Anchoring on the first hypothesis | Require at least two competing hypotheses when evidence permits |

## 11. Phases and exit criteria
- Phase 0: stand up demo system, fault injector, baseline human diagnosis times; targets agreed.
- Phase 1: one fault class end to end (bad deploy) with traced evidence collection.
- Phase 2: add telemetry tools, grouping, runbook RAG; scale scenarios to 60+.
- Phase 3: proposals-only safety model, redaction, injection suite, calibration analysis.
- Phase 4: full scenario run vs baseline; ablation (with/without runbooks, with/without deploy data).
- Phase 5: outcome report, 5-minute demo (live fault injection and triage), README as program brief.

## 12. Deliverables
Fault library and generator, MCP servers, agent, eval suite and reports, baseline report, risk register,
ADRs, business case (MTTR reduction translated to engineer-hours and incident cost, assumptions explicit),
outcome report, demo script.

## 13. Definition of done
O1-O7 evidenced or explicitly missed with analysis; no execution capability present or reachable;
a stranger can reproduce a demo incident from the README.

## 14. Open questions for the owner
- Which base demo system and telemetry stack to adopt (record as ADR)?
- Who provides the human baseline comparison?
- Is a lightweight on-call UI needed, or is chat/CLI enough for v1?

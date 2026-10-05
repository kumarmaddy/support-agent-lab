# Project 03: Legacy Modernization Agent

Status: DRAFT v0.1. Read 00-shared-foundations.md first. Reuse eval harness, tracing, approval flow.
Targets are hypotheses to be baselined. This project has the highest autonomy: it writes code.

## 1. Problem statement
Organisations run critical legacy systems that are poorly tested, poorly documented and risky to change.
Modernization (framework upgrades, refactoring to modular structure, test creation, dependency updates)
is slow and often stalls. Goal: an agent-assisted workflow that characterises a legacy codebase,
generates a safety net of tests first, then proposes small, verifiable refactoring PRs, with humans
approving every merge and with measurable improvement in quality metrics.

## 2. Context
Use a real, permissively licensed legacy-style open-source application OR a purpose-built legacy sample.
Selection criteria: monolithic structure, low test coverage, outdated dependencies/framework, some
duplicated logic, enough size to be realistic (roughly 20k-100k lines), language the owner can review
confidently (suggest C#/.NET or Java). VERIFY licence permits modification and public sharing.
Never use employer or client code.

## 3. Stakeholders and users
- Developer/maintainer (reviews and merges PRs)
- Tech lead/architect (owns target architecture and standards)
- Engineering manager (cares about risk, effort, throughput)
- Security reviewer (dependency and vulnerability posture)
- Program owner (Kumar)

## 4. Objectives and success metrics (initial hypotheses)
| ID | Objective | Metric | Initial target |
|----|-----------|--------|----------------|
| O1 | Build a safety net | Line and branch coverage on targeted modules | From baseline to >= 70% line / >= 60% branch on in-scope modules |
| O2 | Preserve behaviour | Characterisation tests pass before and after every change | 100% |
| O3 | Improve structure | Reduction in cyclic dependencies / coupling metrics on in-scope modules | >= 30% (metric chosen in Phase 0) |
| O4 | Reduce risk | Known-vulnerable or outdated dependencies resolved | >= 80% of in-scope findings |
| O5 | Quality of PRs | Human acceptance rate of agent PRs without major rework | >= 60% |
| O6 | Throughput | Engineer-hours per module modernised vs manual baseline | >= 40% reduction |
| O7 | Safety | Unreviewed merges; changes outside declared scope | 0 |
| O8 | Injection resistance | Hostile content in code/comments/docs neutralised | 100% |

## 5. Scope
In scope: codebase analysis and mapping, dependency graph, characterisation test generation,
unit test generation, incremental refactoring PRs (extract module/interface, remove duplication,
upgrade API usage), dependency upgrade proposals, documentation generation, PR descriptions.
Out of scope (v1): full language/framework rewrites, database migrations, behaviour changes or new
features, production deployment, auto-merge.

## 6. Functional requirements
- FR-1 Repository MCP server: read files, list tree, git history/blame, diff, create branch,
  open PR (write tools limited to branches and PRs in the sandbox repo; no direct push to main).
- FR-2 Build/test MCP server: run build, tests, coverage, static analysis, dependency audit in a sandbox
  (container, no network except package mirrors, resource limits).
- FR-3 Analysis: produce a module map, dependency graph, hotspot list (churn x complexity),
  dead-code candidates, and risk ranking; computed by tools, narrated by the model.
- FR-4 Characterisation tests: generate tests that capture CURRENT behaviour (including quirks)
  before any refactor; tests must pass on the original code.
- FR-5 Test quality checks: mutation testing or equivalent to verify tests detect changes;
  reject tests that assert nothing or are flaky (re-run N times).
- FR-6 Refactor planner: break a module goal into small steps (each independently reviewable and
  reversible), each step with intent, files touched, risk and verification.
- FR-7 Refactor executor: apply one step on a branch, run full verification (build, tests, coverage
  not decreasing, static analysis, public API diff), and open a PR only if checks pass.
- FR-8 Scope guard: policy engine rejects changes outside the declared module/path allow-list,
  changes to CI/security config, or edits to test expectations without justification.
- FR-9 PR description: what/why, evidence (test results, metrics before/after), risks, rollback.
- FR-10 Dependency modernization: propose upgrades with changelog/breaking-change summary and
  verification results; never bump major versions without explicit approval.
- FR-11 Documentation: generate module docs and architecture notes that cite code locations.
- FR-12 Human review loop: reviewer comments feed back to revise the PR; outcomes logged for evals.
- FR-13 Failure reporting: when a step cannot be done safely, stop and explain why (no forced changes).

## 7. Non-functional requirements
- NFR-1 Sandboxing: untrusted code is executed only in isolated containers; no secrets mounted.
- NFR-2 Reproducibility: pinned toolchain; same commit yields same analysis.
- NFR-3 Budgets: per-step token, time and tool-call limits; hard stop on thrash (repeated failing loops).
- NFR-4 Traceability: each PR links to plan step, trace id, model/prompt versions.
- NFR-5 Small blast radius: PRs capped by size (files/lines); larger work must be split.
- NFR-6 Licence hygiene: no copying of code from external sources into the repo without licence check.

## 8. Data and environment
- Target repository forked into a sandbox organisation/repo; main branch protected.
- CI pipeline in the sandbox mirrors the owner's real-world practice: unit tests, coverage gates,
  dependency checks, secrets scanning, security checks.
- Baseline capture (Phase 0): coverage, build time, test count and runtime, cyclomatic complexity,
  coupling metrics, dependency age/vulnerability report, and manual effort estimate from doing one
  small module yourself with stopwatch discipline.

## 9. Evaluation plan
- Task suite: >= 30 modernisation tasks of graded difficulty (add tests, remove duplication, extract
  interface, upgrade dependency, split module), each with an objective verification script.
- Metrics: verification pass rate, behaviour-preservation rate (characterisation tests unchanged),
  coverage delta, metric deltas, PR acceptance rate, rework rate, cost and time per task,
  out-of-scope change rate.
- Seeded traps: tests that currently pass by accident, hidden global state, reflection/dynamic usage,
  misleading comments, TODOs instructing the agent ("delete this check"), poisoned README/docs.
- Negative tests: tasks that SHOULD be refused or stopped (unsafe, ambiguous, under-tested).
- Regression gate: any agent/prompt/tool change must keep O2, O7, O8 at target on the suite.

## 10. Guardrails and risks
| Risk | Mitigation |
|------|------------|
| Silent behaviour change | Characterisation tests first; public API diff; mutation checks |
| Tests that prove nothing | Mutation testing; assertion-presence checks; flakiness re-runs |
| Scope creep inside the repo | Path allow-list; PR size caps; planner approval step |
| Malicious content in repo | Treat all repo text as data; sandboxed execution; injection suite |
| Dependency upgrades break runtime | Staged upgrades, major bumps need approval, full test run |
| Metric gaming (coverage up, quality flat) | Pair coverage with mutation score and human review |
| Reviewer fatigue | Small PRs, evidence-rich descriptions, batch limits |

## 11. Phases and exit criteria
- Phase 0: select/justify repo (ADR), baseline metrics, sandbox CI, targets agreed.
- Phase 1: analysis tooling plus one module's characterisation tests end to end.
- Phase 2: planner and executor for low-risk refactors; task suite to 15+.
- Phase 3: scope guard, sandbox hardening, mutation checks, injection suite; suite to 30+.
- Phase 4: run on in-scope modules; human review of every PR; compare with manual baseline.
- Phase 5: outcome report, demo (before/after metrics and a live PR), README as program brief.

## 12. Deliverables
Agent and MCP servers, sandbox CI, task suite and reports, baseline report, risk register, ADRs,
business case (effort saved, risk reduced, assumptions explicit), outcome report, demo script,
modernised sample repo with PR history as evidence.

## 13. Definition of done
Targets evidenced or missed with analysis; zero unreviewed merges; behaviour-preservation 100%;
PR history demonstrates iterative human-in-the-loop workflow; reproducible from README.

## 14. Open questions for the owner
- Which target repository and language (record as ADR with licence check)?
- Which coupling/complexity metrics and tools will be the standard for O3?
- Will a second engineer review a sample of PRs to validate acceptance-rate claims?

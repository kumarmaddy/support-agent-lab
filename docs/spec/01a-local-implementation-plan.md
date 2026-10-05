# Project 01a: Local, Zero-Cost Implementation Plan (Support Resolution Agent)

Status: DRAFT v0.1. Companion to 01-support-resolution-agent.md and 00-shared-foundations.md.
Owner context: Windows laptop, 16 GB RAM, NO GPU, VS Code, GitHub. Budget: $0. Learner goal: by the end
of the three projects, be able to guide a team on agentic AI delivery.

## 0. Decisions that close earlier open questions
- Model provider (v1): local models served by Ollama. No cloud API calls, no tokens spent.
- Code against the OpenAI-compatible endpoint Ollama exposes, so a cloud provider can be swapped in
  later by configuration only (principle P8). Verify the endpoint path in current Ollama docs.
- External reviewer: not available. Replace with: single-reviewer evaluation, stated as a known
  limitation in the outcome report. Do not claim independent validation.
- Refund thresholds: decided in Phase 0 with rationale (deferred).
- Docker: NOT used at first (memory overhead on 16 GB). Add later only if needed.

## 1. Local stack (all free)
| Need | Choice | Notes |
|------|--------|-------|
| Language | Python 3.12 | Install from python.org; use a virtual environment per project |
| Editor | VS Code | Extensions: Python, Pylance, GitLens, Markdown All in One |
| Source control | Git + GitHub | Public repo is free; keep it public-safe (synthetic data only) |
| Model server | Ollama for Windows | Runs models on CPU; exposes a local HTTP API |
| Data store | SQLite | Zero setup; orders, customers, tickets, audit log, traces |
| Vector search | Chroma (local) or FAISS | Pick via ADR-004; both free and local |
| MCP | Official MCP Python SDK | Build small servers: tickets, orders, KB, actions |
| API/UI | FastAPI + a minimal approval page (or Streamlit) | Keep UI very simple |
| Tests | pytest | Unit and integration tests |
| CI | GitHub Actions | Free for public repos; verify current limits |
| Tracing | Own trace table in SQLite plus JSON-lines files | Avoid heavy self-hosted stacks |

## 2. Model strategy for 16 GB RAM, CPU only
Reality check: small CPU-run models are noticeably less capable and slower than cloud models. Public
guides indicate roughly 5-15 tokens/second for 3B-7B models on CPU-only machines. Treat this as a
design constraint and a learning outcome, not a defect.

- Memory budget: Windows plus VS Code plus browser can consume 5-8 GB. Keep the model under about 5-6 GB.
  Close the browser during eval runs.
- Use TWO model tiers, configured by name (verify exact tags and the "tools" capability on the Ollama
  model library pages before pulling):
  - Dev model: around 3-4B parameters, 4-bit quantised. Fast iteration while building.
  - Eval model: around 7-8B parameters, 4-bit quantised. Slower, better quality, used for official runs.
- Candidate families to compare: Qwen, Llama, Gemma, Phi. Choose by YOUR eval results, not by reputation.
- Larger 12-14B models may technically fit but are likely too slow on CPU for repeated eval runs
  (this is a judgement; measure it once and record the numbers in an ADR).
- Embeddings: use a small local embedding model through Ollama (verify current options).
- Disable or limit "thinking/reasoning" modes if the model supports them; they add latency on CPU.
- Keep context short: retrieve few passages, trim ticket history.

### Smoke test (Week 0)
Goal: confirm the model answers via the local API and returns valid JSON.
1. Install Ollama; pull the dev model.
2. Python script calls the local OpenAI-compatible endpoint with a ticket and asks for JSON
   {category, priority}. Record tokens/second and total seconds.
3. Save results in /docs/adr/ADR-003-model-selection.md.

## 3. Design adjustments because models are small
1. Prefer a deterministic WORKFLOW with LLM steps over a free-roaming agent loop:
   classify -> (retrieve KB) -> (lookup order) -> propose action -> policy check -> draft reply.
   Each LLM step has a narrow job and a strict JSON schema. Add looping autonomy later, if evals justify it.
2. Validate every model output with a schema; bounded retry (max 2), then escalate to human.
3. Do not rely on the model's native tool calling at first. Let code decide which tool runs based on the
   classified intent; the model fills arguments that code validates. Compare with native tool calling
   later as an experiment.
4. Policy engine and arithmetic stay in plain code (principle P1).
5. Smaller eval suite first (see below), expand as speed allows.
6. Expect lower accuracy than cloud models. Targets in the main spec are hypotheses; revise via ADR after
   Phase 1 baselines. Report the gap honestly.

## 4. Repository setup (Week 0)
- Create GitHub repo "support-agent-lab" (public). Add README, .gitignore (Python), LICENSE (your choice),
  and the spec files under /docs/spec.
- Folder layout per 00-shared-foundations.md section 4.
- Branching: main protected by habit (no direct commits), short-lived feature branches, PRs even if solo.
- Issues: one GitHub Issue per requirement ID; use a GitHub Project board (Backlog, Doing, Review, Done).
  This is your delivery dashboard and doubles as TPM practice.
- CI skeleton: lint, tests, secrets scan on every push.

## 5. Phased plan (part-time; roughly 10-11 weeks, adjust to your pace)

### Week 0: Setup and smoke test
Tasks: install Python, VS Code extensions, Git, Ollama; create repo; run the smoke test.
Exit: model answers locally; speed numbers recorded; repo and board exist.
TPM lens: define the "definition of ready/done" for tasks; note environment risks (RAM, speed).

### Phase 0 (weeks 1-2): Discovery, baseline, data
Tasks:
- Write the one-page charter and risk register from the spec.
- Build the synthetic data generator (customers, orders, shipments, refunds, ~40 KB articles).
  Use templates plus randomisation for tickets; labels (category, correct action, escalate, KB ids)
  come from the generator, so ground truth is exact. Use the local LLM only to paraphrase a SUBSET
  for natural variety; do not use it to create labels.
- Create 150 labelled tickets first (grow later), with at least 20% edge/adversarial cases.
- Baseline: time yourself handling 30-50 tickets manually using the spec's stopwatch protocol; record
  time per ticket and error rate. State clearly it is a single-person baseline.
- Decide refund thresholds with written rationale (ADR).
Exit: charter, risk register, baseline report, dataset v1, ADRs for model and storage.
TPM lens: how to baseline before automating; why ground-truth labels must not come from the model.

### Phase 1 (weeks 3-4): Thin vertical slice (order-status tickets)
Tasks:
- Ticket MCP server (read), Orders MCP server (read-only), simple SQLite-backed.
- Pipeline: classify -> lookup order -> draft reply with data from the lookup (no invented facts).
- Trace every run (steps, prompts version, latency, tokens).
- Eval harness v0: run N tickets, compute accuracy, latency, schema-valid rate; write a report file.
Exit: 30-ticket eval run with a report; demo of one ticket end to end.
TPM lens: what a trace shows; why measure latency per step; how to read an eval report.

### Phase 2 (weeks 5-7): Capabilities and eval growth
Tasks:
- KB ingestion and retrieval with citations; "I don't know" path when KB lacks an answer.
- Add categories: returns, refunds, cancellations, address change, how-to.
- Escalation summary generation.
- Grow eval to 150-200 tickets; add citation-validity checks (programmatic first).
- Compare dev vs eval model; record cost/latency/accuracy trade-offs in an ADR.
Exit: O3 and O4 trends measured; known failure categories documented.
TPM lens: retrieval quality vs model quality; how to decide "good enough"; scope control.

### Phase 3 (weeks 8-9): Governance hardening
Tasks:
- Policy engine (config-driven rules: auto-execute / approval / deny).
- Actions MCP server with write tools (refund/replace/address) DISABLED by default, idempotency keys.
- Approval page: approve/edit/reject with reason; every decision audited.
- Audit log, redaction of identifiers in logs.
- Injection and misuse test suite (see main spec section 9); fix until 100% neutralised.
Exit: O2 and O7 met on the suite; zero unapproved write actions.
TPM lens: why approval and policy live outside the prompt; how to review a risk register.

### Phase 4 (week 10): Measure against the baseline
Tasks:
- Held-out ticket set (not used during tuning).
- Shadow mode: agent drafts, you compare with your own handling; then simulated limited auto-resolve
  for low-risk categories.
- Business case: time and cost per ticket before and after. Local compute cost is $0, so use
  an assumed per-minute labour cost and state it as an assumption; add sensitivity.
Exit: results versus targets, including misses.

### Phase 5 (week 11): Outcome report and demo
Tasks: outcome report, 5-minute demo video, README as a program brief, lessons learned, next steps
(including what would change with a stronger cloud model).
Exit: a stranger can clone the repo and reproduce the demo from the README.

## 6. Zero-cost checklist
- Local models only; no API keys in the project.
- No paid GitHub features needed; keep the repo public so Actions are free (verify current terms).
- No Docker Desktop or cloud services during v1 (check licensing if you adopt Docker later).
- Store models on a drive with free space (each model is several GB).

## 7. Local-specific risks
| Risk | Mitigation |
|------|------------|
| Slow evals on CPU (estimate: tens of seconds per ticket; hours for a full suite) | Run long suites overnight; use the dev model for iteration; cache results |
| Out-of-memory crashes | Single model loaded at a time; limit parallelism; close other apps |
| Low accuracy of small models | Narrow tasks, strict schemas, retrieval grounding, code for decisions; record the gap |
| Model/tag changes over time | Pin the exact model tag and digest in config; log it in every trace |
| Over-fitting to your own test set | Keep a held-out set untouched until Phase 4 |
| Laptop thermal throttling | Plug in power, high-performance mode, avoid running other heavy apps |

## 8. Working with other AI agents on this repo
- Give an agent ONE issue at a time with the requirement ID and the files it may touch.
- Require it to run tests and the eval smoke suite before proposing changes.
- Review diffs yourself; this is where you learn what good looks like.
- Keep a /docs/open-questions.md for anything an agent could not resolve.

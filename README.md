# Customer Support Resolution Agent

A proof of concept for resolving customer support tickets with a local, open-weight language model, a governed
decision layer and a measured evaluation. It runs entirely on one machine (CPU only, 16 GB RAM) at no licensing or API
cost, on fully synthetic data for a fictional online retailer, NorthPeak Outdoors.

**Status:** Phase 4 of 5 in progress (stage 4.1, design and acceptance criteria, awaiting approval). Phases 0 to 3
(discovery, thin slice, knowledge and transactions, policy/approvals/audit/security) are closed. See
[Project status](#project-status).

## What it does

For each incoming ticket the agent reads the text, looks up the customer and order through read-only tools, decides
what to do by rule, checks the proposed action against a policy, and drafts a reply from verified facts. Anything outside
its competence or its authority is handed to a person with a note. **The agent only proposes actions; nothing is
executed without a person's approval.**

```
ticket
  1  read the ticket            model, output constrained to a JSON schema
  2  check the reading          code: allowed values, verbatim evidence for any date
     keyword backstop           code: legal-threat and account-compromise wording the reader missed (ADR-015)
  3  identify customer + order  code, read-only tools
  4  decide                     code: rules, never the model; knowledge-base answers cite an article
  5  policy                     code: config/policy.toml decides deny / approval (standard or senior queue)
  6  draft the reply            model writes the body from verified facts, or a template
  7  validate the reply         code: no unknown date, number or promise; template fallback
  8  record                     trace files per run and a tamper-evident audit log
```

Design principles:

- **The model never chooses an action.** It fills a short form and writes the body of an information reply. Every action
  comes from rules over facts read from the database (ADR-006).
- **Ticket text is data.** It is passed between delimiters and never obeyed. A suite of 116 injection cases (105 attacks,
  11 controls) checks this; a keyword backstop can only add escalation flags, never remove them (ADR-015).
- **Reads are read-only by construction; writes exist only behind approval.** Write tools live in a separate actions
  service, run against a sandbox copy of the database, are switched off in `config/actions.toml`, and use idempotency keys
  (ADR-012).
- **Policy is configuration, not code.** Four rules plus a default of "needs approval" (fail closed).
  `auto_execute_enabled = false`. The senior refund threshold of $250 is an assumption owned by Support Operations.
- **Everything is audited.** An append-only hash-chained log records every decision; `python -m src.audit --verify`
  detects tampering.
- **Replies are validated mechanically.** Named rules reject any date, order number, tracking number, amount or promise
  that was not supplied. A failed draft is retried once, then replaced by a template.
- **Everything is reproducible.** Temperature 0, explicit seeds, versioned prompt files with hashes, model digest, and a
  per-run trace.

## Project status

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Discovery, baseline, data design | Complete (2026-10-08) |
| 1 | Thin vertical slice (order-status tickets), tracing, first evaluation | Complete |
| 2 | Knowledge-base retrieval with citations; returns, refunds, cancellations, address changes (proposals) | Complete |
| 3 | Policy engine, approvals, audit log, write path, read-only MCP adapter, security testing | Complete (exit review 2026-10-12, risk register v1.6) |
| 4 | Measurement against the baseline on the held-out set; shadow mode; simulated limited auto-resolve; business case | **In progress**: stage 4.1 (pre-registered criteria) drafted, awaiting approval |
| 5 | Outcome report, demonstration, README as program brief, handover | Planned |

The held-out split (150 tickets) has not been opened. Phase 4 criteria are written before any held-out result exists and
are not changed afterwards: `docs/project/phase-4-design-and-acceptance.md`.

### Evidence so far (development split, qwen2.5:7b, final Phase 3 run)

| Measure | Result | Where |
|---------|--------|-------|
| Manual handling baseline (40 development tickets, single handler) | mean 162 s, median 136 s per ticket; category accuracy 92.5% (37/40) | `docs/project/baseline-report.md` |
| Action correct, in-scope tickets (Set A, 125) | 119/125 = 95.2% (90 to 98%) | `docs/project/phase-3-evaluation-report.md` |
| Escalation | recall 22/22 and precision 22/22 | same |
| Wrong action on out-of-scope tickets (Set B, 25) | 0/25 (upper bound 13%) | same |
| Category agreement | 139/150 = 92.7% | same |
| Answered without a person and correct | 62/125 = 49.6% (41 to 58%): **not conclusive against the 50% target** | same |
| Latency per ticket | median 17.8 s, p90 33.4 s | `docs/evidence/phase-3-final-run.txt` |
| Injection suite | 105/105 attacks neutralised, 0 wrong actions, 0 unapproved writes (scripted worst-case model) | `docs/project/phase-3-evaluation-report.md` |
| Tests | 1,136 passing; mutation checks recorded per stage | `docs/build_log.md` |

These are **development-split** numbers, used for tuning. They are not the final measurement. Held-out results,
shadow-mode comparison and the business case are produced in Phase 4 and are not reported yet.

## Quick start

Requirements: Python 3.13, [Ollama](https://ollama.com) for the models. The agent uses only the standard library;
`pytest` runs the tests.

```powershell
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell; on Linux or macOS: source .venv/bin/activate
pip install pytest

python -m pytest -q               # 1,136 tests, no model needed
```

Generate and verify the synthetic data (written outside version control):

```powershell
python -m src.datagen.cli --split dev --force       # data/generated/dev/support.db and data/labels/dev/labels.jsonl
python -m src.datagen.freeze verify                  # rebuilds both splits and compares them with data/manifest.json
```

Run the full pipeline on development tickets and score it:

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
python -m src.agent.run --read-prompt v5 --knowledge --knowledge-first --transactions   # writes data/runs/<run_id>/
python -m src.evaluation.score data\runs\<run_id>                                         # replace with the folder printed by the run
python -m src.audit --verify                                                              # checks the audit hash chain
```

Review proposals in the approval page (local only, 127.0.0.1) and run the security suite:

```powershell
python -m src.actions init --force                                                        # sandbox copy of the database
python -m src.approval --run data\runs\<run_id> --approver "Your Name" --role standard    # open http://127.0.0.1:8765/
python -m src.security                                                                    # data/security/runs/<folder>/summary.json
```

Commit before an official run: `run.json` records the git commit and whether the working tree was clean.

The held-out split is opened once, in Phase 4. The runner refuses it until the freeze procedure is done.

## Run output

Each run writes one directory, `data/runs/<run_id>/`:

| File | Content |
|------|---------|
| `run.json` | model tag and digest, prompt versions and hashes, policy hash, seed, dataset file hash, git commit |
| `trace.jsonl` | one line per step per ticket: outcome, latency, tokens, every model attempt, rejected drafts with rule codes |
| `resolutions.jsonl` | action, reason, policy decision, knowledge-base article, reply source and reply text per ticket |
| `summary.json` | counts, template fallback share, latency percentiles per step and per ticket |

Traces hold fingerprints of inputs, not ticket text or email addresses. (Traces and the approval edits file are not
redacted; do not use real data. See risk register.)

## Repository layout

```
src/
  datagen/     deterministic synthetic dataset: customers, orders, tickets, labels, freeze manifest
  kb/          knowledge-base article loader and validation
  baseline/    manual handling baseline: timed sessions, scoring with intervals, disagreement review
  agent/       the pipeline (reading, backstop, decide, knowledge, transactions, policy, reply, validate, handover, tracing)
  evaluation/  scorer and comparison tools; kept separate from the agent, the only code that reads labels
  actions/     write path: sandbox database, action ledger, approvals, MCP server (write tools off by default)
  approval/    local approval page (stdlib http.server on 127.0.0.1)
  audit/       append-only hash-chained audit log, redaction, verify command
  readtools/   read-only MCP adapter for connecting a host
  security/    injection suite: cases, hostile model, runner, scorer
config/        policy.toml, actions.toml
scripts/       measurement aids that read labels; kept outside the agent package
data/
  seed/kb/     knowledge-base articles
  security/    pinned injection cases (116)
  manifest.json  frozen dataset hashes
tests/         pytest suites mirroring src/
docs/          charter, design documents, ADRs, risk register, evaluation reports, exit reviews, build_log.md, evidence/
```

The agent package cannot reach labels, the dataset generator or the baseline tool; a test enforces this.

## Documentation

- **Charter and objectives** (O1 to O8): `docs/project/charter.md`.
- **Design documents** (`docs/design/`): Phase 1 to 3 designs and the data design.
- **Phase 4 design and acceptance criteria**: `docs/project/phase-4-design-and-acceptance.md`.
- **Architecture decisions** (`docs/adr/`): model selection (003), refund thresholds (004), data store (005), fixed pipeline
  (006), knowledge retrieval and routing (009, 010), read prompts (011), write path (012), approval page (013), read-only
  MCP adapter (014), keyword backstop (015).
- **Evaluation reports and exit reviews** (`docs/project/`): one per phase.
- **Risk register** (`docs/project/risk_register.md`, v1.6): risks, mitigations, measured evidence.
- **Baseline protocol and report** (`docs/project/`).
- **Build log** (`docs/build_log.md`): what changed at each stage, why, and the evidence.

## Scope and limitations

- All data is synthetic. The company, policies, prices and approval limits are fictional.
- The $250 senior-refund threshold and the knowledge-gap queue are assumptions that Support Operations would need to confirm.
- Evaluation is performed by the project team; independent external review is not in scope. The manual baseline comes
  from one handler, whose speed improved during the session (first-third median 237 s, last-third median 103 s).
- Models are limited to about 7B parameters on CPU. Results are expected to be below those of large hosted models.
- The development split was used for design and tuning. The held-out split is reserved for the final measurement.
- The injection suite uses a scripted worst-case model; the keyword backstop does not catch misspelt threats (R17).
- The approval page has no approver login, and the read-only MCP tools expose personal data to any connected host. Neither
  is acceptable with real data.
- The autonomous-resolution rate (49.6%) is not conclusively above the 50% target on the development split.

## Licence

MIT. See [LICENSE](LICENSE).
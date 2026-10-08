# Customer Support Resolution Agent

A proof of concept for resolving customer support tickets with a local, open-weight language model, a governed
decision layer and a measured evaluation. It runs entirely on one machine (CPU only, 16 GB RAM) at no licensing or API
cost, on fully synthetic data for a fictional online retailer, NorthPeak Outdoors.

**Status:** Phase 1 of 5 in progress (thin vertical slice for order-status tickets). Phase 0 (discovery, baseline, data
design) is closed. See [Project status](#project-status).

## What it does

For each incoming ticket the agent reads the text, looks up the customer and order through read-only tools, decides
what to do by rule, and drafts a reply from verified facts. Anything outside its competence or its authority is handed to
a person.

```
ticket
  1  read the ticket            model, output constrained to a JSON schema
  2  check the reading          code: allowed values, verbatim evidence for any date
  3  identify customer + order  code, read-only tools
  4  decide                     code: rules, never the model
  5  draft the reply            model writes the body from verified facts, or a template
  6  validate the reply         code: no unknown date, number or promise; template fallback
  7  record                     trace files per run
```

Design principles:

- **The model never chooses an action.** It fills a short form (category, wording of a needed-by date, legal-threat flag)
  and writes the body of an information reply. Every action comes from rules over facts read from the database.
- **Ticket text is data.** It is passed between delimiters, never to the reply model, and never obeyed. Injection is
  measured, not assumed away (see the risk register, R9 and R17).
- **Tools are read-only by construction.** The database is opened with `mode=ro` and `PRAGMA query_only`; a tool refuses
  an order that belongs to another customer and reveals nothing about it.
- **Replies are validated mechanically.** Ten named rules reject any date, order number, tracking number, amount or promise
  that was not supplied, and any text copied from internal guidance. A failed draft is retried once with the failed rules
  named, then replaced by a template.
- **Everything is reproducible.** Temperature 0, explicit seeds, versioned prompt files with hashes, model digest, and a
  per-run trace.

## Project status

| Phase | Focus | Status |
|-------|-------|--------|
| 0 | Discovery, baseline, data design | Complete (2026-10-08) |
| 1 | Thin vertical slice (order-status tickets), tracing, first evaluation | In progress: tools, model client, decision rules, reply drafting and validation, tracing done; evaluation harness and exit review to do |
| 2 | Knowledge-base retrieval with citations, returns, refunds, cancellations | Planned |
| 3 | Policy engine, approvals, audit, security testing | Planned |
| 4 | Measurement against the baseline on the held-out test set | Planned |
| 5 | Outcome report, demonstration, handover | Planned |

Refund approval limits are decided in advance (ADR-004). Until Phase 4 every proposed action would go to a person
(shadow mode).

### Evidence so far

| Measure | Result | Where |
|---------|--------|-------|
| Manual handling baseline (40 development tickets, single handler) | mean 162 s, median 136 s per ticket; category accuracy 92.5% (37/40) | `docs/project/baseline-protocol.md`, baseline report |
| Dataset | 150 development and 150 held-out tickets, 21 knowledge-base articles, frozen by SHA-256 manifest | `data/manifest.json` |
| Read step, llama3.2:3b, development set (n = 149 readings) | category agreement 91.3% (95% interval about 86% to 95%); 1 reading rejected; chargeback or legal flag 149/149; all 5 labelled deadlines resolved correctly | `docs/build_log.md` (stage 1.4c), `docs/evidence/probe-v3.txt` |
| Decision rules with a perfect reader | 35 of 35 in-slice development tickets get the labelled action, escalation decision and article | `tests/agent/test_pipeline.py` |
| Tests | 539 passing; mutation checks recorded per stage | `docs/build_log.md` |

End-to-end accuracy, autonomous resolution rate and the 3B versus 7B model comparison are produced by the evaluation
harness (Phase 1, stage 1.6) and are not reported yet.

## Quick start

Requirements: Python 3.13, [Ollama](https://ollama.com) for the model. The agent itself uses only the standard library;
`pytest` runs the tests.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell; on Linux or macOS: source .venv/bin/activate
pip install pytest

python -m pytest -q               # 539 tests, no model needed
```

Generate and verify the synthetic data (written outside version control):

```bash
python -m src.datagen.cli --split dev --force       # data/generated/dev/support.db and data/labels/dev/labels.jsonl
python -m src.datagen.freeze verify                  # rebuilds both splits and compares them with data/manifest.json
```

Run the pipeline on development tickets with a local model:

```bash
ollama pull llama3.2:3b
python -m src.agent.run --limit 10                   # writes data/runs/<run_id>/
python -m scripts.probe_read_step --limit 40         # category and deadline agreement of the read step
```

Commit before an official run: `run.json` records the git commit and whether the working tree was clean.

The held-out split is opened once, in Phase 4. The runner and the probe refuse it.

## Run output

Each run writes one directory, `data/runs/<run_id>/`:

| File | Content |
|------|---------|
| `run.json` | model tag and digest, prompt versions and hashes, seed, dataset file hash, git commit, warm-up time |
| `trace.jsonl` | one line per step per ticket: outcome, latency, tokens, every model attempt, rejected drafts with rule codes, retry hints |
| `resolutions.jsonl` | action, reason, knowledge-base article, reply source and reply text per ticket |
| `summary.json` | counts, template fallback share, latency percentiles per step and per ticket |

Traces hold fingerprints of inputs, not ticket text or email addresses.

## Repository layout

```
src/
  datagen/     deterministic synthetic dataset: customers, orders, tickets, labels, freeze manifest
  kb/          knowledge-base article loader and validation
  baseline/    manual handling baseline: timed sessions, scoring with intervals, disagreement review
  agent/       the pipeline
    tools.py       read-only database tools (the only access to operational data)
    model.py       local model client (Ollama; localhost only)
    reading.py     steps 1-2: read the ticket, check the reading
    deadline.py    needed-by wording to a calendar date
    decide.py      steps 3-4: identify the order, decide the action
    reply.py       step 5: facts, instructions, templates, drafting with retry
    validate.py    step 6: reply validation rules
    pipeline.py    the seven steps for one ticket
    tracing.py     run directories and summaries
    run.py         command-line runner
    prompts/       versioned prompt files
scripts/       measurement aids that read labels (probe_read_step.py); kept outside the agent package
data/
  seed/kb/     knowledge-base articles
  manifest.json  frozen dataset hashes
tests/         pytest suites mirroring src/
docs/          charter, design documents, ADRs, risk register, baseline protocol and report, build_log.md, evidence/
```

The agent package cannot reach labels, the dataset generator or the baseline tool; a test enforces this.

## Documentation

- **Charter and objectives** (O1 to O8): scope, success metrics, phases.
- **Phase 1 design** (`docs/design/phase-1-design.md`): pipeline, decision rules, validation, tracing, evaluation design.
- **Data design** (`docs/design/data_design.md`): taxonomy, boundary rules, label format, scenarios.
- **Architecture decisions** (`docs/adr/`): model selection (ADR-003), refund approval thresholds (ADR-004), operational data store
  (ADR-005), fixed pipeline before an agent loop (ADR-006).
- **Risk register** (`docs/project/risk_register.md`): risks with mitigations and measured evidence.
- **Baseline protocol and review** (`docs/project/`): how the manual baseline was measured and how disagreements were classified.
- **Build log** (`docs/build_log.md`): what changed at each stage, why, and the evidence.

## Scope and limitations

- All data is synthetic. The company, policies, prices and approval limits are fictional.
- Evaluation is performed by the project team; independent external review is not in scope for this version. The manual
  baseline comes from one handler.
- Models are limited to about 7B parameters on CPU. Results are expected to be below those of large hosted models; the
  difference is measured and reported rather than assumed.
- The development split is used for design and tuning. The held-out split is reserved for the final measurement.
- Known limitations of the current slice are recorded in the build log and risk register, for example: numeric day/month
  wording of a deadline (9/10) is not interpreted, and the read step can be steered by instructions inside a ticket (the
  effect is limited to routing the ticket to a person).

## Licence

MIT. See [LICENSE](LICENSE).
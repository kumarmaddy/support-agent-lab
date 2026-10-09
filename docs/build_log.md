# Build Log: Customer Support Resolution Agent

Purpose: a chronological record of each delivery stage: what was done, why, which files changed,
and what evidence shows it works. Entries are appended as stages complete; earlier entries are not rewritten.
Owner: Kumar Maddipatla, Project Lead.

---

## Stage 0.1: Environment and provisional model selection (2026-10-06)
**Objective:** confirm the project can run locally at zero cost on the target laptop.
**Work:** installed Python, Git, VS Code and a local model server (Ollama); wrote a smoke test.
**Files:** `src/scripts/smoke_test.py`, `src/scripts/smoke_test_v2.py`, `docs/adr/ADR-003-model-selection.md`
**Key decisions:**
- Constrain model output with a JSON schema. The first test returned valid JSON that contained the prompt template
  instead of a category: valid structure is not a correct answer.
- Two model tiers: 3B for development, 7B candidate for evaluation, final choice pending the 150-ticket comparison.
**Evidence:** 3B: 5/5 valid, 4/5 correct, about 16-18 tokens/s. 7B: 5/5 valid, 5/5 correct, about 4-7 tokens/s,
system memory at 93% under load.

## Stage 0.2: Governance documents (2026-10-06)
**Objective:** define scope, measures and risks before building.
**Files:** `docs/charter.md`, `docs/risk-register.md`, `docs/priority-rubric.md`
**Key decisions:** targets are hypotheses to re-baseline after Phase 1; ground-truth labels are derived from
rubric attributes, never from a model; evaluation is by the project team and is reported as such.

## Stage 0.3: Data design (2026-10-06)
**Objective:** design the dataset and labels before writing generator code.
**Files:** `docs/data-design.md` (v1.0, then v1.1 and v1.2)
**Key decisions:**
- Labels stored apart from the operational database so the agent cannot read them.
- Eight ticket categories with boundary rules; 26 scenarios, 150 development tickets, 35% edge or adversarial.
- Held-out set generated with a different seed and frozen until Phase 4.
- v1.1: money stored as integer cents, to avoid floating-point rounding in financial amounts.

## Stage 0.4a: Generator base (2026-10-06)
**Objective:** database schema, customers, addresses, product catalogue.
**Files (new):** `pytest.ini`, `src/datagen/{__init__,config,schema,reference,base_data,db,cli}.py`,
`tests/test_datagen_base.py`
**Key decisions:** fixed reference date (output does not depend on the day it is run); separate random stream per
entity type; database creation refuses to overwrite without `--force`.
**Evidence:** 12 tests passing; 200 customers, 241 addresses, 60 products from seed 20261006.

## Stage 0.4b: Order histories and integrity checks (2026-10-06)
**Objective:** generate 600 orders whose histories are internally consistent, and prove it independently.
**Files (new):** `src/datagen/orders.py`, `src/datagen/policy.py`, `src/datagen/checks.py`,
`tests/test_datagen_orders.py`
**Files (changed):** `src/datagen/config.py`, `src/datagen/reference.py`, `src/datagen/db.py`,
`src/datagen/cli.py`, `docs/data-design.md` (v1.2)
**Key decisions:**
- Two-step build (plan a timeline, then build rows) so scenario orders can follow the same rules as background orders.
- 17 integrity checks written in SQL, separate from generator logic; each is tested by deliberately corrupting data.
- Simplifications recorded in data-design section 4a (calendar days, full refunds, no tax or shipping).
**Defect found by inspection and fixed:** processing orders had identical round timestamps. Added a regression test.
**Evidence:** 42 tests passing; 600 orders; 17/17 integrity checks pass across six seeds.
**Reproducibility note:** adding the timestamp fix changed which random numbers were drawn, so counts changed
(for example processing orders 35 to 40, duplicate-charge payments 7 to 9) with the same seed. Same seed does not
protect against code changes; see the seed explanation in the project notes and the dataset manifest planned for 0.4d.

---

## Stage 0.4c-1: Ticket framework and order-status scenarios (2026-10-06)
**Objective:** produce the first tickets and ground-truth labels, with a framework the remaining scenario
families will reuse. Delivered in increments: 0.4c-1 (framework, S01-S04, S22), 0.4c-2 (returns, exchanges,
refunds), 0.4c-3 (cancellation, address, account, product info, other, adversarial).
**Files (new):** `src/datagen/{taxonomy,priority,kb_catalogue,labels,text,scenario_base,scenario_order_status,
scenario_registry,tickets}.py`, `tests/test_datagen_tickets.py`
**Files (changed):** `src/datagen/{config,orders,db,checks,cli}.py`, `docs/data-design.md` (v1.3)
**Key decisions:**
- The priority rubric is implemented as code (`priority.py`); labels compute priority from attributes and are
  validated on creation, so a label can never disagree with the rubric.
- Labels carry `expected_facts` taken from the database, so replies can later be graded for invented facts.
- Each scenario has its own random stream; one scenario's text is unaffected by others.
- Scenario orders use the same builder as the background pool and continue its id numbering.
- S04 redefined: two open orders and no order number, so the correct action is to ask which one.
**Defect found by reading samples:** one phrasing combined with a polite closing produced a double "Thanks";
phrasing replaced.
**Evidence:** 88 tests passing; 33 tickets (S01=10, S02=8, S03=5, S04=6, S22=4); 18 integrity checks pass.
Mutation checks: deliberately breaking the S22 deadline range, an S02 priority flag, and an S04 order-number
leak each made the tests fail.
**Open item:** held-out phrasing is not yet separate from development phrasing (stage 0.4d).

---

## Stage 0.4c-2: Returns, exchanges and refunds (2026-10-06)
**Objective:** add nine scenarios (S05-S11, S21, S23; 57 tickets), bringing the development set to 90 of 150.
**Files (new):** `src/datagen/scenario_returns.py`, `tests/test_datagen_returns.py`
**Files (changed):** `src/datagen/{config,orders,text,kb_catalogue,scenario_base,scenario_order_status,
scenario_registry}.py`, `tests/test_datagen_tickets.py`, `docs/data-design.md` (v1.4)
**Key decisions:**
- Return acceptance is decided by `policy.within_return_window`; the generator refuses to build a ticket whose
  order contradicts its scenario, so labels cannot drift from policy.
- Shared fact builders moved into `scenario_base.py` once a second family needed them.
- A ticket may not arrive before any event on its order.
- Money in ticket text is formatted from integer cents (no floating point).
**Defects found by reading samples (not by the integrity checks):**
- Plural product names produced wrong grammar ("Hiking Pants is too small"); also present in two phrasings from
  the previous stage. Fixed with agreement fields in `text.grammar_fields`.
- Pronoun and article errors ("exchange they", "a S"); subject lines that did not match the request.
- A design error: S06 listed boundary days 29-32, but days 29 and 30 are inside the window. Corrected in v1.4.
**Test method note:** a regex first flagged four false positives ("Order O-000617 (Basecamp Gloves) is late" is
grammatical); the check was tightened and then verified to still catch the real bug when re-introduced. The
grammar test runs across six seeds because plural products appear only on some seeds.
**Evidence:** 115 tests passing; 90 tickets; 18 integrity checks pass. Mutation checks (S06 day 30, missing S11
flag, S21 time limit, ticket before delivery) each failed the tests.
**Open items:** held-out phrasing separation (0.4d); remaining scenarios S13-S20, S24-S26 (0.4c-3).

---

## Stage 0.4c-3: Remaining scenarios, development set complete (2026-10-07)
**Objective:** add the final eleven scenarios (S13-S20, S24-S26; 60 tickets), completing the 150-ticket development set.
**Files (new):** `src/datagen/{scenario_changes,scenario_accounts,scenario_adversarial}.py`,
`tests/{test_datagen_changes,test_datagen_accounts,test_datagen_adversarial}.py`
**Files (changed):** `src/datagen/{config,kb_catalogue,text,scenario_base,scenario_returns,scenario_registry}.py`,
`tests/{test_datagen_tickets,test_datagen_returns}.py`, `docs/data-design.md` (v1.5)
**Key decisions:**
- Adversarial labels describe the legitimate underlying issue plus `injected_instruction` and `must_not`, so a
  grader can score "resisted" versus "obeyed" without judgement.
- Tickets that are not about an order use a separate builder; the label records that no order is referenced.
- Helpers needed by two families moved into `scenario_base.py`; one unused function was removed from `scenario_returns.py`.
- Policy facts in knowledge-question labels are verified against the generated data (delivery days, refund age).
- Policy wording corrected to calendar days, matching the data (data-design section 3).
**Defects found by reading samples (not by the integrity checks):**
- Typo injection corrupted a requested delivery address ("Aevnue") so the ticket disagreed with its label. Typos now
  skip text that labels record.
- Complaint wording was appended to pre-purchase questions ("disappointed with the service so far"). Those
  questions now use calm tones only.
- Double thanks ("Thanks for your help with this. Thank you so much,") caused by the shared tone wrapper.
- An impersonation ticket's subject did not match its claim.
**Existing tests changed (with reasons):** a hard-coded ticket count (90) now derives from the registry; two tests
assumed every referenced order belongs to the sender, which impersonation tickets deliberately violate (now
asserted the other way round in `test_datagen_adversarial.py`).
**Evidence:** 153 tests passing (Python 3.13); 150 tickets (47 edge, 13 adversarial); 18 integrity checks pass.
Seven mutation checks (typo in address, unhappy tone on questions, typo in attack text, wrong locked-customer
source, attack succeeding in a label, sender equal to order owner, orphaned knowledge-base article) each failed the tests.
**Known limitations:** the set over-represents difficult cases (priority mix 96 LOW, 25 MEDIUM, 29 HIGH), so accuracy on
it will not predict accuracy on real traffic; the held-out split still reuses development phrasing (stage 0.4d).

---

## Stage 0.4d-1: Held-out phrasing mechanism and order-status pools (2026-10-07)
**Objective:** make the held-out split measure unseen wording. Stage 0.4d is delivered in three parts: 0.4d-1 mechanism
and order-status pools; 0.4d-2 pools for the remaining families; 0.4d-3 manifest, label checks and freeze.
**Files (new):** `src/datagen/phrasing_heldout.py`, `tests/test_datagen_heldout.py`
**Files (changed):** `src/datagen/{scenario_base,tickets,cli,scenario_order_status}.py`
**Key decisions:**
- Each scenario has a held-out pool with the same length and the same meaning at each index as its dev pool
  (same difficulty, tone, deadline and ambiguity settings), so labels and edge-case coverage match across splits.
- Held-out wording is hand-written and independently phrased; a test caps 4-word-sequence overlap with dev wording at 25%.
- A held-out scenario without a pool is an error (`MissingHeldoutPhrasing`), enforced in the generator itself rather
  than left to each builder, so dev wording can never leak into the held-out set by omission.
- The development dataset is byte-identical before and after this change (verified by comparing label files).
**Defect found by testing:** the first version relied on each builder calling the pool lookup, so an unconverted
scenario would have silently reused dev wording; the generator-level guard was added after a test exposed this.
**Evidence:** 166 tests passing (Python 3.13); dev labels unchanged. Mutation checks: copying a dev sentence into the
held-out pool, and changing a held-out deadline setting, each failed the tests.
**Known limitations:** held-out generation is refused until 0.4d-2 supplies pools for the other 20 scenarios.

---

## Repository restructure (2026-10-07)
**Objective:** group files by responsibility as the codebase grows. No behaviour change.
**Layout:** `src/datagen/` is split into layers: `domain` (rules and vocabulary), `generation` (building blocks that
create data), `store` (database), `scenarios` (ticket families and held-out phrasing); `config`, `tickets` and `cli`
stay at the top level. Tests move to `tests/datagen/`, scripts to `scripts/`, documents to `docs/project/` (charter, risk
register), `docs/design/` (priority rubric, data design) and `docs/adr/`. Scenario modules lose their `scenario_` prefix
(`scenario_returns.py` becomes `scenarios/returns.py`); test files lose `datagen_` (`test_datagen_orders.py` becomes
`tests/datagen/test_orders.py`).
**Key decisions:**
- All project imports are absolute (`from src.datagen.domain import labels`); no relative imports remain.
- Dependency rule: a layer may import only from itself and layers below it (domain, generation, store, scenarios);
  enforced by `tests/datagen/test_architecture.py`.
- The move was scripted (`git mv` plus an import rewrite based on Python's `ast` module) so file history is preserved
  and the change is mechanical and reviewable.
**Path mapping for earlier log entries:** module names in entries dated before this one use the old flat layout; map
them with the rule above (for example `src/datagen/scenario_base.py` is now `src/datagen/scenarios/base.py`,
`src/datagen/labels.py` is now `src/datagen/domain/labels.py`, `src/datagen/db.py` is now `src/datagen/store/db.py`).
**Evidence:** 168 tests passing (Python 3.13); regenerated development labels and database are byte-identical to
the pre-move output; the architecture test fails when a domain module imports from scenarios.

---

## Stage 0.4d-2: Held-out phrasing for all scenarios (2026-10-07)
**Objective:** complete the held-out split so every scenario is worded independently of its development counterpart.
**Files (changed):** `src/datagen/scenarios/{phrasing_heldout,returns,changes,accounts,adversarial}.py`,
`src/datagen/tickets.py`, `tests/datagen/test_heldout.py`
**Key decisions:**
- 100 hand-written phrasings added (S05-S11, S13-S21, S23-S26); each pool mirrors its development pool in length and in
  per-index meaning, including difficulty, tone, deadline, ambiguity, order state, knowledge-base ids and stated facts.
- Scenarios with more than one pool use suffixed keys (`S05_BOUNDARY`, `S11_REFUND`, `S11_REPLACE`, `S17_LOCKED`,
  `S17_NO_EMAIL`); the generator's guard accepts a scenario when any of its pools exists.
- S24 attack wording moved out of the builder functions into a pool, so the held-out attacks are different sentences
  with the same intent; attack text is still exempt from typo injection.
- Wording distinctness is measured per phrasing against every development phrasing (word-level similarity,
  cap 0.70). A first, looser metric (shared 4-word sequences against the pooled development text) was replaced because
  it rewarded short phrases for matching different development sentences; the per-pair measure flagged 13 held-out
  phrasings as near-copies, which were rewritten.
- Held-out and development label profiles are identical (same scenario, category, actions, escalation, difficulty and
  priority counts), so score differences between splits can be attributed to wording and data, not task mix.
**Evidence:** 218 tests passing (Python 3.13); held-out generation: 150 tickets, 18 integrity checks pass; development
labels byte-identical to before. Mutation checks: copying a development sentence into a held-out pool, changing a
held-out order state, and allowing typos in attack text each failed the tests.
**Known limitations:** held-out wording is written by one author, so stylistic range is limited; the held-out set is
the same size and mix as the development set (150 tickets) and over-represents difficult cases in the same way.

---

## Stage 0.4d-3: Manifest and freeze, dataset v1.0.0 (2026-10-07)
**Objective:** freeze the dataset so that later results are measured against a fixed, verifiable reference.
**Files (new):** `src/datagen/freeze.py`, `tests/datagen/test_freeze.py`, `data/manifest.json`,
`docs/dataset-manifest.md`, `.python-version`
**Files (changed):** `src/datagen/config.py` (versions 1.0.0), `docs/design/data-design.md` (v1.6)
**Key decisions:**
- Databases are hashed by table content rather than as files, so SQLite file layout cannot produce false alarms;
  the labels file is hashed as bytes (written as UTF-8 with `\n` endings on every operating system).
- `freeze write` builds in a temporary folder and refuses to run if any check fails or a manifest already exists;
  `freeze verify` rebuilds and names every artifact whose digest differs. The test suite runs the same comparison,
  so the freeze is enforced on every test run.
- Dataset-level checks added before a freeze: contiguous ticket ids matching labels, registry counts, valid labels,
  existing referenced orders, no duplicate text within a split, no shared text between splits.
- Python is pinned to 3.13 and the manifest records the interpreter, SQLite version and operating system.
- Change control recorded in data-design section 13: held-out unused before Phase 4; any change needs a version
  bump, an ADR and a re-freeze.
**Finding:** labels do not contain ticket wording, so a wording change alters only the `tickets` table digest, not the
labels digest; both are therefore recorded.
**Evidence:** 226 tests passing (Python 3.13); manifest verified; three mutation checks (changed held-out wording,
changed development seed, second `write` without `--force`) each produced the expected failure.
**Known limitations:** hashes were produced on one operating system; verification on a second platform (Windows) is
the cross-platform reproducibility check.

---

## Stage 0.5: Knowledge-base articles (2026-10-07)
**Objective:** write the 21 knowledge-base articles that labels cite, consistent with the published policy and the S19 facts.
**Files (new):** `data/seed/kb/*.md` (21 articles), `src/kb/__init__.py`, `src/kb/articles.py`, `tests/kb/test_articles.py`
**Files (changed):** `docs/design/data-design.md` (v1.7)
**Key decisions:**
- Each article has *Key facts* (atomic statements a citation can be checked against), *Details* (customer-facing) and
  *Support guidance (internal)*; internal guidance is separable so it is never shown to a customer.
- Policy facts are tested against `config.py` and the S19 labels, so an article cannot drift from the data without
  failing a test; durations use calendar days only.
- Articles stay at or below 250 words to keep retrieved context small for a CPU-run model.
- The knowledge base is outside the frozen dataset: the `kb_articles` table stays empty and the manifest is unchanged;
  articles are versioned by front matter and git history.
- Sizing and care articles are fictional product guidance; no article states a refund approval threshold (ADR-004 is
  decided in stage 0.7).
**Defects found while testing:** the first window test would not have caught a changed "30 days" key fact because the
number also appears elsewhere in the article; it now checks the key facts specifically. Two invented process claims
(dispatch order, bank authorisations) were removed because no policy or data supports them.
**Evidence:** 238 tests passing (Python 3.13); manifest still verifies. Mutation checks: changed return window,
"business days", an injected instruction, a missing article, and a changed cancellation rule each failed a test.
**Known limitations:** articles are written by one author and reviewed by the same person; retrieval quality is measured in Phase 2.

---

## Stage 0.6: Baseline protocol and timing tool (2026-10-07)
**Objective:** define and tooling-support the manual-handling baseline (objective O8, principle P6).
**Files (new):** `docs/project/baseline-protocol.md`, `src/baseline/{__init__,sampling,lookups,session,scoring,report,cli}.py`,
`tests/baseline/{conftest,test_sampling,test_session,test_scoring,test_cli}.py`
**Key decisions:**
- The baseline uses development tickets only; the held-out split stays unused until Phase 4. The consequence for the
  Phase 4 accuracy comparison is recorded in the protocol (threats to validity).
- Sample: 40 scored tickets plus 3 practice tickets, stratified by scenario with the generator seed (every scenario at
  least once); chosen once and not changeable after results exist.
- The timing tool shows the same records the agent's read-only tools will expose, so manual and automated runs use the
  same information. It cannot read ground-truth labels (an automated test inspects its imports and strings); scoring is a
  separate command run after all tickets are handled.
- The clock stops when the reply is submitted; pauses are excluded; a ticket cannot be abandoned or repeated once seen.
- Cost per ticket is shown as a sensitivity table over assumed hourly rates, not as a single finding.
- Five accuracy measures include a "consequential actions" rate, the manual counterpart of the wrong-action measure (O2).
**Defect found by testing:** my first expected value for the timer test was off by one input; the arithmetic is now
spelled out in the test, and a deliberate break (counting paused time) fails it.
**Evidence:** 263 tests passing (Python 3.13); four mutation checks (paused time counted, consequential errors ignored,
no minimum per scenario, session importing labels) each failed a test; a scripted run of the real command line worked end to end.
**Known limitations:** the baseline is single-handler and the handler is the project author; the run itself (about two
hours across sessions) and the generated report follow in this stage.

---

## Stage 0.7a: Refund approval thresholds (2026-10-07)
**Objective:** fix the refund approval limits before the policy engine and approval service are built (spec FR-6, FR-7).
**Files (new):** `docs/adr/ADR-004-refund-approval-thresholds.md`
**Files (changed):** `docs/design/data-design.md` (1.7 to 1.8)
**Key decisions:**
- Auto-approval up to $50.00, support-agent approval up to $250.00, support-lead approval above; four mandatory
  conditions for every tier and three more for auto-approval. Shadow mode (everything approved by a person) until Phase 4.
- The limits are a stated risk position defended by exposure reasoning. The development split described the scale of
  amounts only; the held-out split was not consulted.
- Policy outcomes are derived by rule and are not stored in labels, so dataset 1.0.0 and its freeze are unchanged.
- ADR numbering: the shared foundations document reserves ADR-004 for the vector store; this project committed the number
  to the refund thresholds earlier, and the vector-store decision takes the next free number.
**Evidence:** document stage; figures in the ADR were recomputed from the development labels and database (20 refund-action
tickets; counts at each limit; minimum adversarial amount $84.99).
**Open (stage 0.7b):** Phase 0 exit review after the manual baseline report is produced.

---

## Stage 0.7b-1: Baseline results and analysis additions (2026-10-07)
**Objective:** read the first baseline results correctly before the Phase 0 exit review.
**Results (40 scored tickets, one handler):** mean 162 s, median 136 s, 90th percentile 260 s; category 92.5%, action set 82.5%,
escalation decision 92.5%, consequential actions 90.0%, required articles 87.5%; ten tickets differed on category or actions.
Median time fell from 237 s (first 13 tickets) to 103 s (last 13).
**Issues found in the first report:** the dataset row did not state the dataset version; accuracy was shown without
counts or intervals; the consequential rate counted every ticket, including those with no consequential action; escalation
had no precision and recall, so it could not be compared with objective O3; the list of differences did not show the
handler's answer beside the label.
**Files (changed):** `src/baseline/{scoring,report,cli}.py`, `tests/baseline/{test_scoring,test_cli}.py`,
`docs/project/baseline-protocol.md` (1.0 to 1.1). **Files (new):** `docs/project/baseline-disagreement-review.md` (template).
**Key decisions:**
- The report now shows the dataset version from the manifest, counts with 95% Wilson intervals, the consequential rate on
  relevant tickets, an escalation table with precision and recall, and a detailed disagreement list.
- Each disagreement is classified (handler error, label error, knowledge-base defect, policy ambiguity) before it is counted as a
  manual error. These analysis additions were made after the ticket list was seen; the protocol records this and the collection
  procedure, sample and scoring rules are unchanged.
**Evidence:** 267 tests passing; four mutation checks (escalation positives, interval formula, disagreement filter, relevance
rule) each failed a test; the relevance mutation first survived and exposed a weak test, which was strengthened.
**Known limitations:** the review is a self-review by the handler and dataset author.

---

## Stage 0.7b-2: Disagreement review tool (2026-10-07)
**Objective:** make the review of baseline disagreements fast and consistent, without automating the judgement.
**Files (new):** `src/baseline/review.py`, `tests/baseline/test_review.py`. **Files (changed):** `src/baseline/cli.py` (new `review`
subcommand), `docs/project/baseline-protocol.md` (tool described in section 8).
**Key decisions:**
- The tool shows, per disagreement, the ticket, the records, the handler's answer, the label and the key facts of the required
  and cited articles, with a neutral pointer to where to look. The reviewer chooses H, L, K or P and writes the evidence; the tool
  never proposes a code, because a suggested classification would anchor a self-review.
- Decisions are appended to `data/baseline/review.jsonl` (resumable; a later decision for a ticket replaces an earlier one) and the
  review document is rendered from that log, so it can be regenerated and always matches the record.
- The review reads labels, so it is a separate module; a test checks that the timed tool cannot import it.
- The summary states manual accuracy two ways, first pass and handler errors only, on the same denominator.
**Evidence:** 278 tests passing; five mutation checks (later decision ignored, defect count including handler errors, table cells
unescaped, empty evidence accepted, log ignored) each failed a test; one survived at first and exposed a weak test, which was strengthened.
**Known limitations:** self-review by the handler and dataset author.

---

## Stage 0.7b-3: Confirming drafted review decisions (2026-10-08)
**Objective:** allow the reviewer to work quickly from prepared proposals without losing the reviewer's accountability.
**Files (changed):** `src/baseline/review.py`, `src/baseline/cli.py`, `tests/baseline/test_review.py`.
**Key decisions:**
- Proposals live in `data/baseline/review-draft.jsonl` and are never recorded automatically. Each one is shown beside the
  handler's answer and the label; the reviewer accepts it, takes it back for review from scratch, or stops.
- An accepted proposal is stored with its source, and the generated review states how many decisions were drafted with assistance
  and confirmed by the reviewer. A review done entirely by hand carries no such statement.
**Evidence:** 282 tests passing; mutation checks (source not recorded, "review myself" still recording) each failed a test.

---

## Stage 0.7b-4: Phase 0 exit review and storage decision (2026-10-08)
**Objective:** evidence the Phase 0 exit criteria, review the charter objectives against the baseline, and record the storage decision.
**Files (new):** `docs/project/phase-0-exit-review.md`, `docs/adr/ADR-005-operational-data-store.md`.
**Files (changed):** `docs/project/risk-register.md` (1.0 to 1.1).
**Key decisions:**
- No objective is re-baselined at this gate: the evidence concerns the manual process and no model has been measured. The next
  re-baseline point is the Phase 1 exit.
- Metric definitions to fix in the Phase 1 evaluation design: executed versus proposed wrong actions, escalation reported with
  intervals (22 escalation tickets per split), autonomous resolution, citation validity.
- Storage: SQLite, one file per split, read-only access for tools that must not change data (ADR-005). ADR-004 is the refund
  thresholds, so the vector-store decision takes the next free number.
- Two risks added: instruments omitting information the agent will have (R15) and too few escalation cases (R16).
**Evidence:** figures in the exit review recomputed from the report and the development labels and database; intervals are Wilson intervals.
**Known limitations:** four exit criteria depend on commands run on the project machine and are marked "Confirm" until evidenced.

---

## Phase 0 closed (2026-10-08)
**Decision:** Phase 0 (Discovery, baseline and data) is closed; the exit review is `docs/project/phase-0-exit-review.md` and the charter milestone is marked complete.
**Evidence recorded at sign-off:**
- `python -m src.datagen.freeze verify` on the project machine (Windows, Python 3.13): `Verified: dataset 1.0.0 matches the manifest (all hashes identical).`
- Baseline data, the disagreement review and the automated test result were confirmed by the Project Lead at sign-off.
**Carried into Phase 1:** the actions in section 6 of the exit review, in particular category definitions in the agent prompt, the evaluation metric definitions, and the 150-ticket model comparison with a pinned model digest.

---

## Stage 1.1: Phase 1 design and architecture decision (2026-10-08)
**Objective:** fix the shape of the first agent version before writing code.
**Files (new):** `docs/design/phase-1-design.md`, `docs/adr/ADR-006-fixed-pipeline-architecture.md`.
**Key decisions:**
- Fixed pipeline: code owns the order of steps and every business decision; the model reads the ticket into a schema and
  words the reply from verified facts. An agent loop is built later on the same tools and compared on the same measures
  (ADR-006); the held-out run is made once per variant at Phase 4.
- Slice: the 35 development tickets whose category is order_status (S01 to S04, S22, two adversarial S24). Other categories are
  recognised and routed to a person.
- Reply validation with a code-built template fallback; the share of fallbacks is reported.
- Traces are JSON Lines files kept outside the operational database, which stays read-only for every tool.
- Evaluation: set A (35 in-slice tickets, end to end) and set B (115 others, classification only), development split only,
  guard against the held-out split.
**Evidence:** document stage. Scenario counts and the order-status profile were taken from the development labels.
**Open item settled in a later stage:** whether the tools are also served over MCP (1.7).

---

## Stage 1.2: Read-only tools (2026-10-08)
**Objective:** build the only door from the agent to the operational database, as specified in the Phase 1 design (section 4).
**Files (new):** `src/agent/__init__.py`, `src/agent/tools.py`, `tests/agent/conftest.py`, `tests/agent/test_tools.py`.
**Key decisions:**
- Four tools (`get_ticket`, `find_customer`, `list_open_orders`, `get_order`) with typed results and one JSON-schema table
  (`TOOL_SCHEMAS`) so the fixed pipeline and a later agent loop share one interface (ADR-006). `Toolbox.call(name, arguments)`
  dispatches by name and returns plain JSON.
- Read-only twice over: the file is opened with `mode=ro` and the connection also sets `PRAGMA query_only`, so a writable connection
  passed in is made read-only too.
- Every argument is validated before SQL; SQL uses bound parameters. Expected conditions (`not_found`, `not_owned`,
  `invalid_argument`) are returned as a status, not raised.
- `get_order` refuses another customer's order and returns nothing about it, not even the order id or the owner.
- Results exclude addresses, card digits and payment records (NFR-3).
- The agent package may not import the data generator or the baseline tool, and may not mention the labels path (tested).
**Defect found by testing:** the id patterns used `match` with `$`, which also accepts a trailing newline (`"T-000001\n"` was
treated as a valid id and returned "not found"). Patterns now use `fullmatch`; the email pattern has a test for the same case.
**Evidence:** 309 tests passing (27 new). Agreement test: for all in-slice development tickets with an order, the tools return the same
status, promised date and, for shipped orders, carrier, tracking number and last status as the labelled facts. Six mutation checks
(ownership check removed, closed orders counted as open, read-only pragma removed, case-sensitive email, extra arguments allowed,
owner leaked in the refusal) each failed a test.
**Known limitations:** `Order` carries one shipment because the dataset has at most one per order (guarded by a test); the fixture
module for `tests/agent` imports the shared fixtures from `tests/baseline`, to be consolidated when a third test package needs them.

## Stage 1.3: Model client, prompt v1, reading step (2026-10-08)
**Files (new):** `src/agent/taxonomy.py`, `src/agent/prompting.py`, `src/agent/model.py`, `src/agent/reading.py`,
`src/agent/prompts/read_ticket.v1.md`, `src/agent/prompts/__init__.py`, `scripts/probe_read_step.py`, `scripts/__init__.py`,
`tests/agent/test_model.py`, `tests/agent/test_reading.py`. **Changed:** `docs/design/phase-1-design.md` (v1.1).
**Key decisions:**
- Category definitions and the six boundary rules from the data design are in the prompt (carry-forward action 1). Rule 5 (general policy
  question with no order is product_info) is stated explicitly. The category list is restated in the agent package, which may not import the
  generator; a test compares it with the generator's taxonomy.
- Model client: local hosts only by default; temperature 0; explicit seed per call; token limit; JSON schema in the `format` option; model digest
  read from `/api/tags`. Failures are returned as an `error` value, never raised. The transport is injectable, so every test runs without Ollama.
- Prompts are versioned files; the loader returns name, version and SHA-256 for the trace.
- Ticket text is passed as data between `<ticket>` delimiters; delimiter lookalikes are removed and the text is capped at 4,000 characters.
- Order numbers come from a pattern in code, not from the model (design v1.1).
- Step 2 accepts only the exact three fields with an allowed category and true booleans (an integer 1 is rejected). One retry with seed+1,
  then the outcome is `failed` with a reason (`model_error` or `invalid_reading`) and the pipeline routes the ticket to a person.
**Evidence:** 356 tests passing (47 new). Pattern check: all 150 development labels agree (119 found, 31 none). Seven mutation checks
(retry seed unchanged, loose boolean check, delimiter stripping removed, length cap removed, temperature changed, local-only check removed,
word boundary removed from the pattern) each failed a test.
**Not yet evidenced:** behaviour of the real model. The probe script (`python -m scripts.probe_read_step`) measures category agreement with the
development labels, the two flags, latency and tokens; the results feed prompt v2 and the model comparison in stage 1.6.
**Known limitations:** the deadline flag is compared with `deadline_within_3_days`, which is a narrower label, so that agreement figure is indicative only.

## Stage 1.4: Identification, decision rules, reply drafting and validation, pipeline (2026-10-08)
**Files (new):** `src/agent/deadline.py`, `decide.py`, `validate.py`, `reply.py`, `pipeline.py`, `src/agent/prompts/read_ticket.v2.md`,
`src/agent/prompts/reply.v1.md`, `tests/agent/support.py`, `test_deadline.py`, `test_decide.py`, `test_validate.py`, `test_reply.py`,
`test_pipeline.py`. **Changed:** `src/agent/reading.py`, `src/agent/prompting.py`, `scripts/probe_read_step.py`, `tests/agent/test_reading.py`,
`docs/design/phase-1-design.md` (v1.2), `docs/project/risk-register.md` (v1.2). `read_ticket.v1.md` is unchanged and kept as the record of the first run.
**Design correction found while building:** design v1.0 said to escalate on any stated deadline for an undispatched order. The data design keeps
S03's far-away deadline (T-000058, a trip nine days after the ticket) as an information reply, so the rule needs the date. Step 1 now returns the
customer's own wording and code resolves it and applies the 3-day window. Prompt read_ticket v2 changes only this field; the category wording is
unchanged, so category results from v1 remain comparable.
**Key decisions:**
- Rules are a pure function of reading, identity and the ticket date; "today" is the ticket's arrival date so replays are exact. A legal threat
  or a non-order-status category is handed over before any customer record is read (tested).
- The reply model writes only the body of an information or information-request reply, from verified facts; it never receives the ticket text.
  Greeting and sign-off are code. Hand-overs use fixed templates and make no model call.
- The validator has ten named rules (design section 6). Templates pass the same validator (tested for every reason).
- An account-status rule I first added (locked account to a person) disagreed with the labels on 2 of 35 tickets and has no basis in the design
  table, so it was removed; recorded as an open policy question.
- Prompt hashing normalises line endings (CRLF and LF alike, one trailing newline). The v1 hash first reported (`1915f1eeab1e`) was the hash of
  Windows file bytes; the normalised hash of the same text is `3e0d4c25df06`. Hashes are now identical on every machine. The v1 probe runs used the
  Windows (CRLF) text as input.
**Evidence:** 491 tests passing (135 new since stage 1.3).
With a perfect reader and template replies, all 35 in-slice development tickets get the labelled action, escalation decision, escalation reason and
article. The deadline resolver reproduces all 5 labelled deadline dates (4 within the window, 1 outside). Thirteen mutation checks (window boundary,
weekday arithmetic, late comparison, deadline rule, privacy facts, legal rule, promise rule, relative-time rule, order-id digits in tokens,
guidance shingle size, retry seed, model use for hand-overs, phrase-in-ticket check) each failed a test; one further mutation (lookup for every
ticket) survived until a test was added.
**Defects found by testing:** (1) the validator read the digits of order numbers as unknown references; (2) the "delivered" template was
required to state the promised date; (3) no development ticket exercises "no order number and exactly one open order", so that path is tested with a customer taken from the database.
**Not yet evidenced:** real-model behaviour of read prompt v2 and of the reply prompt (draft acceptance rate, template share, latency). These are the first measurements of stage 1.6; the probe now reports deadline-date agreement.
**Known limitations:** numeric day/month wording (9/10) is not interpreted; order-status wording about several orders is answered with a question; locked accounts are not treated differently.

## Stage 1.4b: Read prompt v3 and probe diagnostics (2026-10-08)
**Finding (probe of prompt v2, 150 development tickets):** category agreement 132/146 = 90.4% (v1: 135/150 = 90.0%), so the v2 change did not
affect category reading; all 5 labelled deadlines resolved to the correct date. Two defects: (1) 12 tickets (S01, S02, S23) had the order-placed
date quoted as a needed-by date, which the resolver rolled into 2027; the outcome was safe here but a misquoted promised date on an unshipped
order could cause a false escalation; (2) 4 of 150 readings failed (v1: 0), cause not recorded by the probe.
**Changes:** `read_ticket.v3.md` (deadline paragraph only: placed, dispatched, delivered and promised dates are never a needed-by date; "no date"
is an empty string); `reading.py` treats "none", "n/a", "no deadline" and similar as an empty phrase; `probe_read_step.py` lists each failed
reading with its reason and the model's raw output, and defaults to v3. v1 and v2 files are kept as records.
**Evidence:** 501 tests passing (10 new); one mutation (null-word handling removed) fails a test.
**Not yet evidenced:** the effect of v3 on the 12 misquoted dates and the 4 failed readings; to be read from the next probe run.

## Stage 1.4c: Read prompt v3 measured (2026-10-08)
**Probe of read_ticket v3 on the 150 development tickets:** category agreement 136/149 = 91.3% (95% interval about 86% to 95%); 1 reading failed
(v2: 4); chargeback or legal flag 149/149; all 5 labelled deadlines resolved to the labelled date. The failed reading (T-000131) is the validity
check working: the model returned the wording "Thursday" for a ticket that contains no date, the check rejected it on both tries, and the ticket went to a person.
Six past dates quoted by customers (due or placed dates on shipped orders) still differ from the labels; the deadline rule applies only to unshipped
orders and a past date resolves to next year, so none changes an outcome. Known limitation: a quoted promised date on an unshipped order could
trigger a false escalation. The read step can cost at most 3 of the 35 in-slice tickets (T-000072 injection, T-000048 vague ticket, T-000131); all go to a person.
**Decision:** prompt v3 (sha256 475f773cdfe6, line-ending-normalised) is frozen as the working read prompt until the model comparison in stage 1.6.

## Stage 1.5: Tracing and the run command (2026-10-08)
**Files (new):** `src/agent/tracing.py`, `src/agent/run.py`, `tests/agent/test_tracing.py`. **Changed:** `src/agent/pipeline.py` (input fingerprints, per-attempt
detail in each model step), `docs/design/phase-1-design.md` (v1.3, section 7).
**Key decisions:**
- One directory per run with run.json, trace.jsonl, resolutions.jsonl and summary.json; a run id is never reused (creating it twice fails).
- Lines are flushed per ticket, so an interrupted run is still readable and still gets a summary.
- Privacy: traces carry short hashes of each step's input, not ticket text or email addresses (tested against five tickets).
- The summary is derived only from the files, so it can be rebuilt; the template fallback share counts only tickets where a model draft was attempted (hand-overs use
  templates by design and are not fallbacks).
- The run command takes ticket ids from the caller (`--limit` or `--ids-file`), never from labels, and refuses the held-out split; it records the model digest, prompt hashes, dataset file hash and git commit.
**Evidence:** 520 tests passing (19 new). Eight mutation checks (run id reuse, flushing, held-out guard, closing on error, email stored in the trace,
fallback share counting hand-overs, percentile rounding, read fingerprint ignoring the ticket text); two survived at first (percentile rounding and the
fingerprint source) and tests were added for both.
**Not yet evidenced:** real-model reply drafting (acceptance rate, fallback share, latency per ticket); the first run with `python -m src.agent.run` is the first measurement.
**Housekeeping:** add `data/runs/` to `.gitignore`.

## Stage 1.5b: Retries that change the request, and a warm-up call (2026-10-08)
**Smoke run (10 development tickets, llama3.2:3b, read v3, reply v1):** 10 of 10 readings valid; the 4 out-of-slice tickets, the not-owned order
(T-000005, read as order status and stopped by the ownership check) and the deadline ticket (T-000010, "Thursday" resolved to the 8th) were decided as expected;
4 replies were drafted by the model, 2 accepted and 2 replaced by the template after the validator found a missing fact (T-000002 omitted the tracking number;
T-000007 omitted the promised date and put the tracking number in the status sentence). The 24.7 s maximum latency was the first call loading the model.
**Findings:** (1) at temperature 0 the seed has no effect, so the retries returned identical text and doubled the draft time for nothing (the failed reading
in the v3 probe also repeated); (2) cold start inflated the latency maximum; (3) the model sometimes returns a sentence instead of a date in `deadline_phrase`
(T-000002, T-000007); it is verbatim in the ticket so it passes the check, and the resolver ignores it because it names no date.
**Changes:** `reading.py` (`diagnose_reading` returns the problem in words; the retry shows it to the model; transport failures are retried unchanged),
`reply.py` (`retry_hint` from rule codes and the missing facts; the rejected draft is not fed back), `validate.py` (`missing_facts`), `pipeline.py`
(retry hints are traced), `run.py` (`warm_up`, `warmup_ms` in run.json), design doc v1.4.
**Evidence:** 531 tests passing (11 new). Seven mutation checks (hint removed from the read retry, hint recorded but not sent, JSON reminder applied to
every error, reply hint not sent, missing facts not named, warm-up skipped, hints not traced) each failed a test.
**Not yet evidenced:** whether the hinted retry lowers the template fallback share on the real model (2 of 4 in the smoke run). Compare on the next run.
**Housekeeping:** commit before an official run; run.json records `dirty: true` when the working tree has uncommitted changes.

## Stage 1.5c: Validator tightening, template reply mode, warm-up on the real prompt (2026-10-08)
**Second smoke run (10 development tickets, llama3.2:3b, clean commit):** 0 of 4 model-drafted replies fell back to the template (first run: 2 of 4); median 5.4 s
per ticket, p90 21 s; warm-up 7.5 s. Reading the accepted replies showed that a fallback share of zero hides quality problems: T-000007 wrote the tracking number as
the "latest tracking status" and called the past promised date "expected"; T-000002 (second draft) told the customer to track the order on the carrier's website, which
was not supplied. Both passed all ten rules because the rules checked that facts were present, not how they were used.
**Changes:** `validate.py` (`unsupported_claim`, `misplaced_reference`), `reply.py` (retry hints for both; the missing-fact hint reads "It must include"; a late shipment
must say "promised"; `use_model=False` gives the template-only reply), `pipeline.py` and `run.py` (`--reply-mode {model,template}`, recorded in run.json; the warm-up call
uses the real read prompt and schema), `tracing.py` (run-id suffix widened to 6 hex characters: with 4, fifty ids in one second collided about 2% of the time, which made a
test flaky and could have refused a run), design doc v1.5.
**Evidence:** 539 tests passing (8 new, 2 updated). Regression tests use the traced texts of T-000007 and T-000002. Five mutation checks each failed a test: misplaced-reference rule disabled, channel rule disabled, label pattern without the optional "is", template mode ignored in `draft_reply`, and template mode ignored in the pipeline. The last one first survived (the pipeline wiring had no test); a test over all 35 in-slice tickets now covers it.
**Not yet evidenced:** the hinted retry and the new rules on the real model (rerun the smoke test); how many accepted replies are inaccurate (stage 1.6 reply-accuracy check).

## Stage 1.6a to 1.6c: Evaluation harness and the first full development run (2026-10-08)
**Built (1.6a, 1.6b):** `src/evaluation/` with a scorer (Set A end to end, Set B hand-over, read-step agreement, Wilson intervals, held-out guard), a paired run
comparison (exact sign test, refuses different data or tickets) and a blind reply review (model reply against template reply, seeded order, key held apart,
resumable). 564 tests; sixteen mutation checks each failed a test (two survivors found and covered).
**First full run (commit ea5af9bc, clean tree, 150 development tickets):** three runs, llama3.2:3b with model-written replies, llama3.2:3b template-only, and
qwen2.5:7b with model-written replies. Results are in `docs/evidence/phase-1-first-full-run.txt`. Summary: the read step gave 150 of 150 valid readings and
category agreement of 137/150 (3B) and 139/150 (7B). Set A end to end: 33/35 (3B) and 35/35 (7B). Set B: 115/115 handed to a person and 0/115 answered by the agent in
all three runs. Template fallbacks: 10 of 29 (3B) against 3 of 31 (7B), Fisher exact p = 0.028 (different draft sets, so unpaired). Median latency for a Set A ticket:
12.3 s (3B), 26.0 s (7B), 4.3 s (template-only); full run 15.9, 31.4 and 10.3 minutes.
**Findings:** (1) the old rule order routed four labelled chargeback or legal-threat tickets instead of escalating them, although the reader had flagged all four;
(2) all five 3B replies for not-yet-dispatched orders called the promised delivery date a shipping date ("we are expecting to ship it on October 15"), which the
validator could not see; none of the 7B replies did; (3) 7B replies say the promised date "remains" a date that has passed, which needs the reviewer's judgement;
(4) the 3B model reads 13 tickets in the wrong category and misses T-000048 (an order question read as product_info) and T-000072 (an order question with an
injected instruction, read as other), both of which the 7B model gets right; the 7B model reads the impersonation ticket T-000121 as order status and the ownership
check then escalates it, which is the guard working and not the reader; (5) 16 or 17 tickets labelled "escalate" are only routed in this slice (suspected account
compromise 5, chargeback or legal 4 before the correction, identity not verified 2 to 3, not in the knowledge base 5): a Phase 3 policy-engine item.
**Changes (1.6c):** `decide.py` (legal threat before out of slice), `validate.py` and `reply.py` (`wrong_date_role`, `delivery_dates_only`), `review.py` (tickets on
which the runs decided differently are excluded and listed instead of aborting), design doc v1.6.
**Evidence:** 570 tests (6 new). Seven mutation checks each failed a test. Replayed offline over the accepted replies of the first run, the new rule rejects exactly
the five defective 3B replies and none of the 28 accepted 7B replies. It was written after seeing those five, so it is a rule about what the supplied date means
and not a tuned threshold; the final runs are the test of it.
**Next:** final runs on the corrected code (3B, 3B template-only, 7B), blind review of the model-written replies, the first evaluation report.


## Stage 1.7: Demonstration, tool-access decision and Phase 1 exit (2026-10-09)
**Built:** `src/agent/demo.py` (`python -m src.agent.demo --list N` / `--ticket ID [--model M] [--reply-mode R]`), which runs one development ticket through the pipeline and prints each step, the decision and the reply. It reads no labels, writes no traces, refuses the held-out split. 578 tests (5 new).
**Decided:** ADR-008, in-process read-only tools in Phase 1; MCP adapter built with the Actions server in Phase 3.
**Closed:** Phase 1 exit review (`docs/project/phase-1-exit-review.md`). Old smoke-test scripts removed (results are recorded in ADR-003).
**Next:** Phase 2, first stage: read prompt v4 for legal-flag precision, then knowledge-base retrieval.


## Stage 2.1: Read prompt v4, legal-flag precision (2026-10-09)
**Problem (ADR-007 condition, risk R18):** with read prompt v3 the qwen2.5:7b reader flagged 7 development tickets as chargeback or legal threats that are not (duplicate or wrong charges, bank statements, requests to skip review). 3B had none. Escalation is the safe direction, but 7 of 115 out-of-scope tickets (6.1%) were escalated unnecessarily.
**Change:** `read_ticket.v4.md` rewrites field 3 only: a threat must be the customer's own stated intention to take a named step (chargeback, bank dispute, lawyer, lawsuit, regulator), and payment problems, refund requests, bank statements and instructions to skip review are listed as not threats. The category and deadline text is unchanged from v3 (tested). The wording describes the rule and quotes no ticket text. `scripts/probe_read_step.py` now reports legal flags caught, missed and falsely raised, and lists the false alarms.
**Evidence:** 580 tests. The prompt has not yet been run against a model; v3 remains the default until it passes the acceptance test below.
**Acceptance test (fixed before the run):** on the 150 development tickets with qwen2.5:7b, v4 must catch all 4 labelled threats, raise at most 2 false alarms, and keep category agreement within 2 tickets of v3 (139). It is also run on llama3.2:3b and must catch all 4 with no new false alarms.
**Limitation:** the 7 false alarms were seen on this development set, so a pass here is an optimistic estimate; the held-out split in Phase 4 is the real test.
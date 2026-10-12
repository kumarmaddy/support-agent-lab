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


## Stage 2.1: Read prompt v4, legal-flag precision (2026-10-09)
**Problem (ADR-007 condition, risk R18):** with read prompt v3 the qwen2.5:7b reader flagged 7 development tickets as chargeback or legal threats that are not (duplicate or wrong charges, bank statements, requests to skip review): 7 of 115 out-of-scope tickets (6.1%) escalated unnecessarily.
**Change:** `read_ticket.v4.md` rewrites field 3 only: a threat must be the customer's own stated intention to take a named step; payment problems, refund requests, bank statements and instructions to skip review are listed as not threats. Category and deadline text unchanged from v3 (tested). The wording describes the rule and quotes no ticket text. The probe now reports legal flags caught, missed and falsely raised. Defaults changed (ADR-007): `DEFAULT_MODEL = qwen2.5:7b`, `DEFAULT_READ_PROMPT = v4` in `run.py`, used by `demo.py` and the probe; llama3.2:3b needs `--read-prompt v3`. 581 tests.
**Result (`docs/evidence/phase-2-read-prompt-v4.txt`):** acceptance test fixed before the run was passed by 7B: legal threats caught 4/4, false alarms 7 to 1, category agreement 138/150 (v3: 139), 0 failed readings, deadline dates 150/150. On 3B, v4 caught 4/4 with no false alarm, but three address-change tickets (T-000034, 83, 126) failed reading because the model wrote an invented deadline phrase ("Thursday"); the ticket-text check rejected it and each ticket went to a person. v3 stays for 3B.
**Limitation:** the false alarms were seen on this development set, so the gain is an optimistic estimate; the held-out split in Phase 4 is the real test. The remaining false alarm (T-000045) is a refund request telling the company to skip approval.
**Next:** full 7B evaluation with v4 (run, score, compare with run b2e156), then knowledge-base retrieval.


## Stage 2.1 (completed): full 7B run with read prompt v4 (2026-10-09)
**Run:** run-20261009-054209-fee598, qwen2.5:7b, read_ticket.v4, commit 3a660d14, clean tree, 150 tickets, 30.6 minutes. Evidence in `docs/evidence/phase-2-v4-full-run.txt`.
**Result:** legal-flag false alarms 7 to 1; Set B unnecessary escalations 7/115 (6.1%) to 1/115 (0.9%); legal threats found 4/4; Set A end to end 35/35 and Set B 115/115 handed to a person, both unchanged; category agreement 138/150 (v3: 139; p = 1.0); latency unchanged (Set A median 25.6 s). Six tickets moved from escalated to routed (duplicate-charge or skip-review refund requests).
**Documents:** evaluation report v1.1 (section 4.6), ADR-007 condition recorded as met, risk register v1.5 (R18).
**Carry-forward:** confirm on the held-out split in Phase 4; 3B stays on v3.
**Next:** stage 2.2, knowledge-base retrieval design.


## Stage 2.2: Phase 2 design and lexical retrieval baseline (2026-10-09)
**Built:** `docs/design/phase-2-design.md` v0.1; `src/kb/retrieve.py` (BM25 over title, key facts and details; internal guidance never indexed; deterministic; standard library only); `src/evaluation/retrieval.py` (hit@k, recall@k and reciprocal rank by category over the 145 development tickets that list required articles; refuses the held-out split). 589 tests (8 new). Baseline output: `docs/evidence/retrieval-baseline-bm25.txt`.
**Finding:** word matching on whole tickets gives hit@1 of 49% and hit@3 of 72% overall, 26% for order-status tickets (the right article follows from the order state, not the words) and 62% / 88% for knowledge questions (n = 8). Design consequence: articles for transactional tickets stay chosen by decision rules; retrieval serves knowledge questions only.
**Open decisions (design section 4):** probe set for knowledge questions, embedding comparison, "I don't know" threshold.
**Next:** stage 2.3, on approval of the decisions.


## Stage 2.3a: Knowledge-question probe set and embedding retrieval (2026-10-09)
**Built:** `data/probes/knowledge_questions.jsonl` (36 answerable knowledge questions covering all 21 articles and 12 questions the knowledge base cannot answer; written before any retrieval result was seen; kept apart from the frozen dataset); `src/kb/embed.py` (local embedding index through Ollama, cosine ranking, and a hybrid of two rankings by reciprocal rank fusion); `src/evaluation/retrieval.py` extended with `--probes`, `--method bm25|embed|hybrid` and a threshold table for the "I don't know" rule. 597 tests (8 new).
**BM25 on the probes (`docs/evidence/retrieval-probes-bm25.txt`):** hit@1 27/36 = 75% (59-86%); hit@3 32/36 = 89% (75-96%). A minimum-score rule at 3.07 still answers 8% of the unanswerable questions, and the one unanswerable question that gets a high score (down sourcing, 11.1) is matched to the sleeping-bag care article by the word "down".
**Limitation:** the probes were written by the same author as the system; each is reviewed by the project lead before use. Probe questions are not tickets, so no action or escalation is scored.
**Next:** run embed and hybrid on the probes and tickets, then ADR-009.


## Stage 2.3b: Retrieval comparison and ADR-009 (2026-10-09)
**Result (`docs/evidence/retrieval-embedding-hybrid-runs.txt`):** on 36 answerable probes BM25 ranks the right article first 75%, embeddings 83% (68-92%), hybrid 86%; top-3 89%, 97%, 94%. On the 8 knowledge-question tickets embeddings reach 100%. Embeddings against BM25 on the probes: 5 right only for embeddings, 2 only for BM25 (p = 0.45). Embedding scores separate unanswerable questions (highest 0.715; development tickets 0.54 to 0.61) far better than BM25; fused hybrid scores cannot carry a threshold.
**Decided (ADR-009, Proposed):** embeddings for knowledge questions, BM25 kept as baseline, no hybrid, no vector database. Design v0.2: "I don't know" uses three gates (score at least 0.65, model check that the article answers the question, validated cited reply).
**Limitations:** probes written by the system's author; threshold and method chosen on development data; embedding scores for all tickets are not meaningful for order-status tickets, where articles follow from the decision rules.
**Next:** stage 2.4, knowledge-question path in the pipeline.


## Stage 2.4: Knowledge-question path (2026-10-09)
**Built:** `src/agent/knowledge.py` (three gates: similarity score at least 0.65, a yes/no model check that the article's key facts answer the question, and a validated reply; failing any gate hands the ticket over); prompts `knowledge_check.v1` and `knowledge_reply.v1`; `validate_knowledge_reply` and `draft_knowledge_reply` (writer sees only the key facts; fallback is the key facts themselves; template passes the validator for all 21 articles); pipeline step `knowledge` behind `--knowledge`; run metadata records the embedding model, threshold and prompt hashes; `src/evaluation/knowledge.py` measures the path on the probe file. Probe labels widened for four duplicate-fact cases (design 4.1). 630 tests (33 new); six mutation checks each failed a test (one survivor found and covered).
**Not yet measured:** the path has been run only against scripted models. The probe run and the product_info tickets need the real models (stage 2.4 results).
**Next:** run `python -m src.evaluation.knowledge`, then fold product_info tickets into the scorer in stage 2.7.


### 2.4b Knowledge-path diagnostics and embedding digest

**Why.** The first stage 2.4 probe run answered 21 of 36 answerable probes (58%) with no wrong answers and 0 of 12 unanswerable probes answered. Eleven probes were handed over at the model check, eight of them with the correct article retrieved. The output could not distinguish a model "no" from a failed call.

**Changes.**
- `src/evaluation/knowledge.py`: per-probe check verdict (`yes`, `no`, `error:<code>`, `invalid`, `-`); `--check-only` (tests the check on the labelled article and on a retrieved non-answering article); `--show-replies N`; embedding digest in the header.
- `src/kb/embed.py`: `model_digest()` reads the model digest from Ollama.
- `src/agent/run.py`: records `embed_digest` in the run metadata (as ADR-009 states).
- Tests added for the verdicts, check-only mode, reply display and digest lookup. Suite: 634 passed.

**No change** to gates, thresholds or prompts. Those are adjusted only after the diagnostic output is reviewed.


### 2.4d Knowledge check prompt comparison (v1 vs v2)

**Why.** The v1 check handed over 11 answerable probes with the correct article retrieved. Diagnostics showed genuine "no" verdicts, not failed calls.

**What.** Added check prompt v2 (an agent could answer from the facts alone, including by applying a stated rule or number) and a `--check-prompt` option on the run and evaluation commands. Evidence: `docs/evidence/knowledge-check-prompt-runs.txt`.

**Result.** Coverage 58% (v1) vs 64% (v2); the difference is within noise (3 gained, 1 lost). Wrong answers 0 and unanswerable answered 0 under both. The v2 false-yes rate on non-answering articles rose from 1/48 to 4/48.

**Decision.** v1 remains the default. v2 is kept as a documented alternative. The check is the main coverage limit; eight answerable probes with the right article are handed over under both prompts. Further prompt tuning on the 36 development probes is not pursued, to avoid fitting to them. Thresholds and the check prompt are confirmed once in Phase 4 on held-out data.

### 2.5a Cancellations and address changes

**Scope.** Scenarios S13-S16 (23 development tickets) plus the S24 cancellation. Opt-in with `--transactions`; the default is unchanged (Phase 1 behaviour and tests are intact).


**Changes.**
- `decide.py`: scope sets (`PHASE1_SCOPE`, `TRANSACTION_SCOPE`); actions `propose_cancellation`, `propose_address_change`, `decline_policy`; rules for cancellation and address change by order state.
- `transactions.py` and `extract_address.v1.md`: copies the new address from the ticket and accepts it only if it is verified (word for word in the ticket, character set, length).
- `reply.py`: code-written reply bodies for the new reasons (no model wording); `address_missing` request.
- `pipeline.py`, `run.py`: the extra step and the `--transactions` switch; the prompt hash is recorded in `run.json`.
- `score.py`, `slice.py`: scope follows the run; exact address comparison; proposals out of scope count as wrongly answered.
- ADR-009 accepted; `phase-2-design.md` v0.4 (section 5a).

**Tests.** 674 passed (40 new). A perfect reader and scripted address extractor reproduce every labelled action, article and fact for the 24 tickets. Four mutations of the new rules (state check, address verification, proposal action, digit rule) were each caught.

**Not yet measured.** Results with the real models (read step on cancellation and address-change tickets, address copying by qwen2.5:7b).


### 2.5a2 First transactions run and one fix

**Run.** run-20261009-110812-2e6e35 (qwen2.5:7b, read prompt v4, `--transactions`, 150 tickets). Set A (59 tickets: 35 order status + 24 transactional) 59/59 on action, escalation, article, facts and end to end; all six proposed addresses were copied exactly. Set B 90/91 handed to a person. The 35 order-status tickets and the 11 must-escalate routings are unchanged from Phase 1.

**Finding.** T-000145 (S19, "Can I change my delivery address after I place an order?") was read as address_change. The customer has no open order, so the order-number request had no orders to list and the model invented two (ORDER12345, ORDER67890); the validator only recognised the O-nnnnnn format. 

**Fix.** A customer with no open order is asked for the number without any order being named (`no_open_orders`); order-like references in other shapes (ORDER12345, #12345) now fail `unknown_order`. 683 tests pass.

**Open.** Category agreement is 92% (12 misreads, mostly "other" tickets read as product_info, which go to a person). Misreads that land in a handled category (here T-000145) are the new exposure of widening the scope; the Phase 2 evaluation measures it.


### 2.5b Returns, exchanges and replacements

**Scope.** 32 development tickets (S05, S06, S07, S08, the replacement half of S11, and the S24 return). Part of `--transactions`.

**Changes.**
- `read_request.v1.md`, `transactions.py`: reads the kind of request, the product phrase and the requested size; code verifies each against the ticket; the product is matched to the order's own product names.
- `tools.py`: order lines carry the final-sale flag (read-only query).
- `decide.py`: the window (day 30 in, day 31 out, counted to the day the request was received), final-sale, exchange and replacement rules; actions `propose_return_label`, `propose_exchange`, `propose_replacement`.
- `reply.py`: code-written replies; `pipeline.py`, `run.py`: the extra step; the prompt hash is recorded in `run.json`.
- `score.py`, `slice.py`: scope and fact checks for returns.

**Finding.** The dataset counts delivery days to its snapshot date; the agent counts to the day the request was received, as KB-RET-01 words it. One development ticket (T-000091) falls on different sides of the boundary and is reported as a miss.

**Tests.** 734 passed (51 new). A perfect reader reproduces every labelled action, article and fact for 31 of the 32 tickets; the 32nd is the boundary ticket above, which has its own test. Seven mutations of the new rules (window boundary, final sale, same-size exchange, no-item rule, window check, item-match margin, item-in-ticket check) were each caught.

**Not yet measured.** Results with the real models.


### 2.5b2 First returns run and one fix

**Run.** run-20261010-104437-ad6bf3 (qwen2.5:7b, `--transactions`, 150 tickets). Set A 91 tickets (35 order status, 24 cancellation and address change, 32 return and exchange): 89/91 end to end (97.8%, 92-99%). Set B: 57/59 handed to a person. All 6 exchange sizes and 6 addresses were copied exactly; request kind agreed with the scenario for 31 of 32. Evidence: `docs/evidence/phase-2-transactions-run-ad6bf3.txt`.

**Misses.** T-000091 is the documented boundary difference (policy day 30, dataset day 31). T-000082 is a prompt-injection ticket the model read as a refund request, so it went to a person. T-000037 and T-000145 are general policy questions read as transactions.

**Fix.** For the last two, the reply was written by the model and claimed the customer had mentioned an order number, which was untrue. The `no_open_orders` reply is now written by code. 735 tests pass.

**Open.** A general question read as a transaction category when no order is named (stage 2.7). Refunds are stage 2.5c.


### 2.5c Refunds

**Built.** Refund tickets under `--transactions`: a read-only `get_payment_records` tool (payments, refunds, returns; no card digits), a small model call that reports the topic (status, duplicate charge, damaged or wrong item), and decision rules that check that topic against the records. Refund status is reported from the refund record (pending only inside the 7-day period of KB-REF-01). A duplicate charge becomes `propose_refund` of the recorded duplicate payment, or goes to a person if the ticket's amount disagrees with the record. A damaged or wrong item becomes `propose_refund` with no amount when it is within 30 days of delivery. Every proposal carries `approval_required` and says a colleague must approve it. Replies are written by code.

**Scope in scoring.** 26 development tickets (S09, S10, S11, S23, S24, S26 refund tickets). S21 legal threats stay out until the Phase 3 policy engine.

**Checks.** 792 tests pass. 18 deliberate breakages of the rules, the tool's ownership check, the template-only rule and the scorer were each caught by a test.

**Open.** First run on the 7B model is pending. Whether a general question read as a refund reaches the knowledge path is decided in 2.7.


### 2.5c2 First refunds run and a fix to the run comparison

**Run.** run-20261010-125618-28fad8 (qwen2.5:7b, `--transactions`, 150 tickets). Set A 117 tickets (the 91 from 2.5b plus 26 refund tickets): 114/117 end to end (97.4%, 93-99%). Of the 26 refund tickets, 25 were fully right: refund status 6/6, duplicate charges 15/16 (the miss is T-000045), damaged or wrong item 4/4. Set B: 31/33 handed to a person. No refund reply stated an amount that was not in the payment or refund record. Evidence: `docs/evidence/phase-2-refunds-run-28fad8.txt`.

**Misses.** T-000045: the reader flagged "your manager already agreed" as a legal threat, so the ticket went to a senior person (safe, but a miss). T-000082: injection ticket handed to a person. T-000091: documented boundary difference. T-000037 and T-000145: general policy questions read as transactions (decided in 2.7).

**Fix.** `compare` stopped with a KeyError when the two runs had a different scope (here 26 more tickets in scope). It now compares a ticket only if both runs put it in the same set and reports how many were not compared. 793 tests pass.


### 2.6 Hand-over note

**Built.** Each escalation, route to a person, and proposal now carries a note built by code (`src/agent/handover.py`): why the agent stopped, the records it checked, whether approval is required, a suggested next step from the policy, and the queue (senior for escalations). It holds no ticket text and no email address. For a legal threat, which is escalated before any lookup, one read-only lookup afterwards adds the order's status and shipment to the note (KB-REF-04 asks for them). The scorer counts notes present and notes that name the labelled order.

**Checks.** 804 tests pass (11 new). 12 deliberate breakages (reasons without an explanation, wrong queue, lost approval flag, missing lookup, note not written, wrong amount, scorer shortcuts) were each caught; one gap found (the identified order missing from the note) and closed.

**Open.** First run to measure notes on the 7B model, and a blind read of a sample of notes, in 2.7.


### 2.6b First run with notes, and one improvement

**Run.** run-20261010-141612-d0d271 (qwen2.5:7b, `--transactions`, clean tree at 2a1dc16). Actions and scores are unchanged from the refunds run. Notes: 90 needed, 90 present, 67 of 67 name the labelled order, none holds an email address. Evidence: `docs/evidence/phase-2-handover-run-d0d271.txt`.

**Found by reading.** The note for a refund ticket escalated as a legal threat (T-000015) showed the order but not the refund. Such notes now also show the refund and any duplicate payment from the records (one extra read-only lookup, used only for the note). Every note now says what the ticket was read as. 807 tests pass; four deliberate breakages were each caught.

**Also.** `tests/agent/test_pipeline.py` had been dropped from the 2.6 commit and was restored from git; the suite is 807 tests.


### 2.7a Scoring knowledge answers, and the "knowledge first" option

**Built.** The scorer counts knowledge answers and checks the cited article (valid: exists; correct: the labelled article). `--knowledge-first` (with `--knowledge`) tries the knowledge path first for a cancellation, address-change, return or refund ticket that names no order and carries no legal flag; a failed first try falls through to the normal path. The product_info tickets join the in-scope set when the knowledge path is on.

**Finding.** Every transactional development ticket names an order, so the option can only affect tickets the reader has misfiled (T-000037, T-000042, T-000145). The comparison of the two runs is therefore a test of the mechanism on three tickets, and is reported as such.

**Tests.** 816 tests pass (9 new). Seven mutations of the new rules (named-order condition, order-status exclusion, fall-through, legal exclusion, citation existence, citation correctness, scope) each fail a test.

**Next.** Two combined runs (`--knowledge --transactions` with and without `--knowledge-first`), scored and compared.


2.7a result. Runs 21c7b5 (--knowledge --transactions) and 946853 (adds --knowledge-first). Knowledge-first answered two misfiled policy questions (T-000042, T-000145) with the correct article, answered no transactional ticket from the knowledge base, and changed no other result (action 116→118 of 125; p = 0.50, two tickets). Decision: use --knowledge-first with --knowledge. Remaining policy-question misses: T-000016, T-000037, T-000038, T-000143.


2.7b result. Run 9659c5 (llama3.2:3b, read v3, --knowledge --knowledge-first --transactions) vs 946853 (qwen2.5:7b, read v4). Set A end to end 114/125 vs 118/125 (p = 0.289); facts 116 vs 123 (p = 0.016, 7B better). Set B 25/25 handed over and 0 wrongly answered for both. Knowledge answers 6/6 vs 4/4 with correct citations. Template fallbacks 11/35 vs 3/35. Median latency 6.9 s vs 13.9 s. ADR-007 stands.


### 2.7c Blind review tooling (replies and hand-over notes)

**Built.** `review_notes` (make / rate / report): a seeded sample of hand-over notes spread over the actions, shown with the ticket and no labels; three questions per note; resumable; Wilson intervals; follow-up list. The Phase 1 reply review now also shows key facts for knowledge answers. 823 tests pass (16 new); six mutations of the new rules each fail a test (one by never finishing, which the timeout catches).

**Next.** A template-only run, the reply review (model vs template) and the note review on the 7B run, then the Phase 2 evaluation report and the exit review.


### 2.7c Blind review tooling (cases across all categories)

**Why.** The pairwise reply review only reaches replies written by the model, which are almost all order-status replies and knowledge answers; replies for the other categories are templates and have nothing to be paired with.

**Built.** `review_notes` (make / rate / report): a seeded sample of cases spread over the actions that carry a note, so every category is covered. Each case shows the ticket, the reply the customer would get and the hand-over note, with no labels. Four questions per case; resumable; Wilson intervals; follow-up list. The pairwise review also shows key facts for knowledge answers. 824 tests pass; mutations of the new rules each fail a test.

**Next.** A template-only run, the pairwise reply review and the case review on the 7B run, then the Phase 2 evaluation report and the exit review.


### 2.7c Blind review results (7B run 946853), and one fix

**Case review** (`dev-7b-cases`, 30 cases spread over eight actions, one reviewer). Could act on the note without opening anything else: yes 28/30 (95% interval 79-98%), partly 1, no 1. Reply wrong or inappropriate: 1/30. Something wrong in a note: 0/30. Something missing: 0/30. Every action group rated "yes" in full except replacement (3/4) and return label (2/3).

**Follow-ups.** T-000070: the note did not say whether the item is final sale, which the return depends on. T-000066: the ticket did not identify the item and the note did not list the items on the order. Both fixed in the note builder: a return, exchange, replacement or item-refund note now lists the order's items when none was identified, and a return or exchange note states the final-sale check, read from the order's records. T-000014: reply flagged without comment (see the follow-up in the conversation).

**Tests.** 830 tests pass (6 new); mutations of the new lines each fail a test.

**Limits.** One reviewer who also wrote the project; 30 cases; replies and notes judged on the development set only. The fix was checked by tests and by the dev tickets, not by a second review.


### 2.7c Blind review results (7B run 946853), and one fix

**Case review** (`dev-7b-cases`, 30 cases spread over eight actions, one reviewer). Could act on the note without opening anything else: yes 28/30 (95% interval 79-98%), partly 1, no 1. Reply wrong or inappropriate: 1/30. Something wrong in a note: 0/30. Something missing: 0/30. Every action group rated "yes" in full except replacement (3/4) and return label (2/3).

**Follow-ups.** T-000070: the note did not say whether the item is final sale, which the return depends on. T-000066: the ticket did not identify the item and the note did not list the items on the order. Both fixed in the note builder: a return, exchange, replacement or item-refund note now lists the order's items when none was identified, and a return or exchange note states the final-sale check, read from the order's records. T-000014: reply flagged without comment (see the follow-up in the conversation).

**Tests.** 830 tests pass (6 new); mutations of the new lines each fail a test.

**Limits.** One reviewer who also wrote the project; 30 cases; replies and notes judged on the development set only. The fix was checked by tests and by the dev tickets, not by a second review.

**Amended rating.** The reviewer reported a typing slip in one rating (the answer entered was not the one intended). The tool had no way to correct it, so `review_notes amend --ticket` was added: it asks the four questions again and appends the new rating; the report uses the latest rating, and the original line stays in `ratings.jsonl` as the record. The rating was amended after the reviewer had seen a reading of the case in conversation, which is disclosed here. The same change fixed the tool not asking for a comment when only the reply was flagged. 833 tests pass.


### 3.1 Phase 3 design

**Written.** `docs/design/phase-3-design.md` v0.1: policy engine with rules in configuration (fail closed to approval), must-escalate rules for the 11 only-routed tickets, audit log with redaction, Actions server with idempotency keys and a sandbox ledger, approval web page, read-only MCP adapter, injection and misuse suite, nine stages.

**Decided with the project lead.** Approval is always required in v1 (auto-execute exists in config and is tested, shipped off). The approval service is a local web page. Writes never touch the frozen development database.

**Open.** Senior-approval refund threshold (default $250, to be justified in 3.2); MCP SDK check on Python 3.13 and Windows (3.5).


### 3.2 Policy engine

**Built.** `src/agent/policy.py` (pure `evaluate(request, policy)`, validating loader), `config/policy.toml` (three initial rules, auto-execute switch off), a read-only tool `count_refunds`, and the wiring: a `policy` step after `decide` for every proposal, `policy_denied` hand-over reason, senior queue on the note, rule id and outcome in the note, the trace and `run.json` (policy version, sha256, rule ids). `run.py` loads `config/policy.toml` by default (`--policy PATH` to change, `--no-policy` for the Phase 2 behaviour) and refuses to start on a policy it cannot read.

**Verified.** 891 tests pass (833 before; 58 new). 33 mutations of the engine and its wiring were applied; 29 were caught at the first attempt. Of the 4 survivors, two were closed with tests (payment amount in the request; a denied action never worded by the model), and two are equivalent mutants today and are disclosed: the legal flag is always false at a proposal because a legal threat is escalated before any proposal, and the "already refunded" flag is always false for a duplicate because `decide` hands over an already-refunded duplicate first. Both are checked directly in the engine tests, and become reachable when the flag arrives in 3.3 and when the actions server (3.5) calls the engine on its own.

**Result on the development tickets** (oracle reading, template replies): of 48 proposals, 47 get `DEFAULT-APPROVAL` and 1 (T-000149, a duplicate-charge refund of $269.99) gets `APPROVE-REFUND-SENIOR` in the senior queue. No proposal is denied, as expected.

**Decided.** The senior-approval threshold stays at $250 as a documented assumption (basis in phase-3-design.md section 5.1); Support Operations owns the final value.

**Open.** A 7B run to show the decision and rule id on each proposal in the real pipeline (project lead). Must-escalate rules and the compromise flag are stage 3.3.


### 3.2 Policy engine

**Built.** `src/agent/policy.py` (pure `evaluate(request, policy)`, validating loader), `config/policy.toml` (three initial rules, auto-execute switch off), a read-only tool `count_refunds`, and the wiring: a `policy` step after `decide` for every proposal, `policy_denied` hand-over reason, senior queue on the note, rule id and outcome in the note, the trace and `run.json` (policy version, sha256, rule ids). `run.py` loads `config/policy.toml` by default (`--policy PATH` to change, `--no-policy` for the Phase 2 behaviour) and refuses to start on a policy it cannot read.

**Verified.** 892 tests pass (833 before; 59 new). 33 mutations of the engine and its wiring were applied; 29 were caught at the first attempt. Of the 4 survivors, two were closed with tests (payment amount in the request; a denied action never worded by the model), and two are equivalent mutants today and are disclosed: the legal flag is always false at a proposal because a legal threat is escalated before any proposal, and the "already refunded" flag is always false for a duplicate because `decide` hands over an already-refunded duplicate first. Both are checked directly in the engine tests, and become reachable when the flag arrives in 3.3 and when the actions server (3.5) calls the engine on its own.

**Result on the development tickets** (oracle reading, template replies): of 48 proposals, 47 get `DEFAULT-APPROVAL` and 1 (T-000149, a duplicate-charge refund of $269.99) gets `APPROVE-REFUND-SENIOR` in the senior queue. No proposal is denied, as expected.

**Run on the development data** (7B, run-20261011-114847-7c713c, 40 tickets): 13 proposals, all with a policy decision, all `DEFAULT-APPROVAL` in the standard queue; policy sha256 `00ab0acc…44513ca` in `run.json` and in every decision; no denials. The senior rule is covered by tests and by a run on T-000149, T-000041 and T-000025 (the three duplicate payments of $250 or more; see the run recorded below).

**Found while checking.** An ids file written by Windows PowerShell's `-Encoding utf8` starts with a byte-order mark, which made the first id unreadable (`ticket_not_found`). `run.py` now reads ids files with `utf-8-sig`; one test added.

**Decided.** The senior-approval threshold stays at $250 as a documented assumption (basis in phase-3-design.md section 5.1); Support Operations owns the final value.

**Open.** A 7B run to show the decision and rule id on each proposal in the real pipeline (project lead). Must-escalate rules and the compromise flag are stage 3.3.


### 3.2 Policy engine

**Built.** `src/agent/policy.py` (pure `evaluate(request, policy)`, validating loader), `config/policy.toml` (three initial rules, auto-execute switch off), a read-only tool `count_refunds`, and the wiring: a `policy` step after `decide` for every proposal, `policy_denied` hand-over reason, senior queue on the note, rule id and outcome in the note, the trace and `run.json` (policy version, sha256, rule ids). `run.py` loads `config/policy.toml` by default (`--policy PATH` to change, `--no-policy` for the Phase 2 behaviour) and refuses to start on a policy it cannot read.

**Verified.** 892 tests pass (833 before; 59 new). 33 mutations of the engine and its wiring were applied; 29 were caught at the first attempt. Of the 4 survivors, two were closed with tests (payment amount in the request; a denied action never worded by the model), and two are equivalent mutants today and are disclosed: the legal flag is always false at a proposal because a legal threat is escalated before any proposal, and the "already refunded" flag is always false for a duplicate because `decide` hands over an already-refunded duplicate first. Both are checked directly in the engine tests, and become reachable when the flag arrives in 3.3 and when the actions server (3.5) calls the engine on its own.

**Result on the development tickets** (oracle reading, template replies): in the 150-ticket development data with the oracle reading, 48 proposals: 47 get `DEFAULT-APPROVAL` and 1 (T-000149) gets `APPROVE-REFUND-SENIOR`. No proposal is denied, as expected.

**Run on the development data** (7B, run-20261011-114847-7c713c, 40 tickets): 13 proposals, all with a policy decision, all `DEFAULT-APPROVAL` in the standard queue; policy sha256 `00ab0acc…44513ca` in `run.json` and in every decision; no denials. The senior rule was shown on run-20261011-122849-23824b (policy sha256 `37e223c0…`, the corrected file): T-000149, a duplicate-charge refund of $269.99, was routed by `APPROVE-REFUND-SENIOR` to the senior queue (evidence: the amount used was 26999 cents; the note shows queue senior and the rule id), and T-000029 by `DEFAULT-APPROVAL` to the standard queue. Tickets that are not proposals (T-000041 routed, T-000025 answered) carry no policy block. The evidence field holds the request value each condition used, not the threshold.

**Found while checking.** An ids file written by Windows PowerShell's `-Encoding utf8` starts with a byte-order mark, which made the first id unreadable (`ticket_not_found`). `run.py` now reads ids files with `utf-8-sig`; one test added.

**Decided.** The senior-approval threshold stays at $250 as a documented assumption (basis in phase-3-design.md section 5.1); Support Operations owns the final value.

**Open.** Nothing blocks the stage. Must-escalate rules and the compromise flag are stage 3.3.


### 3.3 Must-escalate rules

**Acceptance first.** `docs/project/stage-3.3-acceptance.md` was written before any run: ten criteria for the 7B model (compromise flag 5 of 5 with at most 2 false alarms; category agreement within 2 of 138; S20 5 of 5; S25 4 of 4; at most 2 new unnecessary escalations; at least 20 of 22 labelled must-escalate tickets end as escalations; no regression in Set A or Set B), a reduced set for 3B, and one allowed prompt revision, disclosed whatever the outcome.

**Built.** Read prompt v5 and the four-field schema (`account_compromise_suspected`); the decision `account_compromise_suspected` (senior queue, KB-ACC-03, template reply that promises nothing); `knowledge_not_found` escalated instead of routed; an out-of-scope `other` ticket that names someone else's order escalated as `order_not_owned`; policy condition `compromise_flag` and rule `DENY-ACTION-ON-COMPROMISED-ACCOUNT`; scorer additions (compromise flag counts, escalation recall and precision over all tickets). `READ` token cap raised from 80 to 110 for the longer answer.

**Verified.** 913 tests pass (892 before; 21 new, 1 updated for the `knowledge_not_found` change). With a perfect reader on the development data: all 5 S18 tickets, all 5 S20 tickets (given a weak knowledge match) and all 4 S25 tickets escalate, and no other ticket is flagged. 25 mutations applied, 24 caught; the survivor passes the compromise flag into the policy request, which cannot change a result today because a flagged ticket is escalated before any proposal (the engine rule is tested directly).

**Not yet measured.** Everything above uses a perfect reader. Whether the 7B and 3B models flag S18 tickets and avoid false alarms is exactly what the acceptance run measures.

**Decided / to confirm.** Knowledge gaps go to the senior queue (FR-10 as the project reads it); Support Operations to confirm.


### 3.3 Must-escalate rules

**Acceptance first.** `docs/project/stage-3.3-acceptance.md` was written before any run: ten criteria for the 7B, a reduced gating set for the 3B, and one allowed prompt revision.

**Built.** Read prompt v5 and the four-field schema (`account_compromise_suspected`); the decision `account_compromise_suspected` (senior queue, KB-ACC-03, template reply that promises nothing); `knowledge_not_found` escalated instead of routed; an out-of-scope `other` ticket naming someone else's order escalated as `order_not_owned`; policy condition `compromise_flag` and rule `DENY-ACTION-ON-COMPROMISED-ACCOUNT`; scorer additions (compromise flag counts; escalation recall and precision over all tickets). Read token cap 80 to 110. Read prompt v6 (v3 plus the same field) for the 3B.

**Verified.** 914 tests pass (892 before). 25 mutations of the new code were applied, 24 caught; the survivor passes the compromise flag into the policy request, which cannot change a result today because a flagged ticket is escalated before any proposal (the engine rule is tested directly). The deny rules of stage 3.2 are equivalent mutants for the same reason.

**Measured** (`stage-3.3-results.md`, evidence in `docs/evidence/stage-3.3-runs.txt`). 7B with v5: all ten criteria met; compromise flag 5 of 5 with no false alarms; escalation recall 11/22 to 22/22; Set A 119/125; Set B 0 wrongly answered. 3B: v5 failed (5 invalid readings, Set A 109); v6, the one allowed revision, meets four of five gating criteria and misses category agreement by one ticket (134 against a floor of 135); escalation recall 11/22 to 21/22. T-000087 is still only routed on the 3B (it does not read the ticket as category `other`).

**Decided.** ADR-011: v5 for the 7B, v6 for the 3B; the miss is recorded as a miss. Knowledge gaps go to the senior queue (FR-10 as the project reads it); Support Operations to confirm.

**Also changed.** The default read prompt in `run.py` is now v5 (the 3B needs `--read-prompt v6`).


### 3.4 Audit log and redaction

**Built.** `src/audit/redact.py` (key rules plus patterns for email, card, phone, street address and greeting name, with a broader post-check), `src/audit/log.py` (hash-chained append-only JSONL, lock file, fsync, `verify`, `query`, `record_resolution`), `src/audit/__main__.py` (`--ticket`, `--verify`, `--head`, `--json`). `run.py` gained `--audit PATH` (default `data/audit/audit.jsonl`) and `--no-audit`, and writes `audit_head.json` into the run directory. Each ticket produces `policy_decision` (proposals only), `decision` and `hand_over` (when a note exists).

**Verified.** 959 tests pass (914 before; 45 new). Ten mutations of the new code were applied, nine caught. The survivor removes the sequence-number check in `verify`; it is redundant because a removed line is also caught by the broken `prev` link and the sequence number is inside the hash. Kept as defence in depth.

**Leak test.** Runs the pipeline over all 150 development tickets and requires that no customer email, full name, street line or requested address from the data appears in the audit file, that no greeting carries a first name, and that the broad post-check finds nothing.

**Disclosed limits.** (1) Run traces keep raw synthetic values because the scorer compares them; real data would need a trace redaction layer. (2) The chain does not detect deletion from the end unless the head is noted (`--head`), and it is not proof against a full rewrite. (3) Pattern redaction is tested on the development data only; Phase 4 held-out data is the second test.

**Operational.** Add `data/audit/` to `.gitignore`.


### 3.5 Actions server

**Built.** `src/actions/` (config, sandbox, approvals, service, MCP server, `python -m src.actions init|ledger`), `config/actions.toml` (all tools off), ADR-012. Four write tools (`cancel`, `change_address`, `refund`, `replace`), each behind: switch on, matching approved approval, state check, policy rules again, idempotency key and ledger in one transaction. Every attempt is an `execution` audit event; approvals and rejections are `approval` / `rejection` events.

**Verified.** 1007 tests pass (959 before; 48 new, of which 5 skip without the MCP SDK). 19 mutations of the new code were applied; the first run left 4 survivors (refunded status ignored, no service lock, partial refund marks payment refunded, MCP tool ignores the approval id). Four tests were added and all 19 are now caught. The frozen development database has the same sha256 before and after every test that writes.

**Found on Windows.** The first Windows run (Python 3.13, MCP SDK 2.3.0) passed all MCP tests; one test failed because Windows refuses to delete a database file that a connection still has open. The test now closes the connection first, and `create_sandbox --force` reports "in use by another process" instead of a raw PermissionError.

**Found by testing.** The MCP SDK runs synchronous tools in a worker thread; a SQLite connection created in the main thread raised `ProgrammingError`. The sandbox connection now allows cross-thread use and the service serialises it with a lock.

**Disclosed limits.** No approver authentication yet (3.6 is a local single-user page); addresses must read `street, city 12345`; `return_label` and `exchange` have no write tool; the sandbox records intended effects only; Windows confirmation of MCP SDK 2.x rests on the project lead's run.

**Operational.** `pip install mcp`; `data/sandbox/` is generated, add it to `.gitignore`.


### 3.6 Approval service

**Built.** `src/approval/` (queue, pages, app, command-line launcher), a one-line extension to `ApprovalStore` (`once=True`: refuse a second decision inside the transaction), ADR-013. A local standard-library page lists a run's proposals (senior first), shows reason, records, ticket text, draft reply, rule and the exact effect, and takes Approve, Approve with my change, Reject (reason required). Execute is a separate step through the actions service. Approvals are re-checked by the policy engine with the entered values; a standard approver cannot decide senior-queue items; edits go to `data/edits/edits.jsonl` and the audit log.

**Verified.** 1054 tests pass (1007 before; 47 new). 20 mutations of the new code were applied; the first run left 2 survivors, both the "senior role not enforced at the top of the decision" check, which was redundant for T-000149 because the re-evaluated policy also says senior. A test where the policy has since changed (recorded queue senior, current policy silent) was added; all 20 are caught. Rendering was inspected in Chromium (light, dark, phone width).

**Found by testing.** Approve must not require the form to echo the proposed amount or address; an absent field now means "as proposed" (an empty amount is still refused).

**Disclosed limits.** No login (name and role fixed at start; single-user local tool); the edits file holds raw values; return-label and exchange proposals are listed as manual; one run per server start.

**Operational.** Add `data/edits/` to `.gitignore`.


### 3.6 Approval service

**Built.** `src/approval/` (queue, pages, app, command-line launcher), a one-line extension to `ApprovalStore` (`once=True`: refuse a second decision inside the transaction), ADR-013. A local standard-library page lists a run's proposals (senior first), shows reason, records, ticket text, draft reply, rule and the exact effect, and takes Approve, Approve with my change, Reject (reason required). Execute is a separate step through the actions service. Approvals are re-checked by the policy engine with the entered values; a standard approver cannot decide senior-queue items; edits go to `data/edits/edits.jsonl` and the audit log.

**Verified.** 1062 tests pass (1007 before; 55 new). 21 mutations of the new code were applied; the first run left 2 survivors, both the "senior role not enforced at the top of the decision" check, which was redundant for T-000149 because the re-evaluated policy also says senior. A test where the policy has since changed (recorded queue senior, current policy silent) was added; all 21 are caught. Rendering was inspected in Chromium (light, dark, phone width).

**Found by testing.** Approve must not require the form to echo the proposed amount or address; an absent field now means "as proposed" (an empty amount is still refused).

**Found in the walk-through.** Posting from the editor's built-in browser pane was refused as "another site": the first version compared the Origin header with the page's own address, and an embedded browser can report a different Origin. The check now uses Fetch Metadata (`Sec-Fetch-Site`) when the browser sends it, with the Origin comparison as the fallback, and the refusal page states which values it saw. The per-start token, Host check and loopback binding are unchanged.

**Disclosed limits.** No login (name and role fixed at start; single-user local tool); the edits file holds raw values; return-label and exchange proposals are listed as manual; one run per server start.

**Operational.** Add `data/edits/` to `.gitignore`.


### 3.7 Read-only MCP adapter

**Built.** `src/readtools/` (adapter and `python -m src.readtools` over stdio), a `tool_read` event type in the audit log, ADR-014. The adapter publishes `get_ticket`, `find_customer`, `list_open_orders`, `get_order` and `get_payment_records` using the schemas and the `call` method of `Toolbox`; `count_refunds` and any other name return `unknown_tool`. Reads can be audited (tool, identifiers, status; never the result).

**Verified.** 1094 tests pass (1062 before; 32 new). 15 tests of `tests/agent/test_tools.py` run UNCHANGED through an MCP client and a real MCP server. 11 mutations of the adapter were applied and all were caught. A separate test starts the command as its own process and talks to it over stdio.

**Decided.** The low-level `Server` rather than the decorator API, so that argument checking stays the Toolbox's (ADR-014). One assertion of the existing tests differs in kind over MCP: a non-object `arguments` is refused by the protocol layer, not by the Toolbox (design 5.6).

**Disclosed limits.** The tools return the sender's email and the customer's name to any connected host; stdio only, no authentication; the development database only.

**Operational.** None (the `mcp` package is already required for the actions server).


### 3.7 Read-only MCP adapter

**Built.** `src/readtools/` (adapter and `python -m src.readtools` over stdio), a `tool_read` event type in the audit log, ADR-014. The adapter publishes `get_ticket`, `find_customer`, `list_open_orders`, `get_order` and `get_payment_records` using the schemas and the `call` method of `Toolbox`; `count_refunds` and any other name return `unknown_tool`. Reads can be audited (tool, identifiers, status; never the result).

**Verified.** 1095 tests pass (1062 before; 33 new). 15 tests of `tests/agent/test_tools.py` run UNCHANGED through an MCP client and a real MCP server. 11 mutations of the adapter were applied and all were caught. A separate test starts the command as its own process and talks to it over stdio.

**Decided.** The low-level `Server` rather than the decorator API, so that argument checking stays the Toolbox's (ADR-014). One assertion of the existing tests differs in kind over MCP: a non-object `arguments` is refused by the protocol layer, not by the Toolbox (design 5.6).

**Found on Windows.** Started by hand, the server waits silently for a host, and Ctrl+C printed a long traceback. Ctrl+C now stops it with a one-line "stopped".

**Disclosed limits.** The tools return the sender's email and the customer's name to any connected host; stdio only, no authentication; the development database only.

**Operational.** None (the `mcp` package is already required for the actions server).


### 3.8 Injection and misuse suite

**Built.** `src/security/` (cases, a throw-away world per case, a worst-case model stand-in, a runner, an independent scorer and `python -m src.security`), `data/security/cases.jsonl` (116 cases: 105 attacks, 11 controls), `src/agent/backstop.py` and ADR-015.

**Acceptance criteria** (from design 5.7, fixed before the first run): at least 60 cases kept apart from the frozen dataset; every seeded attack neutralised (charter O6, target 100%); wrong consequential actions 0 (O2); unapproved write actions 0; every control (a legitimate use) still works; a failure is fixed in the code and the suite re-run, never removed or loosened to pass.

**How the suite works.** Five layers are attacked: the pipeline with a model that does exactly what the ticket tells it (a worst case, not a live model), the actions service (direct and over MCP), the approval page (as HTTP requests), and the read-only tools. Each case runs in its own copy of the development database and its own sandbox, so no case can affect another and the frozen data is never touched. The scorer judges from what was observed (database rows, approvals, the ledger, HTTP responses, the reply text), not from what the code intended. An unapproved write is a change to business data that no approved, matching approval explains. A wrong action is a proposal for an order the sender does not own or with an amount that is not the recorded one, or an execution that does not match its approval. The 11 controls are legitimate uses (a real cancellation, a real duplicate charge, an approve-and-execute); they prove that a suite which refuses everything cannot pass.

**Verified.** 1134 tests pass (1095 before; 39 new). Run on the Linux workspace: 105 of 105 attacks neutralised (95% Wilson interval 96.5% to 100%), 0 wrong actions, 0 unapproved writes, 11 of 11 controls as expected. The Windows run is the project lead's exit evidence. 33 mutations of the code under test: 31 caught by the suite. Two survived and are explained: the page checks the senior queue twice (the queue recorded in the run, and the queue recomputed from the edited values); removing only the second check changes nothing on the development data because the first catches the same cases, and removing both is caught. The second survivor builds the cancel statement from text; the order id is validated by pattern before it is used, so the change is not observable (the mutation where text does reach SQL, the address insert, is caught). A further 10 mutations of the scorer, runner and backstop: all caught; two survived at first and led to two new tests.

**Found, and fixed.** The first run failed two attacks: injected text asking the reader to leave out the legal flag or the compromise flag worked, and a refund proposal went to the standard queue instead of the senior queue. Fix: a word-level backstop that can raise the two flags and never clears them (ADR-015). It changes no existing result: the 1095 earlier tests pass unchanged and, on the development tickets, it flags only tickets that are labelled as threats or compromises.

**Corrected after the first run, in the open.** Six case expectations were wrong about intended behaviour and were corrected, not loosened: three attacks that state a different refund amount expected a refund proposal, but the pipeline correctly routes them to a person (`duplicate_amount_differs`), which is stricter; three proposals were checked for an `approval_required` field that cancellations and address changes do not carry, so the check now reads the policy outcome (`require_approval`), which is what governs. The case file is pinned by count and hash in the tests.

**Charter numbering.** Design 5.7 and the implementation plan call this objective O7. In the charter, resistance to hostile input is O6 and O7 is time and cost per ticket. The suite reports O6; the design is corrected in v0.9.

**Disclosed limits.**
- The suite is written by the project's author and uses a scripted worst-case model. Whether a live 7B or 3B model can be talked into a different reading is measured by the evaluation runs, not here (phase 1 evidence under R9: the 3B followed an injected instruction twice; the effect was bounded).
- The backstop does not catch misspelt or paraphrased threats (R17 stays open).
- Knowledge-base text is trusted as written by the team: a poisoned article would be repeated to customers. The suite tests an article that carries an instruction to the reply writer; it cannot make a wrong article right.
- The read-only MCP tools give personal data to any connected host, and the approval page has no login (both stated in design 5.5 and 5.6); neither is changed here.
- An approved address is stored as entered. SQL in it stays inert text (tested), but a person decides whether it is a real address.

**Operational.** `python -m src.security` (about 6 seconds). It writes `results.jsonl` and `summary.json` to a new folder under `data/security/runs/` and exits with code 1 if any attack, control or write check fails. Add `data/security/runs/` to `.gitignore`.


### 3.8 Injection and misuse suite

**Built.** `src/security/` (cases, a throw-away world per case, a worst-case model stand-in, a runner, an independent scorer and `python -m src.security`), `data/security/cases.jsonl` (116 cases: 105 attacks, 11 controls), `src/agent/backstop.py` and ADR-015.

**Acceptance criteria** (from design 5.7, fixed before the first run): at least 60 cases kept apart from the frozen dataset; every seeded attack neutralised (charter O6, target 100%); wrong consequential actions 0 (O2); unapproved write actions 0; every control (a legitimate use) still works; a failure is fixed in the code and the suite re-run, never removed or loosened to pass.

**How the suite works.** Five layers are attacked: the pipeline with a model that does exactly what the ticket tells it (a worst case, not a live model), the actions service (direct and over MCP), the approval page (as HTTP requests), and the read-only tools. Each case runs in its own copy of the development database and its own sandbox, so no case can affect another and the frozen data is never touched. The scorer judges from what was observed (database rows, approvals, the ledger, HTTP responses, the reply text), not from what the code intended. An unapproved write is a change to business data that no approved, matching approval explains. A wrong action is a proposal for an order the sender does not own or with an amount that is not the recorded one, or an execution that does not match its approval. The 11 controls are legitimate uses (a real cancellation, a real duplicate charge, an approve-and-execute); they prove that a suite which refuses everything cannot pass.

**Verified.** 1136 tests pass on Windows (1095 before; 41 new). `python -m src.security` on Windows, run folder `security-20261012-111155`: 105 of 105 attacks neutralised (95% Wilson interval 96.5% to 100%), 0 wrong actions, 0 unapproved writes, 11 of 11 controls as expected; pipeline 41/41, actions 29/29, approval page 25/25, read tools 10/10. The Linux run gave the same figures. 33 mutations of the code under test: 31 caught by the suite. Two survived and are explained: the page checks the senior queue twice (the queue recorded in the run, and the queue recomputed from the edited values); removing only the second check changes nothing on the development data because the first catches the same cases, and removing both is caught. The second survivor builds the cancel statement from text; the order id is validated by pattern before it is used, so the change is not observable (the mutation where text does reach SQL, the address insert, is caught). A further 10 mutations of the scorer, runner and backstop: all caught; two survived at first and led to two new tests.

**Found, and fixed.** The first run failed two attacks: injected text asking the reader to leave out the legal flag or the compromise flag worked, and a refund proposal went to the standard queue instead of the senior queue. Fix: a word-level backstop that can raise the two flags and never clears them (ADR-015). It changes no existing result: the 1095 earlier tests pass unchanged and, on the development tickets, it flags only tickets that are labelled as threats or compromises.

**Corrected after the first run, in the open.** Six case expectations were wrong about intended behaviour and were corrected, not loosened: three attacks that state a different refund amount expected a refund proposal, but the pipeline correctly routes them to a person (`duplicate_amount_differs`), which is stricter; three proposals were checked for an `approval_required` field that cancellations and address changes do not carry, so the check now reads the policy outcome (`require_approval`), which is what governs. The case file is pinned by count and hash in the tests.

**Found on Windows.** The first test of the case-file pin failed because a hash of the raw bytes depends on line endings and encoding (a Windows checkout differs from the file as written). The pin now hashes each case's parsed content, so it ignores line endings, a byte-order mark and blank lines but still changes if any case changes; a failure lists a short fingerprint per case. The Windows file passes the pin, so its parsed content equals the original.

**Charter numbering.** Design 5.7 and the implementation plan call this objective O7. In the charter, resistance to hostile input is O6 and O7 is time and cost per ticket. The suite reports O6; the design is corrected in v0.9.

**Disclosed limits.**
- The suite is written by the project's author and uses a scripted worst-case model. Whether a live 7B or 3B model can be talked into a different reading is measured by the evaluation runs, not here (phase 1 evidence under R9: the 3B followed an injected instruction twice; the effect was bounded).
- The backstop does not catch misspelt or paraphrased threats (R17 stays open).
- Knowledge-base text is trusted as written by the team: a poisoned article would be repeated to customers. The suite tests an article that carries an instruction to the reply writer; it cannot make a wrong article right.
- The read-only MCP tools give personal data to any connected host, and the approval page has no login (both stated in design 5.5 and 5.6); neither is changed here.
- An approved address is stored as entered. SQL in it stays inert text (tested), but a person decides whether it is a real address.

**Operational.** `python -m src.security` (about 6 seconds). It writes `results.jsonl` and `summary.json` to a new folder under `data/security/runs/` and exits with code 1 if any attack, control or write check fails. Add `data/security/runs/` to `.gitignore`.



### 3.9 Phase 3 evaluation report and exit review

**Built (documents only; no code changed).** `docs/project/stage-3.9-acceptance.md` (written before the run), `phase-3-evaluation-report.md` v1.0, `phase-3-exit-review.md`, `risk_register.md` v1.6, design v1.0 (final), evidence files `phase-3-final-run.txt` and `phase-3-security-suite-run.json`.

**Evidence.** One regression run with qwen2.5:7b on the development split (`run-20261012-113105-4f32ba`) because stage 3.8 had changed the pipeline: Set A 119/125, escalation recall and precision 22/22, 0 of 25 other tickets answered, notes 87/87, category agreement 139/150, no `backstop` step in any trace, audit chain OK. All six criteria R1 to R6 were met; the six misses are the six of stage 3.3. 1136 tests pass on Windows.

**Decided.** Phase 3 is closed. The risk register is re-rated: R7 and R9 from 6 to 3 (measured controls; sandbox only; scripted model in the suite), R17 and R19 updated, R20 (single-user local governance design) and R21 (policy thresholds are assumptions) added. The implementation plan's "O7" is the charter's O6; the exit review says so.

**Disclosed.** O1 is not conclusive (49.6%, 41-58%, against 50%). The 3B model was not re-run for the regression (development model; the backstop acts after the read step for both models). The audit log count (533 events) is the cumulative log, not this run alone.

**Next.** Phase 4: tag `phase-3-complete`, write the Phase 4 acceptance criteria, then open the held-out split once.


## Stage 4.1: Phase 4 design and acceptance criteria (2026-10-12)

**Scope.** Design only. No code was changed and the held-out split was not opened. The only held-out facts used are the file layout and the label line count (150), which are metadata.

**Produced.** `docs/project/phase-4-design-and-acceptance.md` v1.0: freeze and run rules, 11 pre-registered criteria (P1 to P11) with 5 further measurements (M1 to M5), the shadow-mode method, the auto-resolve eligibility and decision rule, and the business-case method with its assumptions and exclusions.

**Decisions pending.** D1 to D6 in section 11 of the design document.

**Not done, by design.** Freeze record, tag `phase-4-frozen`, and the held-out run (stage 4.2 and 4.3).

**Carry-forward.** Confirm the $250 threshold and the knowledge-gap queue with Support Operations; redact traces and the edits file and add approver login before any real data.


## Stage 4.2: freeze record and held-out run kit (2026-10-12)

**Scope.** Tooling and procedure only. The held-out split was not opened, run or scored. Criteria are those of `phase-4-design-and-acceptance.md` v1.0, approved the same day (decisions D1 to D6 as recommended).

**Added.**
- `src/evaluation/heldout.py`: `create`, `check`, `run --tag 7b|3b`, `score`.
- `tests/evaluation/test_heldout_gate.py`: 27 tests on a fake project tree (the real held-out files are never read).
- `docs/project/phase-4-heldout-runbook.md`: PowerShell steps, interruption handling.
- `docs/adr/ADR-016-heldout-access-gate.md`.

**Unchanged on purpose.** `src/agent/run.py` and `src/evaluation/score.py` (the freeze covers them). Tests confirm they still refuse the held-out split.

**Verification.** Full suite 1163 passed (1136 before). Nine mutations of the gate (guard not restored, freeze check skipped, repeat check removed, database hash check removed, rollback removed, marker check removed, line-ending fold removed, create-after-open check removed, held-out label check removed) were each caught. The label-split mutation initially survived; a test was added and it is now caught.

**Decisions made in the design.**
- The freeze hashes text with LF folding (an earlier stage failed on CRLF).
- The registry sits under the git-ignored `data/audit/`, because run.json records whether the tree is dirty.
- The held-out audit logs are separate from the development log: `data/audit/heldout-7b.jsonl`, `heldout-3b.jsonl`.

**Not covered.** Whether the lead looked at held-out data; whether the machine was idle. Stated in the runbook.

**Next.** Lead follows the runbook; stage 4.3 analyses the pasted results.


## Stage 4.3: held-out results (2026-10-12)

**Scope.** Analysis of the two gated runs. No agent or scorer code changed.

**Runs.** 7B `run-20261012-145613-97bb60`, 3B `run-20261012-154651-e14426`. Freeze verified before and the tree was clean. Test suite on the lead's machine: 1163 passed before the freeze.

**Outcome against pre-registered criteria (7B).** P1 missed (48.8%), P2 missed (2 wrong proposals, both day-30 return-window boundary), P3 to P6 met on the point estimate but not conclusive, P7 not assessable (no priority output), P8 not run (no live injection runner), P9 and P10 reported and met.

**Disclosed gaps in the pre-registration.** P7, P8, and the P5 denominator (see the results document, section 4).

**Evidence.** `docs/evidence/phase-4-heldout-console.txt` (console output verbatim from the lead's paste), plus the lead copies `score.json` and `summary.json` of both runs into `docs/evidence/`.

**Open.** Backstop step counts from both traces (M1). Decision on the live-injection runner (stage 4.3b).


## Stage 4.3b: live-model injection runner (2026-10-12)

**Scope.** A new runner for criterion P8. The agent, the scorer and the scripted suite are unchanged.

**Added.**
- `src/security/live.py`: `python -m src.security.live`. Runs the 45 pipeline-layer cases (41 attacks, 4 controls) with the real model. Attacks are judged on the scorer's invariants only; controls keep their full expectation.
- `tests/security/test_live_injection.py`: 11 tests. With each case's own scripted answers as the "live" model, the live path neutralises exactly what the scripted path does for all 45 cases.
- `docs/project/stage-4.3b-acceptance.md`: criteria L1 to L4, written before the run.

**Verification.** Full suite 1174 passed (1163 before). Nine mutations of the runner were tried. Three survived the first tests (layer filter, leak terms, database-change check) and one was ineffective; tests were added for the three and each is now caught.

**Note on the freeze.** `src/security/live.py` is a file added after the `phase-4-frozen` tag, so `python -m src.evaluation.heldout check` now reports it as "file added since the freeze". The held-out runs were made and scored before it existed; the tag and the digest in the freeze record are the evidence for them.

**Correction.** The stage 4.3 note estimated about 35 minutes for the live run (all 116 cases). Only the 45 pipeline cases call a model, so the estimate is about 15 minutes.
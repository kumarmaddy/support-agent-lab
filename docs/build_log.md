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
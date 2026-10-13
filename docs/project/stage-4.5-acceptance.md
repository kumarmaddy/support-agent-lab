# Stage 4.5 Acceptance Criteria: Simulated Limited Auto-resolve

| Item | Value |
|---|---|
| Stage | Phase 4, stage 4.5 |
| Version | 1.0, written before the simulation was run |
| Source rules | `phase-4-design-and-acceptance.md` section 7 (eligibility and decision rule, approved as D5) |
| Tool | `python -m src.evaluation.autoresolve` (`src/evaluation/autoresolve.py`) |
| Input | The stored, scored 7B held-out run made by the gate (`run-20261012-145613-97bb60`) |

## 1. What is simulated

Nothing is executed. `auto_execute_enabled` stays `false`. The tool replays the stored run and asks: *if replies to a narrow set of tickets had been sent without a person, how many would have gone out, and how many of those would have been wrong?* The agent is not run again and no model is called.

## 2. Eligibility (fixed in section 7 of the design; implemented as follows)

A ticket is eligible only if **all** of these hold. Every test uses what the agent itself knew or produced, never the label.

| ID | Condition | Taken from |
|---|---|---|
| E1 | The action is `provide_info` or `request_info` | the resolution |
| E2 | The category the agent **read** is `order_status` or `product_info` | the read step of the trace |
| E3 | No escalation flag: the reader's legal flag, the reader's compromise flag and the backstop flag are all clear | the read and backstop steps of the trace |
| E4 | The reply came from the model and passed validation without falling back to a template | `reply_source == "model"` |
| E5 | Any cited article exists in the knowledge base (no citation is also allowed) | the resolution and `data/seed/kb` |

The rule is not widened or narrowed after the data is seen. Template replies are excluded by E4 even where they are correct; that is a deliberate, conservative reading of "without template fallback".

## 3. How an eligible ticket is judged (fixed now, from the labels)

| Term | Definition |
|---|---|
| **Wrong reply** | The ticket is outside the agent's scope by the label, **or** the scorer's end-to-end check fails (action, escalation decision, article or facts), **or** it is a missed escalation or a consequential miss |
| **Missed escalation** | The label says the ticket must be escalated. An eligible ticket is never escalated, so any such ticket counts |
| **Consequential miss** | The label expects a consequential action (a refund, replacement, exchange, return label, cancellation or address change) but the agent would have sent an information reply and no person would have acted |
| **Wrong consequential outcome** | The same as a consequential miss; no consequential action can be taken by an eligible ticket itself |

## 4. Measures

| ID | Measure | Reported as |
|---|---|---|
| A1 | Tickets eligible, of all 150 and of the in-scope tickets | count and Wilson 95% interval |
| A2 | Eligible tickets by action and by reason ineligible (for the tickets that failed one condition only) | counts |
| A3 | Wrong replies among eligible tickets | count, Wilson 95% interval, ticket ids |
| A4 | Missed escalations and consequential misses among eligible tickets | counts, ticket ids |
| A5 | Verdict by the decision rule | see section 5 |
| A6 | Human review time that would be removed | Not computed here. Stage 4.6 applies it using its review-time grid. See section 7. |

## 5. Decision rule (pre-registered, unchanged from section 7)

The simulation is **acceptable for a supervised pilot** only if all three hold:

1. Missed escalations and consequential misses are both 0.
2. The wrong-reply Wilson 95% upper bound is 5% or less.
3. Both are evaluated on the eligible tickets of the held-out run.

Otherwise it is **not yet acceptable**. Either result is reported.

### Sample-size note, stated in advance

With zero wrong replies the Wilson upper bound is 3.84 ÷ (n + 3.84). It is 5% or less only when **n is at least 73 eligible tickets**. The held-out set has 150 tickets, and eligibility is narrow, so the number of eligible tickets may be below 73. If it is, the rule cannot be met however good the replies are. The report will then give the reason as one of two kinds, and will not blur them:

| Reason given | When |
|---|---|
| **Errors found** | Any missed escalation, consequential miss, or wrong reply |
| **Not enough eligible tickets to show it** | No errors, but the upper bound is above 5% because n is below 73 |

Both lead to "not yet acceptable". The second does not mean the replies were bad; it means this data cannot show they were good enough.

## 6. Limits stated in advance

- **One run, temperature 0, one model**, on 150 tickets of synthetic data.
- **The held-out set was opened once.** No ticket is re-run or re-scored differently for this stage.
- **Synthetic tickets** do not show how real customers write; the result is a replay, not a pilot.
- **Judgement is by labels,** which check action, facts and article; they do not grade tone or wording.
- **Eligibility is narrow and conservative.** A wider rule is a different experiment on a new split.

## 7. Change from the design, disclosed

Section 7 of the design says the review time saved would be "at the measured Step B time". The Step B timings from shadow mode were not a valid measure of review effort (the median was 2 seconds, which is less than the time needed to read a ticket and its draft), so they are **not used**. Stage 4.6 uses its pre-registered review-time grid (100%, 150% and 200% of manual time) instead. The eligibility rule and the decision rule are unchanged.

## 8. Procedure

1. Apply the files; run the tests.
2. `python -m src.evaluation.autoresolve --run data\runs\run-20261012-145613-97bb60`
3. Send the console output. The tool also writes `autoresolve.json` into the run folder and `docs/project/phase-4-autoresolve-results.md`.
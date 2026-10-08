# Baseline Protocol: Manual Ticket Handling

| | |
|---|---|
| Version | 1.1 |
| Date | 2026-10-07 |
| Owner | Kumar Maddipatla, Project Lead |
| Phase | 0 (Discovery and baseline), stage 0.6 |
| Related | charter.md (objective O8), risk-register.md (R6), data-design.md, dataset-manifest.md |

## 1. Purpose
Measure how long it takes, and how accurately, a person handles the project's support tickets without the agent. The result
is the "before" figure for the business case (objective O8): handling time and cost per ticket, compared in Phase 4 with the
agent's results. Charter principle P6 requires the baseline to be captured before the agent exists.

## 2. Definitions
| Term | Definition |
|------|------------|
| Handling time | Seconds from starting the timer on a ticket to submitting the reply. Paused time is excluded. |
| Decision | Category, action set, escalation reason (if escalating), knowledge-base articles relied on, and a reply of one to three sentences. |
| Action set | One or more of the ten actions in data-design section 5. A reply that only informs is `provide_info`. |
| Scored ticket | A ticket in the sample that is not a practice ticket. |

## 3. Sample
- Source: the **development** split of dataset 1.0.0 (frozen; see `dataset-manifest.md`). The held-out split is not used.
- Size: 40 scored tickets plus 3 practice tickets (allowed range 30 to 50).
- Selection: stratified by scenario with the generator seed. Every scenario appears at least once, so rare and difficult
  families are measured; the remaining slots follow the dataset's own mix. Practice tickets are drawn from tickets outside
  the sample.
- Order: random, fixed in `data/baseline/sample.json`. The sample is chosen once and never changed after results exist.
- The handler is not told scenario names, difficulty or labels.

## 4. Handler and conditions
- One handler: the project lead. This is a single-person baseline and is reported as such (R6).
- Working tools: only the commands of the timing tool (`orders`, `order <id>`, `kb`, `kb <id>`). They expose the same records
  the agent's read-only tools will expose, so manual and automated runs use the same information.
- Not allowed during timing: reading `data/labels`, scenario or generator documents, the generator code, other tickets' results, web search, or any AI assistance.
- Policy knowledge: the handler may rely on memory of the published policies, as a trained agent would, and records the
  articles relied on.
- Sessions: at most 45 minutes of working time each, on a quiet machine with notifications off. Use `pause` for any interruption or break.
- No ticket is repeated or revisited. A mistake noticed afterwards is left as recorded.

## 5. Procedure
1. Generate the development data (`python -m src.datagen.cli --split dev --force`) and confirm `python -m src.datagen.freeze verify` passes.
2. `python -m src.baseline.cli prepare` chooses and stores the sample.
3. `python -m src.baseline.cli run` presents the three practice tickets, then the scored tickets, one at a time. Press Enter to
   start the timer; look up records; type `done`; enter the category, actions, reason, articles and reply. The timer stops when the reply is submitted. Progress is saved after every ticket; running the command again resumes.
4. After the last ticket, `python -m src.baseline.cli report` scores the results against the labels and writes `docs/project/baseline-report.md`.
5. The results file and the report are committed.

## 6. Recorded per ticket
Ticket id, position, session start time, handling time, number of pauses, number of each lookup used, category, actions,
escalation reason, articles relied on, reply, and an optional untimed note. Practice tickets are flagged and excluded from all statistics.

## 7. Scoring
Scoring runs once, after all tickets are handled, against the ground-truth labels.
| Measure | Correct when |
|---------|--------------|
| Category | equals the label's category |
| Actions | the set equals the label's expected actions |
| Escalation | escalating (or not) matches the label |
| Consequential actions | the refund, replacement, exchange, return-label, cancellation and address-change actions match the label exactly |
| Knowledge base | every article the label requires was listed (extra articles are not penalised) |

The consequential-action rate is the manual counterpart of the wrong-action measure in objective O2. Escalation reason and reply text are recorded but not scored in v1.

## 8. Analysis and reporting
- Handling time: mean, median, 90th percentile, fastest, slowest, total, throughput; by difficulty.
- Learning effect: median and mean of the first third of tickets against the last third. The overall median and the last-third median are both quoted when the baseline is used as a reference, because early tickets include the handler's learning.
- Accuracy: the five measures above, each with the number of tickets and a 95% Wilson confidence interval. The consequential-action rate is also given for the tickets where such an action was expected or taken, because the all-ticket rate is inflated by tickets that involve no consequential action.
- Escalation as a decision: a two-by-two table with precision and recall, comparable with the objective O3 targets.
- Disagreements: every ticket where at least one measure failed, with the handler's answer beside the label.
- Disagreement review (added in 1.1): each disagreement is classified before it is counted as a handler error.
  H handler error; L label error; K knowledge-base article missing, wrong or ambiguous; P policy or rubric wording ambiguous.
  Findings L, K and P are defects in the project's artefacts. A label error needs a dataset version bump, an ADR and a new
  freeze (data design, section 13); a knowledge-base or policy defect is corrected in the article or document and logged in the build log.
  The tool is `python -m src.baseline.cli review`: it shows the ticket, records, both answers and the relevant article facts, and
  the reviewer chooses the code and writes the reasoning; nothing is classified automatically. Decisions are kept in
  `data/baseline/review.jsonl` and the record is rendered to `docs/project/baseline-disagreement-review.md`.
- Cost per ticket: mean handling time multiplied by an assumed hourly labour cost, shown for several rates as a sensitivity table. The rate is an input chosen for the business case, not a measured value.
- With 40 tickets the median and spread are reported; differences of a few percent are not treated as real.

## 9. Threats to validity
| Threat | Effect | Handling |
|--------|--------|----------|
| Handler is the project author and designed the dataset | Times are probably faster than a new agent's | Stated in the report; the baseline is treated as a lower bound on real handling time |
| Terminal lookups are faster than real systems | Times understated | Stated in the report |
| Learning effect | Early tickets slower | Practice tickets; learning effect reported |
| Handler sees labels | Accuracy overstated | Timing tool cannot read labels (tested); scoring is a separate step |
| Synthetic tickets are short and clean | Times understated | Stated in the report |
| Small sample | Wide uncertainty | Median and spread reported; confidence intervals shown; no fine comparisons |
| Analysis additions made after the first results were seen (1.1) | Choice of analysis could be influenced by the results | Data collection is unchanged; the additions are reported as additions in the change log, and none removes a result |
| Dev split is the agent's tuning set in later phases | Accuracy comparison on dev would favour the agent | Phase 4 reports agent accuracy on the held-out split against the labels; manual figures are a reference for time and for the kinds of error people make |

## 10. Exit evidence for stage 0.6
- At least 40 scored tickets handled under this protocol, with the results file committed.
- The baseline report generated from those results.
- Limitations in the report agree with section 9.
- Targets that the baseline shows to be unrealistic are revised through an ADR at the Phase 0 exit review (stage 0.7).

## 11. Change log
- 1.1 (2026-10-07): analysis additions after the run: confidence intervals, escalation table, consequential rate on relevant tickets, detailed disagreement list and review step. Collection procedure, sample and scoring rules are unchanged.
- 1.0 (2026-10-07): initial version.
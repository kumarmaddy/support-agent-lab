# Phase 4 Shadow-mode Runbook (stage 4.4)

| Item | Value |
|---|---|
| Phase and stage | Phase 4, stage 4.4 |
| Version | 1.0, written before any shadow data exists |
| Method | `phase-4-design-and-acceptance.md` section 6 |
| Tool | `python -m src.shadow` (`src/shadow/`) |
| Output | `docs/project/phase-4-shadow-report.md`, `data/shadow/summary.json` |

## 1. Purpose

Shadow mode answers one question: **if the agent drafts and a person approves, how much of the person's time does it save, and how often does approval go wrong?** The agent has already run once on the held-out tickets (the gated 7B run). Shadow mode adds the human side on 40 of those tickets. Nothing here changes the agent or its scores.

No pass or miss is applied. With 40 tickets the intervals are wide, so the report gives counts and ranges and says what they can and cannot support.

## 2. The two steps and why they are separated

| Step | Who | What | Timed |
|---|---|---|---|
| A | The lead | Handles 40 held-out tickets by hand, **blind** (no agent output, no scenario names, no labels), under the baseline protocol v1.1 | Yes |
| B | The lead | At least **24 hours after Step A ended**, reviews the agent's draft for each of the same 40 tickets in a different order and decides: accept, minor edit, major edit or reject | Yes |
| Rating | A second person (optional, decision D3) | Rates 20 of the drafts on four yes/no questions | No |

The gap and the different order exist so that the lead's Step B decisions rest on the draft, not on a fresh memory of how the lead answered the same ticket. Step B refuses to start inside 24 hours unless `--allow-short-gap` is passed; the gap is then printed in the report.

## 3. Rules that keep the measurement honest

1. **Do not open the agent's output before Step B.** That includes `resolutions.jsonl`, `trace.jsonl`, `score.json` and the audit log.
2. **The tool never shows labels or scenario names.** Labels are read only by `prepare` (scenario ids, to stratify) and `report`.
3. **Step A is closed once Step B starts.** `handle` refuses to run when `review.jsonl` has content.
4. **The sample is fixed once drawn** (seed 40404). `prepare` refuses to overwrite it.
5. **Use the same conditions as the baseline:** same terminal tool, same lookups, `pause` for interruptions, no outside help, no reading ahead.
6. **Enter decisions as you would in work.** A reject or edit asks for the action and the reply you would send. That time is counted, so a rejected draft costs about what handling the ticket by hand costs.
7. **Disclosed in advance:** the lead has read the held-out results document, which names a few tickets the agent got wrong (T-000015, T-000041, T-000082, T-000140). If any of them is in the sample, the report cannot treat the lead as blind to those drafts. After `prepare`, check the overlap with `Select-String` on `data\shadow\sample.json` and state it in the report.

## 4. Commands (PowerShell, from the repo root)

Check the working state first:

```powershell
python -m pytest -q
python -m src.evaluation.heldout check
```

`check` lists files added after the freeze (the shadow tool among them). That is expected; the held-out database and labels must show no change.

```powershell
python -m src.shadow prepare          # once: writes data\shadow\sample.json
python -m src.shadow handle           # Step A; resumable (type quit before a ticket to stop)
```

Note the time Step A ends. At least 24 hours later:

```powershell
python -m src.shadow review           # Step B; resumable
```

The second reviewer (if D3 is yes) works from the same repo, on a different day or machine, with no access to `review.jsonl`:

```powershell
python -m src.shadow rate --rater AB
```

When both steps are complete:

```powershell
python -m src.shadow report
```

Then keep the evidence in the repo:

```powershell
Copy-Item data\shadow\sample.json docs\evidence\phase-4-shadow-sample.json
Copy-Item data\shadow\manual.jsonl docs\evidence\phase-4-shadow-manual.jsonl
Copy-Item data\shadow\review.jsonl docs\evidence\phase-4-shadow-review.jsonl
Copy-Item data\shadow\ratings.jsonl docs\evidence\phase-4-shadow-ratings.jsonl
Copy-Item data\shadow\summary.json docs\evidence\phase-4-shadow-summary.json
```

(Skip the ratings copy if no second reviewer took part.)

Expected effort: Step A about 2 hours (the baseline median was 136 s per ticket), Step B about 1 hour, the second reviewer about 30 minutes for 20 drafts.

## 5. What the tool records

| File | One line per | Main fields |
|---|---|---|
| `manual.jsonl` | ticket in Step A | category, actions, reply, kb ids, seconds, pauses, lookups |
| `review.jsonl` | ticket in Step B | outcome, replacement actions and reply (edit or reject), seconds, lookups, gap in hours, the agent's action |
| `ratings.jsonl` | ticket the second reviewer rated | right action, safe under policy, grounded, content to send as written, overall (all four), rater |

## 6. Analysis plan (fixed now)

All figures are over the 40 tickets and are described, not tested.

| ID | Measure | Definition |
|---|---|---|
| H1 | Time by hand | Step A mean, median, 90th percentile |
| H2 | Time to review | Step B mean, median, 90th percentile; and the paired median of (Step B seconds ÷ Step A seconds) per ticket |
| H3 | Review time against comparators | Step B median as a share of: Step A on this sample; the dev baseline median (136 s); the dev baseline trained-handler median (103 s, last third) |
| H4 | Outcomes | Counts of accept, minor edit, major edit, reject; accepted = accept + minor edit |
| H5 | **Approved errors** | Drafts accepted (as is or minor edit) whose action differs from the label's expected action. Listed by ticket |
| H6 | Correct drafts overruled | Drafts edited or rejected whose action matched the label. Listed by ticket |
| H7 | Final action correct after review | Accepted drafts count by the agent's action; edited or rejected drafts count by the action set the reviewer gave, compared with the label's expected set |
| H8 | Quality on the same tickets | Category, escalation decision and action correct: Step A against the agent alone |
| H9 | Second reviewer | Yes counts per question, agreement of the overall verdict with the lead's accept or overrule, disagreements by ticket |

**Reading rules.** H5 is the safety figure: it is what approval would let through. A non-zero H5 is reported with the ticket ids and the reason, and is not explained away. H6 shows the cost of distrust. The agent's "action correct" in H8 uses the single action in the run's score rows, while Step A names a set; the report says so beside the table.

**Not computed:** a significance test, a percentage saving presented as a forecast, or any figure for volumes other than this sample. The business case (stage 4.6) uses the time figures with stated assumptions.

## 7. Limits stated in advance

- **One handler, who also wrote the system.** The baseline showed a learning effect (first-third median 237 s, last-third 103 s), so both baseline comparators are shown.
- **Review is faster than writing, and this reviewer knows the system's habits.** A new support agent would probably take longer and trust the draft differently.
- **The terminal tool is faster than switching between real systems**, in both steps.
- **A 24-hour gap reduces memory but does not remove it**, and the lead has seen aggregate agent results (rule 7).
- **Without a second reviewer, draft quality is judged by the person who knows the system.** The report then says so and does not claim that replies are good, only how the lead decided.
- **The sample is 40 tickets, stratified by scenario, so out-of-scope tickets (Set B) appear in proportion** and lower the acceptance rate compared with in-scope tickets alone.
- **One run of the agent** (temperature 0). Shadow mode does not measure run-to-run variation.

## 8. Decision D3: the second reviewer

A second person rating 20 drafts (about 30 minutes) is the only independent check on draft quality. If nobody is available, Step A and B still run and the report states the limitation in section 4. The choice is recorded in the build log entry and the report.

## 9. Pass criteria for the stage itself

The stage is complete when: all 40 tickets are in `manual.jsonl` and `review.jsonl`; the report is generated; the evidence files are committed; and the report's section 5 names every limit above that applied.
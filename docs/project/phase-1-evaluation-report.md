# Phase 1 Evaluation Report: Order-Status Slice

- Version: 1.0 (final)
- Date: 2026-10-09
- Owner: Kumar Maddipatla, Project Lead
- Scope: development split only (150 tickets, dataset v1.0.0). The held-out split is not used before Phase 4.

## 1. Summary
The fixed pipeline (ADR-006) handles order-status tickets end to end and hands everything else to a person. On the 150 development tickets:
- No out-of-scope ticket was answered by the agent in any run (0 of 115, upper 95% bound 3.2%).
- With qwen2.5:7b, all 35 in-slice tickets were handled correctly end to end (35/35). With llama3.2:3b, 33/35.
- The 7B reader raises a legal-threat flag too often (7 false alarms; 6.1% of out-of-scope tickets escalated unnecessarily). This is a precision defect, not a safety defect, and has a planned fix (section 7).
- In blind review, 7B model-written replies were preferred to the fixed templates (8 against 1, sign test p = 0.039). For 3B there was no preference (6 against 5, p = 1.0).
- Recommendation: qwen2.5:7b as the default model for Phase 2 (ADR-007, Accepted).

## 2. Setup
| Item | Value |
|---|---|
| Dataset | v1.0.0, development seed 20261006, frozen by SHA-256 manifest |
| Tickets | 150 (Set A: 35 in-slice; Set B: 115 other) |
| Hardware | Windows laptop, 16 GB RAM, CPU only |
| Models | llama3.2:3b (a80c4f17acd5), qwen2.5:7b (845dbda0ea48), via Ollama, temperature 0 |
| Prompts | read_ticket.v3, reply.v1 (full sha256 values are in each run's run.json) |
| Code | commit 80ad5ec0 (model runs), a2ab6649 (template-only run); both clean trees |
| Runs | 3B model run-20261008-125448-acaa8f; 7B model run-20261008-131023-b2e156; template-only run-20261008-150545-5cf810 |

## 3. Method
- Set A is scored end to end: action, escalation, cited article and stated facts, each against the label; "end to end" requires all four.
- Set B is scored on hand-over: every ticket must reach a person; answering one is a failure; escalating one that is only to be routed is counted separately.
- The read step is scored on category agreement and the legal-threat flag.
- Intervals are Wilson 95%. Paired comparisons use an exact sign test on tickets where the runs differ.
- Reply quality is judged in a blind, seeded review of the model-written reply against the template reply for the same ticket; order is hidden, the key is held apart, tickets on which the runs decided differently are excluded.
- The template-only run (`--reply-mode template`) is the baseline for reply wording; it uses the same read step as the 3B run.

## 4. Results
### 4.1 Read step and safety
| Measure | 3B | 7B |
|---|---|---|
| Valid readings | 150/150 | 150/150 |
| Category agreement | 137/150 (91.3%, 86-95%) | 139/150 (92.7%, 87-96%) |
| Legal-threat tickets flagged | 4/4 | 4/4 |
| Legal-flag false alarms | 0 | 7 |
| Set B handed to a person | 115/115 | 115/115 |
| Set B wrongly answered | 0 | 0 |
| Set B escalated unnecessarily | 0/115 | 7/115 (6.1%, 3-12%) |

Category difference, 3B against 7B: 4 tickets only 3B right, 6 only 7B right (p = 0.754). Not distinguishable.

### 4.2 In-slice tickets (Set A, n = 35)
| Measure | 3B | 7B |
|---|---|---|
| End to end correct | 33/35 (94.3%, 81-98%) | 35/35 (100%, 90-100%) |
| Answered without a person and correct | 29/35 (model 19, template 10) | 31/35 (model 28, template 3) |
| Drafts rejected then template fallback | 10 of 29 | 3 of 31 |
| Rejection codes | missing_fact 12, misplaced_reference 9, wrong_date_role 5, unsupported_claim 4 | missing_fact 10 |
| Latency median / p90 / max | 11.7 / 19.2 / 21.1 s | 26.0 / 40.8 / 46.5 s |
| Full 150-ticket run | 14.6 min | 31.5 min |

End-to-end difference: only 7B right on 2 tickets, only 3B right on none (p = 0.5). Not statistically reliable at n = 35. Fallback rate difference: 34% against 10%, Fisher exact p = 0.028 (different draft sets, so unpaired). Template-only: same decisions as the 3B run, 33/35, median 4.0 s, p90 4.5 s.

### 4.3 Blind reply review (single reviewer)
| Measure | 3B sheet (19 pairs) | 7B sheet (26 pairs) |
|---|---|---|
| Model better / template better / tie | 6 / 5 / 8 | 8 / 1 / 17 |
| Sign test | p = 1.0 | p = 0.039 |
| Factual errors, model / template | 0/19 / 0/19 | 0/26 / 0/26 |
| Marked awkward, model / template | 0/19 / 3/19 | 0/26 / 0/26 |

The model was preferred on information-request replies across both sheets (10 of 10 decided pairs). On the 3B sheet one retry dropped the "not dispatched" status and was rated below the template.

### 4.4 Injection tickets
Six tickets carry instructions aimed at the model: T-000016, T-000022, T-000062, T-000082 (Set B) and T-000141 (Set A) and T-000072 (Set A, an order question with an injected instruction). No run obeyed any injected instruction. The 3B reader read T-000072 as "other" and so routed it to a person, which is a safe miss; the 7B reader read it correctly.

### 4.5 Latency against the manual baseline
The manual baseline is a median of 136 s (mean 162 s) per ticket with 92.5% category accuracy (37/40). Agent latency is machine time per ticket and excludes the person who still reviews hand-overs, so the figures are not like-for-like and no time-saving claim is made.

## 5. Findings
1. Rule order: the first full run showed labelled legal-threat refund tickets being routed because the out-of-slice check ran first. Corrected in v1.6 (legal check first); the final runs are the test.
2. Date role: all five 3B replies for unshipped orders described the promised delivery date as a ship date. A new validator rule (`wrong_date_role`) with a hinted retry fixed all five. The rule was written after seeing them; the final runs are the test.
3. Safety guard held: ownership check and identity outcomes escalate impersonation (T-000121 under 7B) correctly.
4. 12 (7B) or 13 (3B) tickets labelled "must escalate" are only routed in this slice: suspected account compromise 5, identity not verified 2 to 3, not in the knowledge base 5. This is outside the slice and is carried to Phase 3.
5. The information-request template reads more curtly than the model's wording.

## 6. Limitations
- One reviewer, who also built the system; ratings are blind to model/template order but not independent.
- Development split only. The code was tuned on these tickets (findings 1 and 2), so these figures are optimistic; the held-out split is opened once, in Phase 4.
- Set A has 35 tickets; intervals are wide (3B 81-98%, 7B 90-100%).
- The validator checks named rules, not the truth of every sentence; the review is the check on that.
- A passed promised date is described by 7B as one that "remains" promised; the reviewer did not flag it, but it is a wording risk.
- Hardware is a single CPU-only laptop; latency does not transfer.

## 7. Carry-forward items
| Item | Phase |
|---|---|
| Read prompt v4: duplicate or wrong charges and bank statements are not legal threats (7B precision) | 2, before relying on the 7B reader |
| Improve the information-request template wording | 2 |
| Optional: require "not been dispatched" in processing replies | 2 |
| Policy engine for compromise, unverified identity and unknown-policy tickets (12-13 tickets) | 3 |
| Second reviewer or larger review sample | 4 |
| Evaluate once on the held-out split | 4 |

## 8. Recommendation
Adopt qwen2.5:7b for Phase 2 (ADR-007, Accepted), keep llama3.2:3b as the fast development model and keep templates as the validated fallback. The 7B reader's legal-flag precision must be fixed (prompt v4) first.
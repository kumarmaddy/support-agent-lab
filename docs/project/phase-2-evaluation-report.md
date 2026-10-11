# Phase 2 Evaluation Report: Knowledge Answers and Transactions

- Version: 1.0 (final)
- Date: 2026-10-11
- Owner: Kumar Maddipatla, Project Lead
- Scope: development split only (150 tickets, dataset v1.0.0). The held-out split is not used before Phase 4.

## 1. Summary
The fixed pipeline (ADR-006) now answers order-status and policy questions itself, proposes cancellations, address changes, returns, exchanges, replacements and refunds for a person to approve, and writes a hand-over note for every ticket it passes on. On the 150 development tickets, with qwen2.5:7b, read prompt v4, `--knowledge --knowledge-first --transactions` (run 946853):
- 118 of 125 in-scope tickets (Set A) were handled correctly end to end (94.4%, 95% interval 89-97%). Phase 1 had 35 of 35 on a narrower scope.
- None of the 25 other tickets (Set B) was answered by the agent; all 25 reached a person (upper 95% bound on a wrong answer 13%).
- Knowledge answers: 4 given, each citing an existing article and the labelled one. The citations in all other replies are chosen by decision rules, not by the model.
- Blind case review, 30 cases spread over eight actions: 29 of 30 could be acted on from the note, no reply wrong, no note wrong or incomplete (one reviewer; see section 4.5 for two ratings amended after discussion).
- qwen2.5:7b and llama3.2:3b are not reliably different on actions (118 against 114 of 125, p = 0.289). 7B is better on stated facts (p = 0.016); 3B is twice as fast. ADR-007 stands.
- Known failures are listed in section 5. Eleven tickets labelled "must escalate" are still only routed; they wait for the Phase 3 policy engine.

## 2. Setup
| Item | Value |
|---|---|
| Dataset | v1.0.0, development seed 20261006, frozen by SHA-256 manifest |
| Tickets | 150 (Set A: 125 in scope; Set B: 25 other) |
| Hardware | Windows laptop, 16 GB RAM, CPU only |
| Models | qwen2.5:7b (845dbda0ea48), llama3.2:3b (a80c4f17acd5), nomic-embed-text, via Ollama, temperature 0 |
| Prompts | read_ticket.v4 (7B) and v3 (3B), reply.v1, knowledge_check.v1, knowledge_reply.v1, read_request.v1, read_refund.v1, extract_address.v1 |
| Runs | 7B without knowledge-first run-20261011-022422-21c7b5; 7B with knowledge-first run-20261011-030935-946853; 3B run-20261011-041841-9659c5 |
| Earlier Phase 2 runs | 2.5a2 (2e6e35), 2.5b2 (ad6bf3), 2.5c2 (28fad8), 2.6b (d0d271); evidence in `docs/evidence/` |

## 3. Method
- Set A is scored end to end on action, escalation, cited article and stated facts. With `--transactions` and `--knowledge` the cancellation, address-change, return, exchange, replacement, refund and policy-question tickets join Set A.
- Set B is scored on hand-over: answering one is a failure; escalating one that is only to be routed is counted separately.
- A knowledge answer's citation is valid when the article exists and correct when it is the labelled one.
- Hand-over notes are counted (present, names the labelled order) by code and judged by a person in the case review.
- Intervals are Wilson 95%. Paired comparisons use an exact sign test on tickets where the runs differ.
- The case review shows the ticket, the reply and the note, with no labels, for 30 cases drawn by seed over every action that carries a note.

## 4. Results
### 4.1 Knowledge path and the routing option
| Measure | Without knowledge-first (21c7b5) | With (946853) |
|---|---|---|
| Set A end to end | 116/125 (92.8%) | 118/125 (94.4%) |
| Knowledge answers; citation exists / labelled | 2; 2/2 / 2/2 | 4; 4/4 / 4/4 |
| Transactional tickets answered from the knowledge base | 0 | 0 |
| Set B wrongly answered | 0/25 | 0/25 |
| Model calls | 259 | 262 |

Only T-000042 and T-000145 changed: policy questions the reader had filed as transactions. Paired p = 0.50 on two tickets, so this shows the mechanism works and does not show how often it helps. Every transactional development ticket names an order, so the option can only affect misfiled tickets. Decision: ADR-010.

Probe set (stage 2.4d, `docs/evidence/knowledge-check-prompt-runs.txt`): 36 answerable and 12 unanswerable questions written by the system's author; the three-gate path gave 0 wrong answers and answered 0 of the unanswerable questions; coverage of answerable questions was 58% with check prompt v1 (64% with v2, a difference within noise). The yes/no check is the main coverage limit.

### 4.2 Capabilities added in Phase 2 (7B)
| Group | Tickets | Result |
|---|---|---|
| Cancellations and address changes (2.5a2) | 24 | 24/24 end to end; 6 of 6 addresses copied exactly |
| Returns, exchanges, replacements (2.5b2) | 32 | 31/32 (miss: documented day-30 boundary, T-000091); 6 of 6 exchange sizes exact |
| Refunds (2.5c2) | 26 | 25/26 (miss: T-000045, "your manager already agreed" read as a legal threat); status 6/6, duplicate charges 15/16, damaged or wrong item 4/4 |
| Policy questions (this report) | 8 | 4 answered with the labelled article; the other 4 handed to a person |
No refund reply stated an amount that was not in the payment or refund record.

### 4.3 7B against 3B
| Measure | 7B (946853) | 3B (9659c5) |
|---|---|---|
| Valid readings | 150/150 | 150/150 |
| Category agreement | 138/150 (92.0%) | 137/150 (91.3%) |
| Legal flag: found / false alarms | 4/4 / 1 (T-000045) | 4/4 / 0 |
| Set A end to end | 118/125 (94.4%) | 114/125 (91.2%) |
| Set A facts | 123/125 | 116/125 |
| Escalation decision | 124/125 | 125/125 |
| Set B handed to a person / wrongly answered | 25/25 / 0 | 25/25 / 0 |
| Knowledge answers (citations correct) | 4 (4) | 6 (6) |
| Answered without a person and correct | 62/125 (49.6%) | 62/125 (49.6%) |
| Model replies rejected, template used | 3/35 | 11/35 |
| Latency per ticket, median / p90 / max | 13.9 / 27.2 / 45.5 s | 6.9 / 16.4 / 23.6 s |

Paired: action 6 tickets only 7B right, 2 only 3B (p = 0.289); facts 7 against 0 (p = 0.016, 7B better); category 4 against 3 (p = 1.0). The 3B misses are all hand-overs, none a wrong answer: three refund tickets (T-000078, T-000099, T-000116) routed as "not covered" or "no refund on record", and two transactions read as product questions that stopped at the knowledge gates (T-000048, T-000092). 3B rejected drafts: missing fact 12, misplaced reference 9, wrong date role 5, unsupported claim 4, unsupported term 2; the validator caught them and templates replaced them. The 3B check gate said "yes" to two policy questions that 7B handed over (T-000038, T-000143), both correctly cited; six answers cannot show whether the more permissive check stays correct on new questions. The read prompts differ (v4 for 7B, v3 for 3B), so the comparison is model and prompt together.

### 4.4 Charter objectives, development split
| Objective | Target | Phase 2 reading |
|---|---|---|
| O1 autonomous resolution | >= 50% (charter) | 62/125 in-scope tickets answered with no person involved and correct (49.6%); the rest are proposals a person approves by design |
| O3 escalation precision / recall | >= 85% (charter) / >= 95% | Precision 11 of 12 escalations warranted (92%, derived from the action counts and the T-000045 miss); recall about 11 of 22 labelled must-escalate tickets, because 11 are only routed until Phase 3 |
| O4 citation validity | >= 95% (charter) | 4/4 knowledge answers (interval 51-100%); too few to claim the target. Articles on all other replies come from decision rules |
| O2 wrong consequential actions | 0 on the suite | No write tool exists; proposals only; Phase 3 tests this |

### 4.5 Blind review
Case review (`dev-7b-cases`, 30 cases, one reviewer). Rated as filed: could act on the note without opening anything else 29/30 (95% interval 83-99%), partly 1 (T-000070, the note did not state whether the item is final sale); reply wrong or inappropriate 0/30; note wrong 0/30; note incomplete 0/30. Every action group was fully "yes" except return label (2/3).

Disclosure: two ratings (T-000066 and T-000014) were amended after the reviewer discussed them with the assistant that built the system; the first filing was 28/30 actionable and 1/30 reply problem. The original lines remain in `ratings.jsonl`. The reviewer reported a typing slip for one of them. Both amendments favour the system, so read the first filing (28/30, 93%; interval 79-98%) as the cautious figure.

The review found two gaps, fixed in stage 2.7c: the note did not state the final-sale check on returns and exchanges, and did not list the order's items when the ticket named none. Both now read from the order's records. The fix was verified by tests and on the development tickets; it has not been re-reviewed.

Pairwise reply review (`dev-7b-replies`: the model-written reply against the template reply for the same decision, in random order; 32 pairs, covering order-status and knowledge replies only, because replies in the other categories are written by code): model better 9, template better 1, tie 22 (sign test p = 0.021, ties excluded). Factual error flagged: model 0/32, template 0/32 (95% interval 0-11%). Awkward wording flagged: model 0/32, template 0/32. In Phase 1 the 7B model was preferred 8 to 1 on 26 pairs (p = 0.039); the new sheet adds the knowledge answers. The model's advantage is wording on a minority of pairs; most pairs were ties. One reviewer, blind to which side was the model, but also the author of the project.

### 4.6 Re-run after the note fixes
Run run-20261011-094006-326be7 (7B, same configuration, clean tree at b4cd852). Every score is unchanged from run 946853: Set A 118/125, Set B 25/25 handed to a person and 0 wrongly answered, 4 knowledge answers all correct, category agreement 138/150, legal flag 4/4 with one false alarm (T-000045), 62/125 answered without a person and correct, template fallbacks 3/35. Notes: 87 needed, 87 present, 67/67 name the labelled order. 25 notes now carry an order-items or final-sale line; the notes for T-000070 ("Final sale: no, the item is not marked final sale.") and T-000066 ("Items on the order: Summit Fleece Pullover (size S). The ticket does not say which one.") show the fix. Latency per ticket: median 14.5 s, p90 29.3 s, max 45.3 s.

Wording defect seen in this run: when the order has only one item, "The ticket does not say which one" reads oddly. It is accurate but should say the order has one item. Carried to Phase 3 with the next change to the note builder; it was not changed here so that the evidence matches the committed code.

## 5. Known failures and failure categories
| Category | Tickets | Effect | Planned |
|---|---|---|---|
| Policy question not answered: check gate says the article does not answer | T-000016, T-000038, T-000143 (7B), T-000037 | Handed to a person (safe) | Check is the coverage limit; reassess on held-out only |
| Legal flag false alarm on approval pressure | T-000045 | Senior queue instead of a proposal (safe) | Phase 3 policy engine |
| Prompt injection read as a request | T-000082 | Handed to a person (safe); no injected instruction obeyed | Phase 3 injection suite |
| Boundary definition | T-000091 | Policy counts to the request day, the dataset to its snapshot | Documented; dataset unchanged |
| Must-escalate tickets only routed | 11 tickets | Reach a person, not the senior queue | Phase 3 policy engine |
| Misread category | 12 of 150 | Mostly "other" read as product_info; handed to a person | Held-out measure |

## 6. Limitations
- One reviewer, who also built the system; ratings are blind to labels but not independent, and two were amended after discussion.
- Development split only. Thresholds, prompts and note wording were tuned on these tickets, so the figures are optimistic; the held-out split is opened once, in Phase 4.
- Data and probes are synthetic and written by the system's author.
- Small samples: eight policy-question tickets, four knowledge answers, three tickets affected by the routing option, 30 reviewed cases.
- The validator checks named rules, not the truth of every sentence; a reversed claim can pass.
- The 3B and 7B runs differ in read prompt as well as model.
- Single CPU laptop; latency does not transfer. No time-saving claim is made.

## 7. Carry-forward items
| Item | Phase |
|---|---|
| Note wording when the order has a single item | 3 |
| Policy engine for the 11 must-escalate tickets, T-000045 and injection tickets | 3 |
| MCP adapter and Actions server (write tools disabled by default) | 3 |
| Held-out evaluation, second reviewer, shadow mode, business case | 4 |
| README test count and evidence links; remove old smoke-test scripts | 5 |

## 8. Recommendation
Keep qwen2.5:7b as the default (ADR-007) and llama3.2:3b as the fast development model. Use `--knowledge --knowledge-first --transactions` as the standard configuration (ADR-010). Phase 2 is closed (exit review); begin Phase 3 with the policy engine.
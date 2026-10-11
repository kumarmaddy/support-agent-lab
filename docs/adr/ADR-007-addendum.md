# ADR-007 Addendum: 3B and 7B compared on the Phase 2 scope

- Date: 2026-10-11
- Owner: Kumar Maddipatla, Project Lead
- Status: ADR-007 stands (qwen2.5:7b is the default; llama3.2:3b is the fast development model)

## Evidence (development split, 150 tickets, Set A 125, Set B 25)
| | 3B (read v3) | 7B (read v4) |
|---|---|---|
| Set A end to end | 114/125 (91.2%) | 118/125 (94.4%), p = 0.289 |
| Facts correct | 116/125 | 123/125, p = 0.016 (7B better) |
| Legal flag: found / false alarms | 4/4 / 0 | 4/4 / 1 |
| Set B wrongly answered | 0/25 | 0/25 |
| Knowledge answers, citations correct | 6 of 6 | 4 of 4 |
| Model replies rejected, template used | 11/35 (31%) | 3/35 (9%) |
| Latency per ticket, median / p90 | 6.9 / 16.4 s | 13.9 / 27.2 s |
| Cost | $0 | $0 |

## Decision
No change. The models are not reliably different on actions; 7B states facts more accurately and needs far fewer replacements of its drafts, while 3B takes half the time and raised no legal false alarm. Every 3B miss was a hand-over, not a wrong answer.

## Consequences
- The two read prompts differ (v3, v4), so the comparison covers model and prompt together.
- The 3B check gate answered two policy questions that 7B handed over; both citations were correct. Six answers cannot show whether a more permissive check stays correct.
- Re-test on the held-out split in Phase 4. Reverse the decision if the held-out results favour 3B, or if 7B shows more unnecessary escalations or wrong answers there.
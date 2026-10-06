# Ticket Priority Rubric

| | |
|---|---|
| Version | 1.0 |
| Date | 2026-10-06 |
| Owner | Support Operations (maintained by Kumar Maddipatla, Project Lead) |
| Status | Approved |

Change control: every change increments the version, is recorded in the change log, and requires
relabelling affected tickets before the next evaluation run. The rubric is never altered to improve
model results.

## Purpose
Defines exactly one correct priority per ticket so that the agent's prioritisation can be scored.
Priority is derived from ticket attributes, and the same attributes generate the ground-truth labels
in the synthetic dataset.

## Levels
| Priority | Definition |
|----------|------------|
| HIGH | Money or security is at risk; a legal, chargeback or regulatory threat is made; or the customer states a hard deadline within 3 days |
| MEDIUM | The company has failed a commitment or the customer is blocked: order late past the promised date; damaged or wrong item; customer locked out of their account |
| LOW | General questions, how-to, voluntary returns or exchanges, non-urgent changes, feedback |

## Rules
1. Assign the highest level whose definition matches.
2. For tickets with several issues, priority follows the most severe issue.
3. When genuinely unsure between two levels, choose the higher.
4. Priority is independent of customer tone. A stated threat or deadline raises priority; anger alone does not.
5. Priority is independent of category. A refund request may be HIGH or LOW depending on the facts.

## Attribute triggers (used by the data generator)
| Attribute | Priority |
|-----------|----------|
| duplicate_or_unauthorized_charge = true | HIGH |
| account_compromise_suspected = true | HIGH |
| chargeback_or_legal_threat = true | HIGH |
| deadline_within_3_days = true | HIGH |
| order_late_past_promise = true | MEDIUM |
| item_damaged_or_wrong = true | MEDIUM |
| account_locked_out = true | MEDIUM |
| none of the above | LOW |

## Examples (synthetic)
| Ticket | Priority | Basis |
|--------|----------|-------|
| "I was charged twice for order #2201, please refund the duplicate." | HIGH | Duplicate charge |
| "Someone changed my email and I did not do it." | HIGH | Account compromise |
| "I need this jacket for a trip on Friday and it has not shipped." (today is Wednesday) | HIGH | Deadline within 3 days |
| "My order was due Monday and still has not arrived." | MEDIUM | Late past promise |
| "I cannot log in and the reset email never comes." | MEDIUM | Locked out |
| "The item arrived cracked." | MEDIUM | Damaged item |
| "The jacket is too small, how do I exchange it?" | LOW | Voluntary exchange |
| "Do you sell gift cards?" | LOW | General question |
| "Where is my order?" (ordered yesterday; delivery promised in 5 days) | LOW | Not yet late |

## Edge cases to include in the dataset
- Angry tone without a qualifying trigger: priority follows the attributes.
- Deadline stated but more than 3 days away: not HIGH on that basis.
- Multiple issues (late order plus duplicate charge): HIGH.
- Ambiguous urgency ("soon", "as soon as possible"): no deadline trigger; recorded as an ambiguity case.

## Change log
- 1.0 (2026-10-06): initial approved version.
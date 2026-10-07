# ADR-004: Refund approval thresholds

- Status: Accepted
- Date: 2026-10-07
- Owner: Kumar Maddipatla, Project Lead
- Related: charter objective O2 (wrong-action rate), spec FR-5, FR-6, FR-7, NFR-4, NFR-6; data design sections 3 and 6; risk register (wrong refund or account change)

## Context
The policy engine (FR-6) decides, from rules held in configuration and not in prompts, whether a proposed action is
auto-executed, sent for human approval, or denied. Refunds are the one action type with direct financial exposure, so
the amount limits must be fixed before the engine, the approval service (FR-7) and the evaluation harness are built.

The company is fictional and no real approval limits exist. The limits are therefore a stated risk position, defended by
reasoning about exposure, not fitted to the generated data. The development split was used only to describe the scale of
amounts (below). The held-out split was not consulted.

Facts about the development dataset (150 tickets, full-order refunds only, amounts in USD):
- 20 tickets expect a `propose_refund` action. Their refund amounts range from $14.99 to $414.98; the median is about $113.
- Cumulative count at or below a limit: $25 → 1, $50 → 3, $75 → 4, $100 → 7, $150 → 11, $250 → 18 (of 20).
- The four adversarial tickets that expect a refund (S24, S26) have amounts of $84.99 or more.

## Options considered
| Option | Rule | Assessment |
|--------|------|------------|
| A. Approve everything | Every refund needs a human | Safest, but the agent never completes a refund; no automation value for this action type |
| B. Low limit | Auto-approve up to $50 when all conditions hold | Bounded exposure per action; automates the clearest small cases |
| C. Medium limit | Auto-approve up to $100 | Doubles automation of refund tickets (3 → 7 of 20) but includes amounts near the lowest adversarial case ($84.99) |
| D. Tiered by customer tier | Higher limit for loyal customers | Rejected for v1: adds a fairness and testing burden and the policy table has no tier-based refund rule |

## Decision
Option B, with a second approval tier and mandatory conditions.

| Refund amount | Decision (when all conditions below hold) |
|---------------|--------------------------------------------|
| up to and including $50.00 | Eligible for auto-approval |
| above $50.00, up to and including $250.00 | Requires approval by a support agent |
| above $250.00 | Requires approval by a support lead |

Amounts are compared in integer cents: 5,000 and 25,000. The boundary values belong to the lower tier.

Conditions for any approval tier (the refund is denied, or sent for escalation, if one fails):
1. The refund equals the full amount of a captured payment on an order belonging to the verified customer.
2. The order is within the policy basis for the refund: return received and refund pending, a duplicate charge flagged in
   the payment data, or a damaged or wrong item within 30 days of delivery. Final-sale items are not refundable under the
   return rule.
3. No refund already exists for that payment (idempotency; NFR-4).
4. The customer account is active and the requester is the account holder.

Conditions for auto-approval only (the refund goes to approval if one fails):
5. The customer has had fewer than 2 refunds in the previous 90 days.
6. The ticket is not flagged as adversarial or as a chargeback or legal threat (these are always escalated).
7. The decision rests on facts read from the database, never on a claim or an instruction in the ticket text.

Rollout: until Phase 4 the agent runs in shadow mode and every refund is sent for approval regardless of amount. The
$50 limit applies only to the limited auto-resolve stage of Phase 4, and is reviewed before that stage starts.

## Rationale
- **Bounded exposure.** The worst-case loss from an incorrect auto-approval is the limit. At $50, even a wrong decision on every
  auto-approved development ticket would cost at most 3 × $50 = $150 (in fictional dollars), and a single error is capped.
- **Objective O2 allows no wrong consequential action on the seeded suite.** A low limit keeps the number of
  decisions that rest on the agent alone small, so the O2 evidence is easier to inspect, while the second tier keeps larger
  amounts in front of a person.
- **Separation from the attack surface.** No adversarial ticket that expects a refund in the development set is at or below $50, so the
  highest-risk tickets can never be auto-approved on amount alone. Conditions 6 and 7 cover attacks with low amounts.
- **Evidence over assertion.** The conditions use only fields the data already holds (payments, refunds, returns, shipments,
  customer status), so the policy engine can decide deterministically and the decision can be explained (NFR-6).
- **Cost of caution is explicit.** At $50 only 3 of 20 refund-action tickets (15%) are eligible for auto-approval. The O1 target
  (60% autonomous resolution) is measured across all in-scope categories, and most categories involve no financial action,
  so the limit does not make the target unreachable. If Phase 4 shows the limit is the binding constraint, the next step is
  a review of option C, recorded in a new ADR with evidence from the pilot.

## Consequences
- The policy engine reads two numbers and one count from configuration (`auto_limit_cents`, `lead_limit_cents`,
  `max_recent_refunds`), so changing the limits does not change code.
- Expected policy outcomes are derived by the same rules and are not stored in the labels, so the frozen dataset
  (version 1.0.0) is unchanged. The evaluation harness checks the engine against an independent implementation of these rules.
- Tests required in Phase 2 include the boundary values (5,000 and 5,001 cents; 25,000 and 25,001 cents), a second refund
  on the same payment, a final-sale item, and each auto-approval condition failing in turn.
- The support lead owns the limits (charter, stakeholders). A change needs a new ADR that supersedes this one.

## Assumptions and limitations
- The company, amounts and policies are fictional; the limits show the reasoning method, not an industry benchmark.
- Partial refunds are out of scope (data design, section 4a), so the rule covers full-order refunds only.
- The dataset has a small refund sample (20 tickets); the sensitivity figures describe the scale of amounts and are not a basis for tuning.

## Note on numbering
The shared foundations document lists ADR-004 as the vector-store choice. For this project the number was committed to the
refund thresholds in the data design before that choice arose. The vector-store decision will take the next free number.
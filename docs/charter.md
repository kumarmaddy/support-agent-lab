# Project Charter: Customer Support Resolution Agent (Proof of Concept)

| | |
|---|---|
| Version | 1.0 |
| Date | 2026-10-06 |
| Prepared by | Kumar Maddipatla, Project Lead |
| Status | Approved |

## 1. Purpose
Design, build and evaluate an AI-assisted resolution system for customer support tickets, using a
fictional online retailer ("NorthPeak Outdoors") and fully synthetic data. The proof of concept
demonstrates how routine tickets can be resolved accurately within policy, how exceptions are
escalated, and how every automated decision is governed, auditable and measured against a baseline.
The system runs entirely on local infrastructure with open-weight models, at no licensing or API cost.

## 2. Business problem
Support teams spend most of their capacity on repetitive tickets (order status, returns, refunds,
account changes). Response times are slow, answers vary between agents, and routine volume crowds out
complex cases. The business needs a way to resolve routine tickets quickly and consistently, escalate
the rest with a useful summary, and keep a complete audit trail for compliance review.

## 3. Objectives and success metrics
Targets are initial hypotheses. They will be re-baselined at the end of Phase 0 and Phase 1 and any
change is recorded through an Architecture Decision Record (ADR).

| ID | Objective | Metric | Initial target |
|----|-----------|--------|----------------|
| O1 | Resolve routine tickets without human handling | Autonomous resolution rate (in-scope categories) | >= 50% |
| O2 | Prevent incorrect consequential actions | Wrong-action rate (refund, account change) | 0 on test suite |
| O3 | Escalate correctly | Escalation precision / recall | >= 85% / >= 95% |
| O4 | Ground answers in policy | Citation validity | >= 95% |
| O5 | Classify and prioritise accurately | Category accuracy / priority accuracy (rubric v1.0) | >= 90% / >= 80% |
| O6 | Resist hostile input | Prompt-injection resistance on seeded attacks | 100% |
| O7 | Operate within resource limits | Time per ticket on target hardware; infrastructure cost | Measured; cost $0 |
| O8 | Demonstrate business value | Handling time and cost per ticket, before vs after (assumptions stated) | Reported with sensitivity analysis |

## 4. Scope
**In scope:** ticket classification and prioritisation; knowledge-base answers with citations; order
and account lookups; proposed actions (refund, replacement, address change, cancellation); policy
engine; human approval workflow; escalation summaries; audit log; evaluation framework.

**Out of scope (v1):** cloud hosting or paid services; real customer data; voice and chat channels;
multilingual support; model fine-tuning; autonomous action outside policy checks; integration with
real payment systems.

## 5. Stakeholder roles
Roles are modelled within the proof of concept.

| Role | Responsibility |
|------|----------------|
| Sponsor / Project Lead (Kumar Maddipatla) | Scope, delivery, decisions, outcome reporting |
| Support Operations | Owns the priority rubric, response policies and approval thresholds |
| Approver | Reviews and approves proposed consequential actions |
| Risk and Compliance | Reviews audit trail, controls and security test results |

Evaluation is performed by the project team. Independent external review is not in scope for v1, and
results will be reported accordingly.

## 6. Approach and phases
| Phase | Focus |
|-------|-------|
| 0 | Discovery, baseline, data design |
| 1 | Thin vertical slice (order-status tickets) with tracing and first evaluation |
| 2 | Capability build (knowledge base, returns, refunds, cancellations) and evaluation growth |
| 3 | Governance hardening (policy engine, approvals, audit, security testing) |
| 4 | Measurement against baseline on a held-out test set |
| 5 | Outcome report, demonstration and handover documentation |

A phase closes only when its exit criteria are evidenced in the repository documentation.

## 7. Constraints and assumptions
- Infrastructure: single Windows laptop, 16 GB RAM, no GPU; models up to about 7B parameters (ADR-003).
- Budget: $0. Open-weight models served locally; public GitHub repository; synthetic data only.
- Ground-truth labels are generated from scenario attributes and the approved priority rubric. Models
  never produce ground truth.
- The held-out test set is not used for tuning before Phase 4.
- A labour cost per minute is assumed for the business case and labelled as an assumption.
- Small local models are expected to be less accurate than large hosted models. The gap will be
  measured and reported.

## 8. Deliverables
Working system and source repository; synthetic dataset and generator; evaluation suite and reports;
ADRs; risk register; baseline report; business case; outcome report; 5-minute demonstration; README
structured as a project brief.

## 9. Milestones
| Milestone | Target |
|-----------|--------|
| Environment ready; provisional model selection (ADR-003) | Complete (2026-10-06) |
| Phase 0 exit: charter, risk register, rubric, dataset v1, baseline report | Week 2 |
| Phase 1 exit: order-status slice and 30-ticket evaluation | Week 4 |
| Phase 2 exit | Week 7 |
| Phase 3 exit | Week 9 |
| Phase 4 exit | Week 10 |
| Phase 5 exit: outcome report and demonstration | Week 11 |

## 10. Governance
- Decisions are recorded as ADRs in `docs/adr`.
- Scope changes require a charter version increment.
- Work is tracked as GitHub issues linked to requirement IDs on a project board.
- A status note is produced weekly (progress, risks, next steps).
- Phase gates require documented evidence.

## 11. Approval
Approved by: Kumar Maddipatla, Project Lead. Date: 2026-10-06.
# ADR-013: The approval service is a local standard-library web page

- Status: Accepted (2026-10-12)
- Owner: Kumar Maddipatla, Project Lead

## Context
Phase 3 decision (2026-10-11): approval is always required in v1, through a local web page. The project runs on one 16 GB laptop, with no server and no accounts.

## Options
1. A web framework (Flask, FastAPI) with a login.
2. A standard-library page bound to loopback, name and role fixed at start.
3. A command-line prompt.

## Decision
Option 2. `http.server` adds no dependency and starts instantly; a form page shows the ticket, reason, rule and effect together, which a prompt cannot. Safety comes from loopback binding, Host and Origin checks, a per-start token, escaping everything, and a policy that forbids scripts.

## Consequences
- No authentication: the approver's identity is a start-up argument. This is stated in the design (5.5) and is unsuitable for more than one person.
- Approval and execution are separate steps and separate audit events.
- Reversal trigger: a second approver, a shared machine, or any real customer data requires a framework with authentication, and a revision of this ADR.
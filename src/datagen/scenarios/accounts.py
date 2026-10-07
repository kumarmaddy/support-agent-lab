"""Scenario family: account problems and general questions (S17-S20).

None of these tickets refers to an order. The sender is identified by the ticket's email address.
"""
import random

from .scenario_base import (GeneratedTicket, Phrasing, ScenarioContext, ScenarioDef,
                            build_account_ticket, calm)

ACCOUNT_SUBJECTS = ["Can't log in", "Problem with my account", "Account help", "Sign-in problem"]
SECURITY_SUBJECTS = ["Urgent: account security", "Someone else is using my account",
                     "Suspicious activity on my account", "Please secure my account"]
QUESTION_SUBJECTS = ["Quick question", "Question before I order", "Question about your policies",
                     "A question for you"]


def _locked_ids(sctx: ScenarioContext) -> list[str]:
    return sorted(cid for cid, c in sctx.customers.items() if c[5] == "locked")


def _active_id(sctx: ScenarioContext, rng: random.Random) -> str:
    return rng.choice(sorted(cid for cid, c in sctx.customers.items() if c[5] == "active"))


# ------------------------------------------------------------------ S17 locked out
_S17_LOCKED = [     # the customer's account really is locked in the database
    Phrasing("My account says it's locked and I can't sign in. How do I get back in?"),
    Phrasing("I tried my password a few times and now the site says my account is locked. What should I do?"),
    Phrasing("I'm locked out of my account after too many sign-in attempts. Can you unlock it?"),
    Phrasing("I can't log in. It says my account has been locked."),
]
_S17_NO_EMAIL = [   # the account is active, but the reset email never arrives
    Phrasing("I can't log in and the password reset email never arrives. I've checked my spam folder."),
    Phrasing("I requested a password reset three times and no email has come through. Please help me get "
             "into my account."),
    Phrasing("The reset link email isn't coming. I'm locked out and need to get into my account."),
]


def build_s17(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    locked = i < len(_S17_LOCKED)
    if locked:
        customer_id, phrasing = _locked_ids(sctx)[i], _S17_LOCKED[i]
    else:
        customer_id, phrasing = _active_id(sctx, rng), _S17_NO_EMAIL[i - len(_S17_LOCKED)]
    return build_account_ticket(
        sctx, rng, scenario_id="S17", customer_id=customer_id, phrasing=phrasing,
        subjects=ACCOUNT_SUBJECTS, category="account", flags={"account_locked_out": True},
        actions=["provide_info"], kb_ids=["KB-ACC-02", "KB-ACC-01"] if locked else ["KB-ACC-01"],
        facts={"account_status": "locked" if locked else "active", "self_service_reset_available": True})


# ------------------------------------------------------------------ S18 suspected compromise
_S18 = [
    Phrasing("I got an email saying my password was changed, but I didn't change it. I think someone "
             "else has access to my account."),
    Phrasing("Someone has changed the email address on my account and I did not do it."),
    Phrasing("I'm seeing sign-in alerts from a device and location I don't recognise. I think my account "
             "has been hacked."),
    Phrasing("My account shows a shipping address I never entered. I think someone logged in as me."),
    Phrasing("I received a notification that my account was accessed from a new device. It wasn't me. "
             "Please secure my account."),
]


def build_s18(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_account_ticket(
        sctx, rng, scenario_id="S18", customer_id=_active_id(sctx, rng), phrasing=_S18[i % len(_S18)],
        subjects=SECURITY_SUBJECTS, category="account", flags={"account_compromise_suspected": True},
        actions=["escalate_human"], kb_ids=["KB-ACC-03"], facts={"account_status": "active"},
        escalate_reason="suspected_account_compromise")


# ------------------------------------------------------------------ S19 knowledge-base questions
# (phrasing, KB ids, facts). Facts restate the published policy so replies can be checked against it.
_S19 = [
    (Phrasing("What is your return policy?"), ["KB-RET-01"],
     {"topic": "return_policy", "return_window_days": 30}),
    (Phrasing("How long does delivery usually take once an order has shipped?"), ["KB-SHP-01"],
     {"topic": "delivery_time", "delivery_days_after_dispatch_min": 3, "delivery_days_after_dispatch_max": 7}),
    (Phrasing("How long does it take to get my money back after I send something back?"), ["KB-REF-01"],
     {"topic": "refund_time", "refund_days_after_return_received_min": 5,
      "refund_days_after_return_received_max": 7}),
    (Phrasing("Can I change my delivery address after I place an order?"), ["KB-ADR-01"],
     {"topic": "address_change_policy", "allowed_before_dispatch_only": True}),
    (Phrasing("Can I return something I bought on final sale?"), ["KB-RET-03"],
     {"topic": "final_sale_policy", "returnable": False}),
    (Phrasing("How should I wash and look after a down sleeping bag?"), ["KB-CAR-01"],
     {"topic": "care_instructions"}),
    (Phrasing("I'm between two sizes in hiking boots. How does your sizing usually run?"), ["KB-SIZ-01"],
     {"topic": "sizing"}),
]


def build_s19(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    phrasing, kb_ids, facts = _S19[i % len(_S19)]
    return build_account_ticket(
        sctx, rng, scenario_id="S19", customer_id=_active_id(sctx, rng), phrasing=calm(rng, phrasing),
        subjects=QUESTION_SUBJECTS, category="product_info", flags={}, actions=["provide_info"],
        kb_ids=kb_ids, facts=facts)


# ------------------------------------------------------------------ S20 not in the knowledge base
_S20 = [
    "Do you sell gift cards?",
    "I run a small outdoor shop and would like to buy your jackets wholesale. Who should I speak to?",
    "Do you have a physical store in Denver where I can try boots on?",
    "I make hiking videos and would like to discuss a partnership. Who handles sponsorships?",
    "Which tent would you recommend for a winter mountaineering expedition?",
]


def build_s20(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_account_ticket(
        sctx, rng, scenario_id="S20", customer_id=_active_id(sctx, rng),
        phrasing=calm(rng, Phrasing(_S20[i % len(_S20)], difficulty="edge")), subjects=QUESTION_SUBJECTS,
        category="other", flags={}, actions=["escalate_human"], kb_ids=[],
        facts={"topic": "not_covered_by_knowledge_base"}, escalate_reason="not_in_knowledge_base")


SCENARIOS = [
    ScenarioDef("S17", "Locked out or password reset", 7, build_s17),
    ScenarioDef("S18", "Suspected account compromise", 5, build_s18),
    ScenarioDef("S19", "Knowledge-base question", 7, build_s19),
    ScenarioDef("S20", "Out of scope or not in knowledge base", 5, build_s20),
]
"""Pipeline step 5: draft the reply (phase-1-design.md, sections 2, 5 and 6).

Who writes what:
- Code writes the greeting and the sign-off, and the whole reply whenever the action is to hand the ticket to a person.
- The model writes only the short body of an information or information-request reply, from verified facts and an
  instruction. It never sees the ticket text, so ticket text cannot steer the reply (risk R9).
- Every body is validated (``validate.py``). A failed draft is retried once with a different seed; a second failure uses the
  template body built by code. The template passes the same validator, which a test enforces.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.agent import decide as d
from src.agent.model import ModelClient, ModelResponse
from src.agent.prompting import Prompt
from src.agent.validate import MAX_CHARS, ReplyFacts, missing_facts, validate_knowledge_reply, validate_reply

MAX_TOKENS = 220
SIGN_OFF = "Kind regards,\nCustomer Support"
REPLY_SCHEMA = {
    "type": "object",
    "properties": {"body": {"type": "string", "maxLength": MAX_CHARS}},
    "required": ["body"],
    "additionalProperties": False,
}
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


def fmt_date(iso: str) -> str:
    day = date.fromisoformat(iso[:10])
    return f"{_MONTH_NAMES[day.month - 1]} {day.day}, {day.year}"


def first_name(full_name: Optional[str]) -> str:
    words = re.sub(r"[^A-Za-z' -]", "", full_name or "").split()
    return words[0][:30] if words else ""


# ------------------------------------------------------------------ what each decision may say
def facts_for(decision: d.Decision) -> ReplyFacts:
    f = decision.facts
    if decision.action not in (d.PROVIDE_INFO, d.REQUEST_INFO):
        return ReplyFacts()
    if decision.action == d.REQUEST_INFO:
        ids = frozenset(c["order_id"] for c in f.get("candidates", []))
        return ReplyFacts(allowed_ids=ids, must_include=tuple(sorted(ids)))
    dates, tokens, must = {date.fromisoformat(f["promised_date"])}, set(), [f["order_id"]]
    if "delivered_date" not in f:                       # a delivered order is reported by its delivery date alone
        must.append(fmt_date(f["promised_date"]))
    if "tracking_no" in f:
        tokens.add(f["tracking_no"])
        must += [f["carrier"], f["tracking_no"]]
    if "delivered_date" in f:
        dates.add(date.fromisoformat(f["delivered_date"]))
        must.append(fmt_date(f["delivered_date"]))
    if decision.reason == "shipped_late":                 # a past date must be described as the promised date, not an expected one
        must.append("promised")
    return ReplyFacts(frozenset(dates), frozenset({f["order_id"]}), frozenset(tokens), tuple(must),
                      delivery_dates_only=f.get("status") == "processing")


def _candidate_text(candidates: list) -> str:
    return "; ".join(f'{c["order_id"]} ({", ".join(c["items"])})' if c.get("items") else c["order_id"] for c in candidates)


def render_facts(decision: d.Decision) -> str:
    f, lines = decision.facts, []
    if "order_id" in f:
        lines.append(f"Order number: {f['order_id']}")
        lines.append(f"Promised delivery date: {fmt_date(f['promised_date'])}")
    if "tracking_no" in f:
        lines += [f"Carrier: {f['carrier']}", f"Tracking number: {f['tracking_no']}", f"Latest tracking status: {f['last_status']}"]
    if "delivered_date" in f:
        lines.append(f"Delivered on: {fmt_date(f['delivered_date'])}")
    if f.get("candidates"):
        lines.append(f"Orders to choose from: {_candidate_text(f['candidates'])}")
    return "\n".join(lines) if lines else "(none)"


INSTRUCTIONS = {
    "order_processing": "The order has not been dispatched yet, so there is no tracking number. Give the promised delivery date.",
    "shipped_on_time": "The order has been dispatched. Give the carrier, the tracking number, the latest tracking status and the promised delivery date.",
    "shipped_late": ("The order is taking longer than promised. Apologise briefly. Give the carrier, the tracking number, the latest "
                     "tracking status and the promised delivery date, and say we are checking with the carrier. Do not give a new date."),
    "delivered": "Our records show the order was delivered. Give the delivery date.",
    "needs_order_number": "Ask which order they mean. List the orders to choose from, and ask them to reply with the order number.",
    "multiple_order_ids": "They mentioned more than one order. Ask which one they mean, naming the orders listed.",
    "order_not_found": "We could not find that order on the account. Ask them to check the order number in their confirmation email and reply with it.",
    "no_account": "We could not match the email address to an account. Ask them to reply with their order number.",
    "no_open_orders": "We could not see an open order on the account. Ask them to reply with the order number they mean. Do not name any order.",
    "address_missing": "Ask them to reply with the complete new delivery address for the order listed.",
}

# Template bodies: used for every hand-over, and as the fallback when a drafted body fails validation.
def template_body(decision: d.Decision) -> str:
    f, reason = decision.facts, decision.reason
    if reason == "order_processing":
        return (f"Your order {f['order_id']} has not been dispatched yet, so there is no tracking number at the moment. "
                f"The promised delivery date is {fmt_date(f['promised_date'])}.")
    if reason in ("shipped_on_time", "shipped_late"):
        lead = (f"Thank you for your patience, and we are sorry that order {f['order_id']} is taking longer than promised. "
                f"The promised delivery date was {fmt_date(f['promised_date'])}. We are checking with the carrier."
                if reason == "shipped_late" else
                f"Your order {f['order_id']} has been dispatched. The promised delivery date is {fmt_date(f['promised_date'])}.")
        return (f"{lead} The carrier is {f['carrier']}, the tracking number is {f['tracking_no']} "
                f"and the latest status is: {f['last_status']}.")
    if reason == "delivered":
        return f"Our records show that order {f['order_id']} was delivered on {fmt_date(f['delivered_date'])}."
    if reason in ("needs_order_number", "multiple_order_ids"):
        return (f"So that we look at the right order, please reply with the order number you mean. "
                f"The orders we can see are: {_candidate_text(f['candidates'])}.")
    if reason in ("order_not_found", "no_account", "no_open_orders"):
        return ("We could not find that order. Please check the order number in your confirmation email and reply with it, "
                "so that we can look into it.")
    if reason == "item_unclear":
        c = f["candidates"][0]
        return f"So that we arrange this correctly, please reply with the item you mean from order {c['order_id']}: {', '.join(c['items'])}."
    if reason == "size_missing":
        return f"So that we can arrange the exchange, please reply with the new size you would like for the {f['item']} in order {f['order_id']}."
    if reason == "return_label":
        return (f"Thank you for your message. Order {f['order_id']} was delivered on {fmt_date(f['delivered_date'])}, which is within our "
                f"{f['return_window_days']}-day return window, so {'the ' + f['item'] if f.get('item') else 'your order'} can be returned. We have passed your request to a colleague, "
                "who will email you a free return label.")
    if reason == "return_window_closed":
        what = "exchange" if f["request_kind"] == "exchange" else "return"
        return (f"Thank you for your message. Order {f['order_id']} was delivered on {fmt_date(f['delivered_date'])}. Our {what} window is "
                f"{f['return_window_days']} days from delivery, so we are not able to accept this {what}. We are sorry that we cannot help with this.")
    if reason == "return_final_sale":
        return (f"Thank you for your message. The {f['item']} in order {f['order_id']} was marked final sale when it was bought, so it cannot "
                "be returned or exchanged. We are sorry that we cannot accept it back.")
    if reason == "exchange_within_window":
        return (f"Thank you for your message. Order {f['order_id']} was delivered on {fmt_date(f['delivered_date'])}, which is within our "
                f"{f['return_window_days']}-day window, so the {f['item']} can be exchanged. You asked for size {f['requested_size']}. "
                "We have passed your request to a colleague, who will confirm that it is available and arrange the exchange with you.")
    if reason == "replacement_within_window":
        return (f"We are sorry that there is a problem with order {f['order_id']}. We have passed your request for a replacement to a "
                "colleague, who will confirm it with you.")
    if reason == "address_missing":
        return f"So that we can change the delivery address, please reply with the complete new address for order {f['candidates'][0]['order_id']}."
    if reason == "cancellation_before_dispatch":
        return (f"Thank you for your message. Order {f['order_id']} has not been dispatched yet, so it can still be cancelled. "
                "We have passed your request to a colleague, who will confirm the cancellation with you.")
    if reason == "cancellation_after_dispatch":
        return (f"Thank you for your message. Order {f['order_id']} has already been dispatched, so it can no longer be cancelled. "
                f"When it arrives you can return it under our return policy. The carrier is {f['carrier']} and the tracking number is {f['tracking_no']}.")
    if reason == "address_change_before_dispatch":
        return (f"Thank you for your message. Order {f['order_id']} has not been dispatched yet, so the delivery address can still be changed. "
                f"We have passed your request to change it to {f['requested_address']} to a colleague, who will confirm the change with you.")
    if reason == "address_change_after_dispatch":
        return (f"Thank you for your message. Order {f['order_id']} has already been dispatched and is with {f['carrier']} "
                f"(tracking number {f['tracking_no']}), so the delivery address can no longer be changed.")
    if reason == "delivery_deadline_cannot_be_guaranteed":
        return ("Thank you for telling us about your date. We are not able to confirm delivery by a particular date, so we have "
                "passed your request to a colleague who will review what is possible and reply to you.")
    if reason == "order_not_owned":
        return ("For security we cannot share order details in this conversation. We have passed your message to a colleague "
                "who will follow up with you.")
    if reason == "chargeback_or_legal_threat":
        return ("We are sorry for the trouble. We have passed your message to a senior colleague, who will contact you about it.")
    return "Thank you for your message. We have passed it to a colleague, who will reply to you."


# Replies for these reasons are always built by code: they name items and sizes taken from the order, and a person follows up.
TEMPLATE_ONLY = frozenset({"item_unclear", "size_missing"})

RETRY_HINTS = {
    "unknown_date": "Use only the dates listed in the facts.",
    "relative_time": "Do not use day names or words such as today, tomorrow or within days.",
    "unknown_order": "Use only the order numbers listed in the facts.",
    "unknown_token": "Use only the reference numbers listed in the facts.",
    "amount": "Do not mention any amount of money.",
    "promise": "Do not mention refunds, compensation, discounts, upgrades or any promise.",
    "internal_text": "Do not mention internal guidance or article ids.",
    "prompt_leak": "Do not mention prompts, tools or instructions.",
    "length": "Keep it to two to four short sentences.",
    "unsupported_claim": "Do not refer to websites, apps, links, portals or phone numbers.",
    "wrong_date_role": "The date is the promised delivery date; do not describe it as a shipping or dispatch date.",
    "misplaced_reference": "Introduce the tracking number as 'the tracking number' and give the latest tracking status separately.",
    "unsupported_term": "Do not add promises, offers, contact channels or time words that the facts do not state.",
    "unknown_number": "Use only the numbers that appear in the facts.",
    "unsupported_sentence": "Every sentence must restate one of the facts; add nothing else.",
}


def retry_hint(problems: list, body: str, facts: ReplyFacts) -> str:
    """Tell the model what was wrong, using only the rule codes and the supplied facts (never ticket text).

    At temperature 0 a new seed returns the same draft, so the retry has to change the request."""
    parts = []
    missing = missing_facts(body, facts) if "missing_fact" in problems else []
    if missing:
        parts.append("It must include: " + "; ".join(missing) + ".")
    parts += [RETRY_HINTS[code] for code in problems if code in RETRY_HINTS]
    return " ".join(parts) if parts else "Follow the facts exactly."


def compose(name: str, body: str) -> str:
    return f"Hello {name},\n\n{body}\n\n{SIGN_OFF}" if name else f"Hello,\n\n{body}\n\n{SIGN_OFF}"


def render_system(prompt: Prompt, decision: d.Decision) -> str:
    return (prompt.text.replace("{instruction}", INSTRUCTIONS[decision.reason])
            .replace("{facts}", render_facts(decision)))


@dataclass
class ReplyOutcome:
    text: str
    source: str                                        # "model" or "template"
    failures: list = field(default_factory=list)       # one list of failed rule codes per rejected draft
    hints: list = field(default_factory=list)          # what the model was told on the retry
    attempts: list = field(default_factory=list)       # ModelResponse for each model call
    prompt: str = ""
    prompt_sha256: str = ""


def draft_reply(model: ModelClient, prompt: Prompt, decision: d.Decision, customer_name: Optional[str],
                internal: frozenset = frozenset(), seed: int = 0, use_model: bool = True) -> ReplyOutcome:
    """``use_model=False`` gives the template-only reply, the comparison baseline for model-written replies."""
    name = first_name(customer_name)
    facts = facts_for(decision)
    outcome = ReplyOutcome("", "template", prompt=prompt.label, prompt_sha256=prompt.sha256)
    if use_model and decision.action in (d.PROVIDE_INFO, d.REQUEST_INFO) and decision.reason not in TEMPLATE_ONLY:
        system, request = render_system(prompt, decision), "Write the email body now."
        for attempt in range(2):
            response: ModelResponse = model.chat(system, request, REPLY_SCHEMA, seed=seed + attempt, max_tokens=MAX_TOKENS)
            outcome.attempts.append(response)
            body = response.content.get("body") if response.ok and isinstance(response.content, dict) else None
            if not isinstance(body, str):
                outcome.failures.append(["model_error"])
                continue
            body = " ".join(body.split())
            problems = validate_reply(body, facts, internal)
            if not problems:
                outcome.text, outcome.source = compose(name, body), "model"
                return outcome
            outcome.failures.append(problems)
            if attempt == 0:
                hint = retry_hint(problems, body, facts)
                outcome.hints.append(hint)
                request = f"Write the email body now. Your previous draft was rejected. {hint}"
    outcome.text = compose(name, template_body(decision))
    return outcome


# ------------------------------------------------------------------ knowledge answers
def knowledge_template_body(key_facts: list) -> str:
    return "Thank you for your question. " + " ".join(key_facts)


def draft_knowledge_reply(model: ModelClient, prompt: Prompt, decision: d.Decision, internal: frozenset = frozenset(),
                          seed: int = 0, use_model: bool = True) -> ReplyOutcome:
    """The reply to a knowledge question. The writer sees only the article's key facts, never the ticket. A draft must pass
    ``validate_knowledge_reply``; the fallback is the key facts themselves, which pass the same rules."""
    facts = decision.facts["key_facts"]
    outcome = ReplyOutcome("", "template", prompt=prompt.label, prompt_sha256=prompt.sha256)
    if use_model:
        system, request = prompt.text.replace("{facts}", "\n".join(f"- {f}" for f in facts)), "Write the email body now."
        for attempt in range(2):
            response: ModelResponse = model.chat(system, request, REPLY_SCHEMA, seed=seed + attempt, max_tokens=MAX_TOKENS)
            outcome.attempts.append(response)
            body = response.content.get("body") if response.ok and isinstance(response.content, dict) else None
            if not isinstance(body, str):
                outcome.failures.append(["model_error"])
                continue
            body = " ".join(body.split())
            problems = validate_knowledge_reply(body, facts, internal)
            if not problems:
                outcome.text, outcome.source = compose("", body), "model"
                return outcome
            outcome.failures.append(problems)
            if attempt == 0:
                hint = " ".join(RETRY_HINTS[c] for c in problems if c in RETRY_HINTS) or "Follow the facts exactly."
                outcome.hints.append(hint)
                request = f"Write the email body now. Your previous draft was rejected. {hint}"
    outcome.text = compose("", knowledge_template_body(facts))
    return outcome
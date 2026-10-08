"""The fixed pipeline for order-status tickets (phase-1-design.md, section 2; ADR-006).

    1 read the ticket (model)  ->  2 check the reading (code)  ->  3 identify customer and order (code, read-only tools)
    ->  4 decide (code)  ->  5 draft the reply (model, or template)  ->  6 validate the reply (code)  ->  7 record

The pipeline reads no labels and calls no tool that writes. It returns a ``Resolution``; nothing is sent to a customer.
Each step appends a small record to ``Resolution.steps`` (name, outcome, timings, tokens); stage 1.5 writes them to disk.
"""
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.agent import decide as d
from src.agent import reading as r
from src.agent import reply as rp
from src.agent.model import ModelClient
from src.agent.prompting import Prompt
from src.agent.tools import Toolbox
from src.agent.validate import internal_shingles
from src.kb.articles import SECTION_GUIDANCE, Article


@dataclass
class Resolution:
    ticket_id: str
    action: str
    reason: str
    article: Optional[str]
    reply: str
    reply_source: str                       # "model" or "template"
    facts: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)


def internal_guidance(articles: dict[str, Article]) -> frozenset:
    """Six-word runs from the internal guidance of every article; a reply may not contain any of them."""
    return internal_shingles(a.sections.get(SECTION_GUIDANCE, "") for a in articles.values())


def _hash(*parts) -> str:
    """Short fingerprint of a step's input, so a trace can show that two runs saw the same input without storing it."""
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _step(name: str, started: float, **detail) -> dict:
    return {"step": name, "latency_ms": int((time.perf_counter() - started) * 1000), **detail}


def _model_usage(responses) -> dict:
    return {"attempts": [{"seed": x.seed, "error": x.error, "content": x.content, "latency_ms": x.latency_ms,
                          "tokens_in": x.tokens_in, "tokens_out": x.tokens_out} for x in responses],
            "model_calls": len(responses), "tokens_in": sum(x.tokens_in for x in responses),
            "tokens_out": sum(x.tokens_out for x in responses),
            "model_latency_ms": sum(x.latency_ms for x in responses),
            "model": responses[0].model if responses else "", "digest": responses[0].digest if responses else ""}


def run_ticket(box: Toolbox, model: ModelClient, read_prompt: Prompt, reply_prompt: Prompt, internal: frozenset,
               ticket_id: str, seed: int = 0, reply_mode: str = "model") -> Resolution:
    steps: list = []

    def finish(action, reason, article, text, source, facts=None):
        return Resolution(ticket_id, action, reason, article, text, source, facts or {}, steps)

    started = time.perf_counter()
    got = box.get_ticket(ticket_id)
    steps.append(_step("get_ticket", started, outcome=got.status, input_hash=_hash(ticket_id)))
    if not got.ok:
        return finish(d.ROUTE_TO_HUMAN, "ticket_not_found", None, "", "none")
    ticket = got.data

    # 1-2. read and check
    started = time.perf_counter()
    read = r.read_ticket(model, read_prompt, ticket.subject, ticket.body, seed=seed)
    steps.append(_step("read_ticket", started, outcome="ok" if read.ok else read.reason, input_hash=_hash(ticket.subject, ticket.body),
                       prompt=read.prompt,
                       prompt_sha256=read.prompt_sha256, retry_hints=read.hints, **_model_usage(read.attempts),
                       reading=None if not read.ok else {"category": read.reading.category,
                                                          "deadline_phrase": read.reading.deadline_phrase,
                                                          "legal": read.reading.mentions_chargeback_or_legal,
                                                          "order_ids": list(read.reading.order_ids)}))
    if not read.ok:
        decision = d.Decision(d.ROUTE_TO_HUMAN, "reading_failed", None)
        text = rp.compose("", rp.template_body(decision))
        return finish(decision.action, decision.reason, None, text, "template")
    reading = read.reading

    # 3. identify
    identity = None
    if d.requires_lookup(reading):
        started = time.perf_counter()
        identity = d.identify(box, ticket, reading)
        steps.append(_step("identify", started, outcome=identity.outcome,
                           input_hash=_hash(ticket.customer_email.lower(), reading.order_ids)))

    # 4. decide
    started = time.perf_counter()
    today = date.fromisoformat(ticket.received_at[:10])
    decision = d.decide(reading, identity, today)
    steps.append(_step("decide", started, input_hash=_hash(reading.category, reading.deadline_phrase, reading.mentions_chargeback_or_legal,
                                                       identity.outcome if identity else None, str(today)),
                       action=decision.action, reason=decision.reason, article=decision.article))

    # 5-6. draft and validate
    started = time.perf_counter()
    name = identity.customer.name if identity and identity.customer else None
    outcome = rp.draft_reply(model, reply_prompt, decision, name, internal, seed=seed, use_model=(reply_mode == "model"))
    steps.append(_step("draft_reply", started, input_hash=_hash(decision.reason, decision.facts), source=outcome.source, rejected_drafts=outcome.failures, retry_hints=outcome.hints,
                       prompt=outcome.prompt, prompt_sha256=outcome.prompt_sha256, **_model_usage(outcome.attempts)))
    return finish(decision.action, decision.reason, decision.article, outcome.text, outcome.source, decision.facts)
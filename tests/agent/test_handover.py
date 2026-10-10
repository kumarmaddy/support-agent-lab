"""Stage 2.6: the hand-over note (phase-2-design.md, section 5d)."""
import json
import re
from pathlib import Path

import pytest

from src.agent import decide as d
from src.agent.decide import Decision, Identity
from src.agent.handover import HANDOVER_ACTIONS, REASONS, SENIOR, STANDARD, build_handover, order_context
from src.agent.pipeline import internal_guidance, run_ticket
from src.agent.prompting import load_prompt
from src.agent.tools import Toolbox
from src.agent.tracing import TraceWriter, read_jsonl
from src.agent.transactions import Transactions
from src.evaluation.score import score_ticket
from tests.agent.support import ScriptedModel, oracle_read
from tests.agent.test_decide import CUSTOMER, reading, shipped

SRC = Path(__file__).resolve().parents[2] / "src" / "agent"
READ, REPLY = load_prompt("read_ticket", "v2"), load_prompt("reply", "v1")
TX = Transactions(load_prompt("extract_address", "v1"), load_prompt("read_request", "v1"), load_prompt("read_refund", "v1"))


def reasons_in_source():
    """Every reason string that the code attaches to a hand-over or proposal action, found by reading the source."""
    found, text = set(), "".join(p.read_text(encoding="utf-8") for p in SRC.glob("*.py"))
    for action, reason in re.findall(r'Decision\((?:d\.)?(ESCALATE_HUMAN|ROUTE_TO_HUMAN|PROPOSE_[A-Z_]+),\s*"([a-z_]+)"', text):
        found.add(reason)
    for const in re.findall(r'^(?:NOT_FOUND|UNAVAILABLE|NOT_ANSWERED)\b.*$', text, flags=re.M):
        found.update(re.findall(r'"(knowledge_[a-z_]+)"', const))
    return found


def test_every_reason_the_code_can_hand_over_has_an_explanation_and_a_next_step():
    found = reasons_in_source()
    assert len(found) >= 30 and not (found - set(REASONS)), found - set(REASONS)
    assert all(why and step for why, step in REASONS.values())


def test_the_agents_own_replies_have_no_note_and_hand_overs_and_proposals_have_one():
    answered = Decision(d.PROVIDE_INFO, "delivered", "KB-SHP-01", {"order_id": "O-000001", "promised_date": "2026-10-01", "status": "delivered"})
    assert build_handover("T-000001", "2026-10-06T09:00:00", reading(), None, answered, "model") is None
    for action in (d.REQUEST_INFO, d.DECLINE_POLICY):
        assert action not in HANDOVER_ACTIONS
    note = build_handover("T-000001", "2026-10-06T09:00:00", reading("refund"), None, Decision(d.ROUTE_TO_HUMAN, "out_of_slice", None), "template")
    assert note.queue == STANDARD and note.account == "not_looked_up" and note.records == ()
    assert "Records checked: none" in note.render()


def test_escalations_go_to_the_senior_queue_and_proposals_say_approval_is_needed():
    legal = build_handover("T-000002", "2026-10-06T09:00:00", reading("refund", legal=True), None,
                           Decision(d.ESCALATE_HUMAN, "chargeback_or_legal_threat", "KB-REF-04"), "template")
    assert legal.queue == SENIOR and legal.legal_flag and "KB-REF-04" in legal.render()
    facts = {"order_id": "O-000001", "status": "delivered", "promised_date": "2026-10-01", "duplicate_amount_cents": 5000,
             "duplicate_payment_id": "PM-000002", "approval_required": True}
    refund = build_handover("T-000003", "2026-10-06T09:00:00", reading("refund"), Identity(d.IDENTIFIED, CUSTOMER),
                            Decision(d.PROPOSE_REFUND, "duplicate_charge", "KB-REF-02", facts), "template")
    text = refund.render()
    assert refund.queue == STANDARD and refund.approval_required and "Approval: required" in text
    assert "$50.00" in text and "PM-000002" in text and refund.customer_id == "C-000001" and refund.account == "found"


def test_the_order_context_adds_the_order_to_an_escalation_that_read_no_records():
    identity = Identity(d.IDENTIFIED, CUSTOMER, order=shipped())
    context = order_context(identity)
    assert context["status"] == "shipped" and context["tracking_no"] == "TR000000000001"
    note = build_handover("T-000004", "2026-10-06T09:00:00", reading("refund", legal=True, ids=("O-000001",)), identity,
                          Decision(d.ESCALATE_HUMAN, "chargeback_or_legal_threat", "KB-REF-04"), "template", context)
    assert "Shipment: TrailExpress" in note.render() and note.order_ids == ("O-000001",)
    assert order_context(Identity(d.ORDER_NOT_OWNED, CUSTOMER)) == {} and order_context(None) == {}


# ------------------------------------------------------------------ on the development tickets
@pytest.fixture(scope="module")
def world(dev_dataset, articles):
    db, _, labels = dev_dataset
    box = Toolbox.from_path(db)
    yield box, {lab["ticket_id"]: lab for lab in labels}, internal_guidance(articles)
    box.conn.close()


TOPIC = {"S10": "status", "S21": "status", "S11": "item_refund"}


def run(world, ticket_id):
    box, by_id, internal = world
    label = by_id[ticket_id]
    topic = {"topic": TOPIC.get(label["scenario_id"], "duplicate_charge")}
    request = {"request": "return", "item": "", "requested_size": ""}
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ticket_id), extract=lambda s, u, seed: topic if '"topic"' in s else request)
    return run_ticket(box, model, READ, REPLY, internal, ticket_id, 0, "template", None, TX)


def test_a_legal_threat_note_carries_the_order_status_that_the_decision_did_not_read(world):
    res = run(world, "T-000015")                                  # S21: "still no refund ... dispute the charge"
    assert res.action == d.ESCALATE_HUMAN and res.handover["queue"] == SENIOR
    assert any("Order O-000691" in line and "returned" in line for line in res.handover["records"])
    assert "O-000691" in res.handover["order_ids"]
    assert "identify_for_summary" in [s["step"] for s in res.steps] and "get_payment_records" not in [s["step"] for s in res.steps]


def test_a_note_holds_no_ticket_text_and_no_email_address(world):
    box, by_id, _ = world
    emails = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for ticket_id in ("T-000005", "T-000015", "T-000029", "T-000045", "T-000046", "T-000091", "T-000010"):
        res = run(world, ticket_id)
        note = res.handover
        assert note, ticket_id
        text = json.dumps(note) + res.handover["why"]
        ticket = box.get_ticket(ticket_id).data
        assert not emails.search(text) and ticket.customer_email not in text
        for sentence in re.split(r"[.!?\n]", ticket.body):
            sentence = sentence.strip()
            assert len(sentence) < 25 or sentence not in text, (ticket_id, sentence)
        assert ticket.subject not in text


def test_every_handover_or_proposal_on_the_development_tickets_has_a_note_and_nothing_else_does(world):
    box, by_id, _ = world
    for ticket_id in list(by_id)[:150]:
        res = run(world, ticket_id)
        assert bool(res.handover) == (res.action in HANDOVER_ACTIONS), (ticket_id, res.action)
        if res.handover:
            assert res.handover["reason"] == res.reason and res.handover["action"] == res.action and res.handover["article"] == res.article


def test_the_amounts_and_dates_in_a_note_come_from_the_resolution_facts(world):
    res = run(world, "T-000029")
    f = res.facts
    text = "\n".join(res.handover["records"])
    assert f"${f['duplicate_amount_cents'] // 100}.{f['duplicate_amount_cents'] % 100:02d}" in text and f["duplicate_payment_id"] in text
    assert res.handover["approval_required"] is True


def test_the_note_is_written_to_the_run_folder_only_for_hand_overs(world, tmp_path):
    with TraceWriter(tmp_path, "run-test", {}) as writer:
        for ticket_id in ("T-000002", "T-000015"):
            writer.write(run(world, ticket_id))
    rows = read_jsonl(tmp_path / "run-test" / "resolutions.jsonl")
    assert ("handover" in rows[0]) == (rows[0]["action"] in HANDOVER_ACTIONS) and "handover" in rows[1]


def test_the_scorer_counts_notes_and_whether_they_name_the_labelled_order(world):
    res = run(world, "T-000029")
    label = world[1]["T-000029"]
    row = score_ticket(res.__dict__, label, "refund", False, True, True)
    assert row["note_needed"] and row["note_present"] and row["note_names_order"] is True
    stripped = {**res.__dict__, "handover": None}
    row = score_ticket(stripped, label, "refund", False, True, True)
    assert row["note_present"] is False and row["note_names_order"] is False
    other = {**res.__dict__, "handover": {**res.handover, "order_ids": ["O-999999"]}}
    assert score_ticket(other, label, "refund", False, True, True)["note_names_order"] is False
    answered = run(world, "T-000002")
    assert answered.handover is None and score_ticket(answered.__dict__, world[1]["T-000002"], "order_status", False, True, True)["note_needed"] is False


def test_the_order_the_agent_identified_is_named_even_when_the_ticket_gave_no_number():
    facts = {"order_id": "O-000001", "status": "processing", "promised_date": "2026-10-15"}
    note = build_handover("T-000005", "2026-10-06T09:00:00", reading("cancellation"), Identity(d.IDENTIFIED, CUSTOMER),
                          Decision(d.PROPOSE_CANCELLATION, "cancellation_before_dispatch", "KB-CAN-01", facts), "template")
    assert note.order_ids == ("O-000001",)
    named = build_handover("T-000005", "2026-10-06T09:00:00", reading("cancellation", ids=("O-000001",)), Identity(d.IDENTIFIED, CUSTOMER),
                           Decision(d.PROPOSE_CANCELLATION, "cancellation_before_dispatch", "KB-CAN-01", facts), "template")
    assert named.order_ids == ("O-000001",)
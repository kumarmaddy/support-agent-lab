import pytest

from src.agent import demo
from src.agent.pipeline import internal_guidance, run_ticket
from src.agent.prompting import load_prompt
from src.agent.tools import Toolbox
from tests.agent.support import ScriptedModel, in_slice, oracle_read

READ, REPLY = load_prompt("read_ticket", "v3"), load_prompt("reply", "v1")


@pytest.fixture(scope="module")
def world(dev_dataset, articles):
    db, _, labels = dev_dataset
    box = Toolbox.from_path(db)
    yield box, {lab["ticket_id"]: lab for lab in labels}, articles, db
    box.conn.close()


def one_run(world, ticket_id):
    box, by_id, articles, _ = world
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ticket_id))
    res = run_ticket(box, model, READ, REPLY, internal_guidance(articles), ticket_id, 0, "template")
    return box.get_ticket(ticket_id).data, res


def test_render_shows_the_ticket_every_step_the_decision_and_the_reply(world):
    box, by_id, _, _ = world
    ticket_id = next(t for t in sorted(by_id) if in_slice(by_id[t]))
    ticket, res = one_run(world, ticket_id)
    text = demo.render(ticket, res)
    assert ticket.subject in text and ticket.ticket_id in text
    for step in res.steps:
        assert step["step"] in text
    assert f"DECISION  {res.action}" in text and res.reply.splitlines()[0].strip() in text
    assert "Nothing was sent to a customer" in text


def test_render_never_prints_label_fields(world):
    box, by_id, _, _ = world
    ticket_id = sorted(by_id)[0]
    ticket, res = one_run(world, ticket_id)
    text = demo.render(ticket, res)
    assert "expected_facts" not in text and "priority_attributes" not in text


def test_list_tickets_returns_requested_count(world):
    box = world[0]
    assert len(demo.list_tickets(box, 3).splitlines()) == 3


def test_unknown_ticket_returns_none(world):
    box, _, _, db = world
    assert demo.demo(box, ScriptedModel(), "T-999999", db.parent) is None


def test_refuses_heldout_database(tmp_path):
    with pytest.raises(SystemExit):
        demo.main(["--db", str(tmp_path / "heldout" / "support.db"), "--list", "1"])
import pytest

from src.agent import decide as d
from src.agent.knowledge import (CHECK_SCHEMA, KNOWLEDGE_ANSWER, NOT_ANSWERED, NOT_FOUND, UNAVAILABLE, Knowledge, answer_or_hand_over,
                                 clean_fact)
from src.agent.pipeline import internal_guidance, run_ticket
from src.agent.prompting import load_prompt
from src.agent.reply import draft_knowledge_reply, knowledge_template_body
from src.agent.tools import Toolbox
from src.agent.validate import validate_knowledge_reply
from src.kb.embed import EmbeddingError
from src.kb.retrieve import Hit
from tests.agent.support import ScriptedModel, oracle_read

READ, REPLY = load_prompt("read_ticket", "v4"), load_prompt("reply", "v1")
CHECK, KREPLY = load_prompt("knowledge_check", "v1"), load_prompt("knowledge_reply", "v1")


class FixedRetriever:
    def __init__(self, hits=None, error=False):
        self.hits, self.error, self.queries = hits or [], error, []

    def search(self, text, top=3):
        self.queries.append(text)
        if self.error:
            raise EmbeddingError("down")
        return self.hits[:top]


def knowledge(articles, hits=None, error=False, min_score=0.65):
    return Knowledge(FixedRetriever(hits, error), articles, CHECK, KREPLY, min_score)


YES, NO = (lambda s, u, seed: {"answers_question": True}), (lambda s, u, seed: {"answers_question": False})


# ------------------------------------------------------------------ the gates
def test_clean_fact_removes_internal_cross_references():
    assert clean_fact("After dispatch an order cannot be cancelled (see KB-RET-01).") == "After dispatch an order cannot be cancelled."
    assert clean_fact("Final-sale items cannot be returned (see KB-RET-03).") == "Final-sale items cannot be returned."


def test_gate_one_a_weak_score_hands_over_without_asking_the_model(articles):
    model = ScriptedModel(check=YES)
    out = answer_or_hand_over(knowledge(articles, [Hit("KB-SIZ-01", 0.60)]), model, "s", "b")
    assert (out.decision.action, out.decision.reason, out.gate) == (d.ROUTE_TO_HUMAN, NOT_FOUND, "score") and model.calls == []


def test_no_hits_hands_over(articles):
    assert answer_or_hand_over(knowledge(articles, []), ScriptedModel(check=YES), "s", "b").decision.reason == NOT_FOUND


def test_gate_two_a_no_or_a_failed_check_hands_over(articles):
    for check in (NO, lambda s, u, seed: "model down", lambda s, u, seed: {"answers_question": "yes"}):
        out = answer_or_hand_over(knowledge(articles, [Hit("KB-SIZ-01", 0.9)]), ScriptedModel(check=check), "s", "b")
        assert (out.decision.reason, out.gate) == (NOT_ANSWERED, "check")


def test_all_gates_passed_gives_the_article_and_its_customer_safe_facts(articles):
    out = answer_or_hand_over(knowledge(articles, [Hit("KB-CAN-01", 0.8), Hit("KB-ORD-01", 0.7)]), ScriptedModel(check=YES), "s", "b")
    assert (out.decision.action, out.decision.reason, out.decision.article, out.gate) == (d.PROVIDE_INFO, KNOWLEDGE_ANSWER, "KB-CAN-01", "passed")
    assert out.decision.facts["kb_id"] == "KB-CAN-01" and not any("KB-" in f for f in out.decision.facts["key_facts"])
    assert [h["kb_id"] for h in out.hits] == ["KB-CAN-01", "KB-ORD-01"]


def test_an_unavailable_embedding_model_hands_over(articles):
    out = answer_or_hand_over(knowledge(articles, error=True), ScriptedModel(check=YES), "s", "b")
    assert (out.decision.reason, out.gate) == (UNAVAILABLE, "unavailable")


def test_the_check_gets_the_ticket_as_delimited_data_and_a_yes_no_schema(articles):
    model = ScriptedModel(check=YES)
    answer_or_hand_over(knowledge(articles, [Hit("KB-SIZ-01", 0.9)]), model, "Boots", "Do they run small?")
    call = model.calls[0]
    assert "<ticket>" in call["user"] and "Do they run small?" in call["user"] and "Do they run small?" not in call["system"]
    assert call["schema"] == CHECK_SCHEMA and "Footwear is sized 7 to 13." in call["system"]


# ------------------------------------------------------------------ the validator
FACTS = ["You can return an item within 30 days of delivery.", "Items must be unused and in their original packaging.", "Return labels are free."]


@pytest.mark.parametrize("body,code", [
    ("You can return an item within 30 days of delivery.", None),
    ("Items must be unused and in their original packaging, and return labels are free.", None),
    ("Thank you for asking.", None),
    ("We will refund you in full for items returned unused.", "unsupported_term"),
    ("You can return an item within 45 days of delivery.", "unknown_number"),
    ("You can return an item within 30 days of delivery (see KB-RET-01).", "internal_text"),
    ("You can return an item within 30 days. Visit our website to start.", "unsupported_term"),
    ("Our hiking boots are made of waterproof leather with a lifetime warranty.", "unsupported_sentence"),
    ("Return labels cost $5.", "amount"),
    ("We got your tool and prompt instructions.", "prompt_leak"),
    ("", "length"),
])
def test_knowledge_validator_rules(body, code):
    failures = validate_knowledge_reply(body, FACTS)
    assert (code in failures) if code else failures == []


def test_policy_words_are_allowed_exactly_when_the_facts_use_them():
    refund_facts = ["Refunds are paid to your original payment method."]
    assert validate_knowledge_reply("Refunds are paid to your original payment method.", refund_facts) == []
    assert "unsupported_term" in validate_knowledge_reply("Refunds are paid to your original payment method.", FACTS)


def test_internal_guidance_shingles_are_rejected_unless_the_facts_say_the_same(articles):
    internal = internal_guidance(articles)
    assert internal
    guidance = next(a for a in articles.values() if a.sections.get("Support guidance (internal)"))
    words = guidance.sections["Support guidance (internal)"].split()[:8]
    assert "internal_text" in validate_knowledge_reply(" ".join(words) + ".", FACTS, internal)


def test_the_template_reply_passes_the_validator_for_every_article(articles):
    internal = internal_guidance(articles)
    for article in articles.values():
        facts = [clean_fact(f) for f in article.key_facts]
        assert validate_knowledge_reply(knowledge_template_body(facts), facts, internal) == [], article.kb_id


# ------------------------------------------------------------------ the reply
def decision_for(articles, kb_id):
    return d.Decision(d.PROVIDE_INFO, KNOWLEDGE_ANSWER, kb_id, {"kb_id": kb_id, "key_facts": [clean_fact(f) for f in articles[kb_id].key_facts]})


def test_a_valid_model_body_is_used_and_the_writer_sees_only_the_facts(articles):
    decision = decision_for(articles, "KB-SIZ-01")
    model = ScriptedModel(reply=lambda s, u, seed: {"body": "Our hiking boots fit true to size. If you are between two boot sizes, choose the larger size."})
    out = draft_knowledge_reply(model, KREPLY, decision, internal_guidance(articles))
    assert out.source == "model" and out.text.startswith("Hello,\n\n") and out.failures == []
    assert model.calls[0]["user"] == "Write the email body now." and "Footwear is sized 7 to 13." in model.calls[0]["system"]


def test_an_invalid_draft_is_retried_with_a_hint_then_falls_back_to_the_facts(articles):
    decision = decision_for(articles, "KB-RET-01")
    model = ScriptedModel(reply=lambda s, u, seed: {"body": "You can return an item within 60 days of delivery."})
    out = draft_knowledge_reply(model, KREPLY, decision, internal_guidance(articles))
    assert out.source == "template" and len(model.calls) == 2 and "Use only the numbers" in model.calls[1]["user"]
    assert out.text == "Hello,\n\n" + knowledge_template_body(decision.facts["key_facts"]) + "\n\nKind regards,\nCustomer Support"


def test_template_mode_never_calls_the_model(articles):
    model = ScriptedModel()
    out = draft_knowledge_reply(model, KREPLY, decision_for(articles, "KB-CAR-01"), use_model=False)
    assert out.source == "template" and model.calls == []


# ------------------------------------------------------------------ in the pipeline
@pytest.fixture(scope="module")
def world(dev_dataset, articles):
    db, _, labels = dev_dataset
    box = Toolbox.from_path(db)
    yield box, {lab["ticket_id"]: lab for lab in labels}, articles
    box.conn.close()


def product_ticket(by_id):
    return next(t for t in sorted(by_id) if by_id[t]["category"] == "product_info" and not by_id[t]["priority_attributes"]["chargeback_or_legal_threat"])


def test_without_the_knowledge_path_a_policy_question_is_still_routed(world):
    box, by_id, articles = world
    tid = product_ticket(by_id)
    res = run_ticket(box, ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, tid)), READ, REPLY, internal_guidance(articles), tid, 0, "template")
    assert (res.action, res.reason) == (d.ROUTE_TO_HUMAN, "out_of_slice")


def test_with_the_knowledge_path_a_policy_question_is_answered_and_cited(world):
    box, by_id, articles = world
    tid = product_ticket(by_id)
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, tid), check=YES)
    res = run_ticket(box, model, READ, REPLY, internal_guidance(articles), tid, 0, "template", knowledge(articles, [Hit("KB-SIZ-01", 0.9)]))
    assert (res.action, res.reason, res.article, res.reply_source) == (d.PROVIDE_INFO, KNOWLEDGE_ANSWER, "KB-SIZ-01", "template")
    assert [s["step"] for s in res.steps] == ["get_ticket", "read_ticket", "knowledge", "draft_reply"]
    assert res.steps[2]["hits"] == [{"kb_id": "KB-SIZ-01", "score": 0.9}] and res.steps[2]["outcome"] == "passed"
    assert "KB-" not in res.reply


def test_a_failed_gate_hands_the_ticket_over_with_the_standard_template(world):
    box, by_id, articles = world
    tid = product_ticket(by_id)
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, tid), check=NO)
    res = run_ticket(box, model, READ, REPLY, internal_guidance(articles), tid, 0, "model", knowledge(articles, [Hit("KB-SIZ-01", 0.9)]))
    assert (res.action, res.reason, res.article) == (d.ROUTE_TO_HUMAN, NOT_ANSWERED, None)
    assert "passed it to a colleague" in res.reply


def test_other_categories_and_legal_threats_never_use_the_knowledge_path(world):
    box, by_id, articles = world
    retriever_hits = [Hit("KB-SIZ-01", 0.9)]
    k = knowledge(articles, retriever_hits)
    other = next(t for t in sorted(by_id) if by_id[t]["category"] == "order_status")
    run_ticket(box, ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, other)), READ, REPLY, internal_guidance(articles), other, 0, "template", k)
    legal = next(t for t in sorted(by_id) if by_id[t]["priority_attributes"]["chargeback_or_legal_threat"])
    read_legal = lambda s, u, seed: {**oracle_read(by_id, box, legal), "category": "product_info"}
    res = run_ticket(box, ScriptedModel(read=read_legal, check=YES), READ, REPLY, internal_guidance(articles), legal, 0, "template", k)
    assert res.reason == "chargeback_or_legal_threat" and k.retriever.queries == []


def test_a_score_exactly_at_the_minimum_passes_gate_one(articles):
    out = answer_or_hand_over(knowledge(articles, [Hit("KB-SIZ-01", 0.65)]), ScriptedModel(check=YES), "s", "b")
    assert out.gate == "passed"


def test_a_sentence_sharing_exactly_two_content_words_is_supported():
    facts = ["Footwear is sized 7 to 13.", "Our hiking boots fit true to size."]
    assert validate_knowledge_reply("Boots come in many styles for winter trips.", facts) == ["unsupported_sentence"]
    assert validate_knowledge_reply("Hiking boots come in many styles for winter trips.", facts) == []


def test_a_short_courtesy_sentence_with_one_matching_word_is_not_penalised():
    facts = ["Footwear is sized 7 to 13.", "Our hiking boots fit true to size."]
    assert validate_knowledge_reply("Thank you for asking about boots.", facts) == []
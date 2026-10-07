"""Tests for stage 0.5: knowledge-base articles agree with the catalogue, the policy and the labels."""
import re
from pathlib import Path

import pytest

from src.datagen import config
from src.datagen.domain.kb_catalogue import KB_ARTICLES
from src.datagen.scenarios.accounts import _S19
from src.kb.articles import REQUIRED_SECTIONS, SECTION_GUIDANCE, load_articles, parse_article

KB_DIR = Path(__file__).resolve().parents[2] / "data" / "seed" / "kb"
CATEGORY_BY_PREFIX = {"SHP": "shipping", "ORD": "orders", "RET": "returns", "REF": "refunds", "CAN": "cancellations",
                      "ADR": "address", "ACC": "account", "SIZ": "product_info", "CAR": "product_info",
                      "SEC": "privacy"}
MAX_WORDS = 250        # short articles keep retrieved context small for a CPU-run model (ADR-003)


@pytest.fixture(scope="module")
def articles():
    return load_articles(KB_DIR)


# ------------------------------------------------------------------ structure
def test_articles_match_the_catalogue_exactly(articles):
    assert set(articles) == set(KB_ARTICLES)
    for kb_id, article in articles.items():
        assert article.title == KB_ARTICLES[kb_id]
        assert article.path.name == f"{kb_id}.md"


def test_front_matter_and_sections(articles):
    for article in articles.values():
        assert article.category == CATEGORY_BY_PREFIX[article.kb_id.split("-")[1]], article.kb_id
        assert re.fullmatch(r"\d+\.\d+", article.version) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", article.effective)
        assert tuple(article.sections) == REQUIRED_SECTIONS, article.kb_id
        assert len(article.key_facts) >= 2, article.kb_id


def test_articles_are_short(articles):
    for article in articles.values():
        assert len(article.full_text.split()) <= MAX_WORDS, article.kb_id


def test_parser_rejects_bad_files(tmp_path):
    (tmp_path / "a.md").write_text("no front matter\n", encoding="utf-8")
    with pytest.raises(ValueError, match="front matter"):
        parse_article(tmp_path / "a.md")
    (tmp_path / "b.md").write_text("---\nid: KB-X\ntitle: t\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing front matter keys"):
        parse_article(tmp_path / "b.md")


# ------------------------------------------------------------------ policy facts (docs/design/data-design.md section 3)
def test_every_citable_text_uses_calendar_days(articles):
    for article in articles.values():
        text = article.full_text.lower()
        assert "business day" not in text and "working day" not in text, article.kb_id


def test_return_window_matches_the_generator(articles):
    n = config.RETURN_WINDOW_DAYS
    for kb_id in ("KB-RET-01", "KB-RET-04", "KB-REF-03"):
        assert f"within {n} days of delivery" in " ".join(articles[kb_id].key_facts), kb_id
    assert f"day {n} is still inside the window and day {n + 1} is not" in articles["KB-RET-01"].full_text
    assert "calendar days" in articles["KB-RET-01"].full_text


def test_cancellation_and_address_change_are_before_dispatch_only(articles):
    for kb_id in ("KB-CAN-01", "KB-ADR-01"):
        facts = " ".join(articles[kb_id].key_facts).lower()
        assert "before it is dispatched" in facts and "after dispatch" in facts, kb_id


# S19 labels restate published policy; each label fact must be stated in the article the label cites.
def test_s19_label_facts_are_stated_in_the_cited_articles(articles):
    for _phrasing, kb_ids, facts in _S19:
        text = articles[kb_ids[0]].full_text
        topic = facts["topic"]
        if topic == "return_policy":
            assert f"{facts['return_window_days']} days" in text
        elif topic == "delivery_time":
            low, high = facts["delivery_days_after_dispatch_min"], facts["delivery_days_after_dispatch_max"]
            assert f"{low} to {high} calendar days" in text
        elif topic == "refund_time":
            low, high = facts["refund_days_after_return_received_min"], facts["refund_days_after_return_received_max"]
            assert f"{low} to {high} calendar days" in text
        elif topic == "address_change_policy":
            assert facts["allowed_before_dispatch_only"] and "before it is dispatched" in text
        elif topic == "final_sale_policy":
            assert facts["returnable"] is False and "cannot be returned" in text
        elif topic in ("care_instructions", "sizing"):
            assert articles[kb_ids[0]].key_facts            # fictional product guidance, no numeric facts
        else:
            pytest.fail(f"unhandled S19 topic {topic}")


def test_s19_covers_every_topic_it_asserts():
    assert {facts["topic"] for _p, _k, facts in _S19} == {
        "return_policy", "delivery_time", "refund_time", "address_change_policy", "final_sale_policy",
        "care_instructions", "sizing"}


# ------------------------------------------------------------------ safety of the knowledge source itself
INJECTION_MARKERS = ["ignore previous", "ignore all previous", "disregard", "system prompt", "you are now",
                     "override", "pre-approved", "reveal your", "as an ai"]


def test_articles_contain_no_instruction_like_text_aimed_at_a_model(articles):
    """The knowledge base is a trusted source; a poisoned article would be an attack path (shared foundations, section 7)."""
    for article in articles.values():
        text = article.full_text.lower()
        for marker in INJECTION_MARKERS:
            assert marker not in text, f"{article.kb_id}: {marker!r}"


def test_internal_guidance_is_separable_from_customer_text(articles):
    for article in articles.values():
        assert article.sections[SECTION_GUIDANCE] not in article.customer_text
        assert "Support guidance" not in article.customer_text


def test_articles_reference_only_existing_articles(articles):
    for article in articles.values():
        for ref in re.findall(r"KB-[A-Z]{3}-\d{2}", article.full_text):
            assert ref in KB_ARTICLES, f"{article.kb_id} cites unknown {ref}"
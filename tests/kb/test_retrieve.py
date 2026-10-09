from src.kb.articles import Article, SECTION_DETAILS, SECTION_GUIDANCE, SECTION_KEY_FACTS
from src.kb.retrieve import Hit, build_index, confident, tokens
from pathlib import Path


def article(kb_id, title, facts, details="", guidance=""):
    return Article(kb_id, title, "x", "1.0", "2026-10-07",
                   {SECTION_KEY_FACTS: facts, SECTION_DETAILS: details, SECTION_GUIDANCE: guidance}, Path(kb_id))


SMALL = {a.kb_id: a for a in (
    article("KB-A", "Return window", "- You can return items within 30 days."),
    article("KB-B", "Sizing guide", "- Sizes run small; order one size up."),
    article("KB-C", "Refund timing", "- Refunds are paid in 5 to 7 days.", guidance="secretword only here"),
)}


def test_tokens_drop_stop_words_and_plural_endings():
    assert tokens("Hello, how are the refunds?") == ["refund"]
    assert tokens("Returning returned returns") == ["return", "return", "return"]


def test_search_ranks_the_matching_article_first():
    hits = build_index(SMALL).search("what size should I order, do they run small?")
    assert hits[0].kb_id == "KB-B"


def test_search_is_deterministic_and_limited_to_top():
    index = build_index(SMALL)
    assert index.search("return refund size", 2) == index.search("return refund size", 2) and len(index.search("return refund size", 2)) == 2


def test_internal_guidance_is_never_indexed():
    assert build_index(SMALL).search("secretword") == []


def test_no_shared_word_returns_nothing():
    assert build_index(SMALL).search("zebra quartz") == []


def test_confident_applies_score_and_margin_thresholds():
    hits = [Hit("KB-A", 5.0), Hit("KB-B", 4.5)]
    assert confident(hits, 4.0).kb_id == "KB-A"
    assert confident(hits, 6.0) is None
    assert confident(hits, 4.0, minimum_margin=1.0) is None
    assert confident([], 0.0) is None
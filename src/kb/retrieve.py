"""Lexical retrieval over the knowledge base (phase-2-design.md, section 3).

Ranks the articles for a piece of text with BM25, a standard word-matching score: a word counts more when it is rare across the
articles and when it appears often in one article, and long articles are not favoured. It needs no model and no extra package,
gives the same ranking every time, and is the baseline that any embedding approach has to beat (ADR-009).

Only the customer-facing parts of an article (title, key facts, details) are indexed. The internal guidance is never searched or
returned, so nothing in it can reach a reply by way of retrieval.
"""
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from src.kb.articles import SECTION_DETAILS, SECTION_KEY_FACTS, Article

K1, B = 1.5, 0.75
_WORD = re.compile(r"[a-z]+")
STOPWORDS = frozenset("""a about after again all also am an and any are as at be been before but by can could did do does for from get
got had has have how i if in into is it its just me my of on or our out so than that the their them then there these they this to up
us was we were what when where which who will with would you your hello hi dear thanks thank regards kind please team support
order orders""".split())


def tokens(text: str) -> list:
    """Lower-case words with common endings removed, so that "refunds" and "refund" match; stop words are dropped."""
    out = []
    for word in _WORD.findall(text.lower()):
        if word in STOPWORDS or len(word) < 2:
            continue
        for ending in ("ing", "ed", "es", "s"):
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[: -len(ending)]
                break
        out.append(word)
    return out


@dataclass(frozen=True)
class Hit:
    kb_id: str
    score: float


class Index:
    def __init__(self, articles: dict):
        self.ids = sorted(articles)
        docs = {kb_id: tokens(_indexed_text(articles[kb_id])) for kb_id in self.ids}
        self.counts = {kb_id: Counter(words) for kb_id, words in docs.items()}
        self.lengths = {kb_id: len(words) for kb_id, words in docs.items()}
        self.average = sum(self.lengths.values()) / max(len(self.ids), 1)
        document_frequency = Counter(word for c in self.counts.values() for word in c)
        n = len(self.ids)
        self.idf = {word: math.log(1 + (n - df + 0.5) / (df + 0.5)) for word, df in document_frequency.items()}

    def search(self, text: str, top: int = 3) -> list:
        """The best ``top`` articles, highest score first; articles with no word in common are left out."""
        query = set(tokens(text))
        scored = []
        for kb_id in self.ids:
            score = 0.0
            for word in query:
                tf = self.counts[kb_id].get(word, 0)
                if tf:
                    score += self.idf[word] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * self.lengths[kb_id] / self.average))
            if score > 0:
                scored.append(Hit(kb_id, round(score, 6)))
        scored.sort(key=lambda h: (-h.score, h.kb_id))
        return scored[:top]


def _indexed_text(article: Article) -> str:
    return " ".join([article.title, article.sections.get(SECTION_KEY_FACTS, ""), article.sections.get(SECTION_DETAILS, "")])


def build_index(articles: dict) -> Index:
    return Index(articles)


def confident(hits: list, minimum_score: float, minimum_margin: float = 0.0) -> Optional[Hit]:
    """The top hit if it is strong enough to answer from, otherwise None (the "I don't know" path)."""
    if not hits or hits[0].score < minimum_score:
        return None
    if len(hits) > 1 and hits[0].score - hits[1].score < minimum_margin:
        return None
    return hits[0]
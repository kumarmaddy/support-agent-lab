"""Embedding retrieval and the BM25 + embedding combination (phase-2-design.md, section 3; ADR-009).

An embedding model turns a text into a list of numbers so that texts with similar meaning are close together. Each article is
embedded once; a question is embedded at search time and the articles are ranked by cosine similarity (the angle between the two
lists of numbers; 1.0 means the same direction). The model runs locally through Ollama (``ollama pull nomic-embed-text``).

``HybridIndex`` combines two rankings by reciprocal rank fusion: an article scores 1/(60 + rank) in each ranking, and the scores are
added. It uses ranks only, so the two scoring scales never have to be reconciled.

Like the rest of the project, the client only talks to a local host. A failed call raises ``EmbeddingError`` (retrieval cannot
silently return nothing); the pipeline decides what that means.
"""
import math
import urllib.error
from typing import Callable, Optional

from src.agent.model import DEFAULT_URL, LOCAL_HOSTS, urllib_transport
from src.kb.articles import SECTION_DETAILS, SECTION_KEY_FACTS
from src.kb.retrieve import Hit
from urllib.parse import urlparse

DEFAULT_EMBED_MODEL = "nomic-embed-text"
DOCUMENT_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "     # nomic-embed-text expects these task prefixes
RRF_K = 60


class EmbeddingError(RuntimeError):
    pass


def embed_texts(texts: list, model: str = DEFAULT_EMBED_MODEL, base_url: str = DEFAULT_URL,
                transport: Callable = urllib_transport, timeout: float = 120) -> list:
    if urlparse(base_url).hostname not in LOCAL_HOSTS:
        raise ValueError("the project runs local models only")
    try:
        body = transport("POST", f"{base_url}/api/embed", {"model": model, "input": texts}, timeout)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
    vectors = body.get("embeddings")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise EmbeddingError(f"unexpected embedding response: {body.get('error', 'no embeddings')}")
    return vectors


def cosine(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class EmbeddingIndex:
    def __init__(self, articles: dict, model: str = DEFAULT_EMBED_MODEL, base_url: str = DEFAULT_URL, transport: Callable = urllib_transport):
        self.model, self.base_url, self.transport = model, base_url, transport
        self.ids = sorted(articles)
        texts = [DOCUMENT_PREFIX + " ".join([articles[i].title, articles[i].sections.get(SECTION_KEY_FACTS, ""),
                                              articles[i].sections.get(SECTION_DETAILS, "")]) for i in self.ids]
        self.vectors = dict(zip(self.ids, embed_texts(texts, model, base_url, transport)))

    def search(self, text: str, top: int = 3) -> list:
        query = embed_texts([QUERY_PREFIX + text], self.model, self.base_url, self.transport)[0]
        hits = [Hit(i, round(cosine(query, self.vectors[i]), 6)) for i in self.ids]
        hits.sort(key=lambda h: (-h.score, h.kb_id))
        return hits[:top]


class HybridIndex:
    def __init__(self, first, second, pool: int = 10):
        self.first, self.second, self.pool = first, second, pool

    def search(self, text: str, top: int = 3) -> list:
        scores: dict = {}
        for index in (self.first, self.second):
            for rank, hit in enumerate(index.search(text, self.pool), 1):
                scores[hit.kb_id] = scores.get(hit.kb_id, 0.0) + 1 / (RRF_K + rank)
        fused = sorted((Hit(i, round(s, 6)) for i, s in scores.items()), key=lambda h: (-h.score, h.kb_id))
        return fused[:top]
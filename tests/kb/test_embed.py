import pytest

from src.kb import embed
from src.kb.retrieve import Hit, build_index
from tests.kb.test_retrieve import SMALL


def fake_transport(vectors):
    """Returns the vector for each input text, chosen by a keyword in the text."""
    calls = []

    def transport(method, url, payload, timeout):
        calls.append(payload)
        return {"embeddings": [next(v for k, v in vectors if k in text) for text in payload["input"]]}
    transport.calls = calls
    return transport


VECTORS = [("Return window", [1.0, 0.0, 0.0]), ("Sizing guide", [0.0, 1.0, 0.0]), ("Refund timing", [0.0, 0.0, 1.0]),
           ("send back", [0.9, 0.1, 0.0]), ("how big", [0.1, 0.9, 0.0])]


def test_cosine_of_parallel_orthogonal_and_zero_vectors():
    assert embed.cosine([1, 2], [2, 4]) == pytest.approx(1.0)
    assert embed.cosine([1, 0], [0, 1]) == 0.0 and embed.cosine([0, 0], [1, 1]) == 0.0


def test_embedding_search_ranks_by_similarity_and_uses_task_prefixes():
    transport = fake_transport(VECTORS)
    index = embed.EmbeddingIndex(SMALL, transport=transport)
    assert index.search("how big are they", 2)[0].kb_id == "KB-B"
    assert index.search("send back", 1)[0].kb_id == "KB-A"
    assert all(t.startswith(embed.DOCUMENT_PREFIX) for t in transport.calls[0]["input"])
    assert transport.calls[1]["input"][0].startswith(embed.QUERY_PREFIX)


def test_failed_or_malformed_response_raises_embedding_error():
    with pytest.raises(embed.EmbeddingError):
        embed.embed_texts(["a"], transport=lambda *a: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(embed.EmbeddingError):
        embed.embed_texts(["a", "b"], transport=lambda *a: {"embeddings": [[1.0]]})


def test_remote_hosts_are_refused():
    with pytest.raises(ValueError):
        embed.embed_texts(["a"], base_url="http://example.com:11434", transport=lambda *a: {})


def test_hybrid_fuses_ranks_from_both_indexes():
    class Fixed:
        def __init__(self, ids):
            self.ids = ids

        def search(self, text, top=3):
            return [Hit(i, 1.0) for i in self.ids][:top]
    fused = embed.HybridIndex(Fixed(["KB-A", "KB-B"]), Fixed(["KB-B", "KB-C"])).search("x", 3)
    assert [h.kb_id for h in fused] == ["KB-B", "KB-A", "KB-C"]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61, abs=1e-6)
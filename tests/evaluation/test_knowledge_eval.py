from src.agent.knowledge import Knowledge
from src.agent.prompting import load_prompt
from src.evaluation import knowledge as ev
from src.kb.retrieve import Hit
from tests.agent.support import ScriptedModel

CHECK, KREPLY = load_prompt("knowledge_check", "v1"), load_prompt("knowledge_reply", "v1")


class ByQuestion:
    """Returns the hit configured for the question text."""
    def __init__(self, table):
        self.table = table

    def search(self, text, top=3):
        return self.table.get(text.strip(), [])


def test_probe_run_counts_right_wrong_and_handed_over(articles):
    retriever = ByQuestion({"sizes?": [Hit("KB-SIZ-01", 0.9)], "returns?": [Hit("KB-SIZ-01", 0.9)], "weak?": [Hit("KB-SIZ-01", 0.3)],
                            "gift?": [Hit("KB-SIZ-01", 0.9)], "shop?": [Hit("KB-SIZ-01", 0.2)]})
    knowledge = Knowledge(retriever, articles, CHECK, KREPLY)
    probes = [{"id": "a", "question": "sizes?", "required_kb_ids": ["KB-SIZ-01"], "answerable": True},
              {"id": "b", "question": "returns?", "required_kb_ids": ["KB-RET-01"], "answerable": True},
              {"id": "c", "question": "weak?", "required_kb_ids": ["KB-RET-01"], "answerable": True},
              {"id": "d", "question": "gift?", "required_kb_ids": [], "answerable": False},
              {"id": "e", "question": "shop?", "required_kb_ids": [], "answerable": False}]
    model = ScriptedModel(check=lambda s, u, seed: {"answers_question": True})
    rows = ev.run_probes(knowledge, model, probes, frozenset(), use_model=False)
    s = ev.summarise(rows)
    assert (s["right"], s["wrong"], s["handed_over"]["score"], s["unanswerable_answered"], s["unanswerable_handed_over"]["score"]) == (1, 1, 1, 1, 1)
    assert s["reply_sources"] == {"template": 3}
    text = ev.render(rows)
    assert "wrong answers" in text and "b ['KB-RET-01'] -> KB-SIZ-01" in text and "d (unanswerable)" in text


def test_acceptable_articles_count_as_right(articles):
    knowledge = Knowledge(ByQuestion({"q": [Hit("KB-SHP-03", 0.9)]}), articles, CHECK, KREPLY)
    probes = [{"id": "a", "question": "q", "required_kb_ids": ["KB-SHP-01"], "also_acceptable_kb_ids": ["KB-SHP-03"], "answerable": True}]
    rows = ev.run_probes(knowledge, ScriptedModel(check=lambda s, u, seed: {"answers_question": True}), probes, frozenset(), use_model=False)
    assert ev.summarise(rows)["right"] == 1
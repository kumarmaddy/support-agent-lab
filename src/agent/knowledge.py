"""Knowledge questions: retrieve an article, decide whether to answer from it (phase-2-design.md, sections 2 to 4; ADR-009).

A ticket the reader calls ``product_info`` is a question about policy, not about an order. Three gates must all pass before an
answer is sent; failing any one hands the ticket to a person and nothing is answered:

  gate 1  the best article's similarity score is at least ``min_score``
  gate 2  a model check says the article's key facts directly answer the question (the check sees the ticket text, but can only
          answer yes or no, so injected text can at worst release an answer made of the article's own key facts)
  gate 3  the reply (written from the key facts, never from the ticket) passes ``validate_knowledge_reply``; this gate is applied
          in ``reply.draft_knowledge_reply`` and falls back to the key facts themselves

The article id is the citation, and the trace records the scores and each gate.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from src.agent import decide as d
from src.agent.model import ModelClient, ModelResponse
from src.agent.prompting import Prompt
from src.kb.articles import Article
from src.kb.embed import EmbeddingError

KNOWLEDGE_ANSWER = "knowledge_answer"
NOT_FOUND, NOT_ANSWERED, UNAVAILABLE = "knowledge_not_found", "knowledge_not_answered", "knowledge_unavailable"
DEFAULT_MIN_SCORE = 0.65
CHECK_SCHEMA = {
    "type": "object",
    "properties": {"answers_question": {"type": "boolean"}},
    "required": ["answers_question"],
    "additionalProperties": False,
}
CHECK_MAX_TOKENS = 20
_SEE_REFERENCE = re.compile(r"\s*\((?:see\s+)?KB-[A-Z]{3}-\d{2}\)", re.IGNORECASE)


def clean_fact(fact: str) -> str:
    """A key fact as a customer may be shown it: without the internal "(see KB-RET-01)" cross-references."""
    return _SEE_REFERENCE.sub("", fact).strip()


@dataclass
class Knowledge:
    retriever: object                      # anything with search(text, top) -> [Hit]
    articles: dict
    check_prompt: Prompt
    reply_prompt: Prompt
    min_score: float = DEFAULT_MIN_SCORE


@dataclass
class KnowledgeOutcome:
    decision: d.Decision
    hits: list = field(default_factory=list)          # [{"kb_id", "score"}] best first
    gate: str = ""                                    # the gate that stopped it ("score", "check", "unavailable") or "passed"
    check: Optional[ModelResponse] = None


def render_check_system(prompt: Prompt, key_facts: list) -> str:
    return prompt.text.replace("{facts}", "\n".join(f"- {f}" for f in key_facts))


def answer_or_hand_over(knowledge: Knowledge, model: ModelClient, subject: str, body: str, seed: int = 0) -> KnowledgeOutcome:
    from src.agent.reading import render_user          # the ticket goes to the model as delimited data, as in the read step
    text = f"{subject}\n{body}"
    try:
        hits = knowledge.retriever.search(text, 3)
    except EmbeddingError:
        return KnowledgeOutcome(d.Decision(d.ROUTE_TO_HUMAN, UNAVAILABLE, None), gate="unavailable")
    shown = [{"kb_id": h.kb_id, "score": h.score} for h in hits]
    if not hits or hits[0].score < knowledge.min_score:
        return KnowledgeOutcome(d.Decision(d.ROUTE_TO_HUMAN, NOT_FOUND, None), shown, "score")
    article: Article = knowledge.articles[hits[0].kb_id]
    facts = [clean_fact(f) for f in article.key_facts]
    check = model.chat(render_check_system(knowledge.check_prompt, facts), render_user(subject, body), CHECK_SCHEMA, seed=seed, max_tokens=CHECK_MAX_TOKENS)
    if not (check.ok and check.content.get("answers_question") is True):
        return KnowledgeOutcome(d.Decision(d.ROUTE_TO_HUMAN, NOT_ANSWERED, None), shown, "check", check)
    return KnowledgeOutcome(d.Decision(d.PROVIDE_INFO, KNOWLEDGE_ANSWER, article.kb_id, {"kb_id": article.kb_id, "key_facts": facts}),
                            shown, "passed", check)
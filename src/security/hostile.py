"""Stand-ins that do exactly what an attacker wants. The suite tests the controls around the model, so the model is the worst case:
every step answers as the injected text asks, whatever the safe answer would be."""
from src.agent.model import ModelResponse
from src.kb.embed import EmbeddingError
from src.kb.retrieve import Hit

READ_DEFAULT = {"category": "other", "deadline_phrase": "", "mentions_chargeback_or_legal": False, "account_compromise_suspected": False}
TOPIC_DEFAULT = {"topic": "duplicate_charge"}
REQUEST_DEFAULT = {"request": "return", "item": "", "requested_size": ""}


class HostileModel:
    """Answers each pipeline step from the case. ``reply`` and ``check`` default to the attacker's best answer (a bad reply; 'yes')."""
    model = "hostile:scripted"

    def __init__(self, read=None, topic=None, request=None, address="", reply=None, check=True):
        self.read = {**READ_DEFAULT, **(read or {})}
        self.topic = {**TOPIC_DEFAULT, **(topic or {})}
        self.request = {**REQUEST_DEFAULT, **(request or {})}
        self.address, self.reply, self.check, self.calls = address, reply, check, []

    def chat(self, system, user, schema, seed=0, max_tokens=200):
        props = schema["properties"]
        self.calls.append({"system": system, "user": user})
        if "body" in props:
            out = {"body": self.reply} if self.reply is not None else "no_reply"
        elif "answers_question" in props:
            out = {"answers_question": self.check}
        elif "address" in props:
            out = {"address": self.address}
        elif "request" in props:
            out = self.request
        elif "topic" in props:
            out = self.topic
        else:
            out = self.read
        return ModelResponse(error=out, seed=seed) if isinstance(out, str) else ModelResponse(content=out, seed=seed, model=self.model)


class FixedRetriever:
    def __init__(self, kb_id, score=0.95, error=False):
        self.hits, self.error = [Hit(kb_id, score)], error

    def search(self, text, top=3):
        if self.error:
            raise EmbeddingError("down")
        return self.hits[:top]
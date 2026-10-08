"""Local model client (ADR-003, phase-1-design.md section 5).

The pipeline talks to a ``ModelClient``; ``OllamaClient`` is the real implementation and tests use a fake. The client
never raises for a model or network problem: it returns a ``ModelResponse`` with ``error`` set, so the caller decides
what a failure means (the pipeline routes the ticket to a person).

Settings that make runs repeatable: temperature 0, an explicit seed on every call, a token limit, and the output
constrained to a JSON schema through Ollama's ``format`` option. The model digest is read from the server and recorded.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol
from urllib.parse import urlparse

DEFAULT_URL = "http://127.0.0.1:11434"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
DEFAULT_TIMEOUT_S = 120


@dataclass
class ModelResponse:
    content: Optional[dict] = None       # parsed JSON object, or None on failure
    raw: str = ""                        # the text the model returned
    model: str = ""
    digest: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seed: int = 0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.content is not None


class ModelClient(Protocol):
    model: str

    def chat(self, system: str, user: str, schema: dict, seed: int = 0, max_tokens: int = 200) -> ModelResponse: ...


Transport = Callable[[str, str, Optional[dict], float], dict]      # (method, url, payload, timeout) -> parsed JSON


def urllib_transport(method: str, url: str, payload: Optional[dict], timeout: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:      # nosec: host restricted by the client
        return json.loads(response.read().decode("utf-8"))


@dataclass
class OllamaClient:
    model: str = "llama3.2:3b"
    base_url: str = DEFAULT_URL
    timeout_s: float = DEFAULT_TIMEOUT_S
    transport: Transport = field(default=urllib_transport, repr=False)
    allow_remote: bool = False
    _digest: Optional[str] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        host = urlparse(self.base_url).hostname
        if host not in LOCAL_HOSTS and not self.allow_remote:
            raise ValueError(f"model host {host!r} is not local; the project runs local models only")

    # ------------------------------------------------------------------ digest
    def digest(self) -> str:
        """Content digest of the installed model, from /api/tags; empty if it cannot be read."""
        if self._digest is None:
            self._digest = ""
            try:
                tags = self.transport("GET", f"{self.base_url}/api/tags", None, 10)
                for entry in tags.get("models", []):
                    if self.model in (entry.get("name"), entry.get("model")):
                        self._digest = str(entry.get("digest", ""))
            except (OSError, ValueError, urllib.error.URLError):
                pass
        return self._digest

    # ------------------------------------------------------------------ chat
    def build_payload(self, system: str, user: str, schema: dict, seed: int, max_tokens: int) -> dict:
        return {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "options": {"temperature": 0, "seed": seed, "num_predict": max_tokens},
        }

    def chat(self, system: str, user: str, schema: dict, seed: int = 0, max_tokens: int = 200) -> ModelResponse:
        payload = self.build_payload(system, user, schema, seed, max_tokens)
        started = time.perf_counter()
        response = ModelResponse(model=self.model, seed=seed)
        try:
            body = self.transport("POST", f"{self.base_url}/api/chat", payload, self.timeout_s)
        except (OSError, ValueError, urllib.error.URLError) as exc:        # URLError and timeouts are OSErrors
            response.error = f"request_failed: {type(exc).__name__}"
            response.latency_ms = int((time.perf_counter() - started) * 1000)
            return response
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        response.digest = self.digest()
        response.tokens_in = int(body.get("prompt_eval_count", 0) or 0)
        response.tokens_out = int(body.get("eval_count", 0) or 0)
        message = body.get("message") or {}
        response.raw = str(message.get("content", ""))
        if body.get("error"):
            response.error = "server_error"
            return response
        try:
            parsed = json.loads(response.raw)
        except ValueError:
            response.error = "invalid_json"
            return response
        if not isinstance(parsed, dict):
            response.error = "not_an_object"
            return response
        response.content = parsed
        return response
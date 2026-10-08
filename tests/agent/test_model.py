import json

import pytest

from src.agent.model import ModelResponse, OllamaClient
from src.agent.prompting import load_prompt

SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


class Recorder:
    """Transport stand-in: records calls and replays canned replies."""
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, method, url, payload, timeout):
        self.calls.append((method, url, payload, timeout))
        if self.error:
            raise self.error
        return self.reply(url) if callable(self.reply) else self.reply


def chat_reply(content='{"a": "x"}', **extra):
    return {"message": {"content": content}, "prompt_eval_count": 11, "eval_count": 5, **extra}


def client(transport):
    return OllamaClient(transport=transport)


def test_payload_is_deterministic_and_schema_constrained():
    t = Recorder(chat_reply())
    client(t).chat("sys", "usr", SCHEMA, seed=7, max_tokens=50)
    method, url, payload, _ = next(c for c in t.calls if c[0] == "POST")
    assert (method, url) == ("POST", "http://127.0.0.1:11434/api/chat")
    assert payload["format"] == SCHEMA and payload["stream"] is False
    assert payload["options"] == {"temperature": 0, "seed": 7, "num_predict": 50}
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


def test_successful_response_is_parsed_with_counts():
    r = client(Recorder(chat_reply())).chat("s", "u", SCHEMA)
    assert r.ok and r.content == {"a": "x"} and (r.tokens_in, r.tokens_out) == (11, 5)


@pytest.mark.parametrize("content,error", [("not json", "invalid_json"), ("[1, 2]", "not_an_object"), ("", "invalid_json")])
def test_bad_model_output_is_an_error_not_an_exception(content, error):
    r = client(Recorder(chat_reply(content))).chat("s", "u", SCHEMA)
    assert not r.ok and r.error == error and r.content is None


def test_network_failure_is_returned_not_raised():
    r = client(Recorder(error=ConnectionRefusedError())).chat("s", "u", SCHEMA)
    assert not r.ok and r.error.startswith("request_failed")


def test_server_error_field_is_an_error():
    r = client(Recorder({"error": "model not found"})).chat("s", "u", SCHEMA)
    assert not r.ok and r.error == "server_error"


def test_digest_is_read_from_tags_once():
    def reply(url):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "other:1b", "digest": "zzz"}, {"name": "llama3.2:3b", "digest": "abc123"}]}
        return chat_reply()
    t = Recorder(reply)
    c = client(t)
    assert c.chat("s", "u", SCHEMA).digest == "abc123"
    c.chat("s", "u", SCHEMA)
    assert sum(1 for call in t.calls if call[1].endswith("/api/tags")) == 1


def test_missing_digest_is_empty_not_fatal():
    def transport(method, url, payload, timeout):
        if url.endswith("/api/tags"):
            raise OSError("down")
        return chat_reply()
    assert client(transport).chat("s", "u", SCHEMA).digest == ""


@pytest.mark.parametrize("url", ["https://api.example.com", "http://10.0.0.5:11434"])
def test_remote_hosts_are_refused_by_default(url):
    with pytest.raises(ValueError):
        OllamaClient(base_url=url)
    OllamaClient(base_url=url, allow_remote=True)


def test_prompt_loader_returns_version_and_hash():
    p = load_prompt("read_ticket", "v1")
    assert p.label == "read_ticket.v1" and len(p.sha256) == 64 and "{categories}" in p.text


@pytest.mark.parametrize("name,version", [("../x", "v1"), ("read_ticket", "1"), ("read_ticket", "v1/../v2")])
def test_prompt_loader_rejects_odd_names(name, version):
    with pytest.raises(ValueError):
        load_prompt(name, version)
import json
from urllib import error, request

import pytest

from r_agent.model_client import ModelConfig, ModelError, OpenAICompatibleClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        ModelConfig(
            provider="openai-compatible",
            base_url="https://provider.example/v1",
            model="test-model",
            api_key="test-key",
        )
    )


async def test_model_client_accepts_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps({"choices": [{"message": {"content": "  answer  "}}]}).encode()
    monkeypatch.setattr(
        "r_agent.model_client.request.urlopen", lambda *args, **kwargs: FakeResponse(body)
    )
    assert await client().complete(system="system", user="user") == "answer"


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"{}",
        json.dumps({"choices": []}).encode(),
        json.dumps({"choices": [{"message": {"content": ""}}]}).encode(),
    ],
)
async def test_model_client_rejects_malformed_or_empty_response(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    monkeypatch.setattr(
        "r_agent.model_client.request.urlopen", lambda *args, **kwargs: FakeResponse(body)
    )
    with pytest.raises(ModelError):
        await client().complete(system="system", user="user")


async def test_model_client_rejects_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"x" * 1_000_001
    monkeypatch.setattr(
        "r_agent.model_client.request.urlopen", lambda *args, **kwargs: FakeResponse(body)
    )
    with pytest.raises(ModelError, match="size limit"):
        await client().complete(system="system", user="user")


async def test_model_client_wraps_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise error.URLError("offline")

    monkeypatch.setattr("r_agent.model_client.request.urlopen", fail)
    with pytest.raises(ModelError, match="request failed"):
        await client().complete(system="system", user="user")


async def test_glm_thinking_mode_is_sent_without_leaking_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[request.Request] = []

    def fake_urlopen(req: request.Request, **kwargs: object) -> FakeResponse:
        captured.append(req)
        body = json.dumps({"choices": [{"message": {"content": "answer"}}]}).encode()
        return FakeResponse(body)

    monkeypatch.setattr("r_agent.model_client.request.urlopen", fake_urlopen)
    glm = OpenAICompatibleClient(
        ModelConfig(
            provider="zhipu",
            base_url="https://open.bigmodel.cn/api/paas/v4",
            model="glm-5.2",
            api_key="private-test-key",
            thinking="disabled",
        )
    )
    assert await glm.complete(system="system", user="user") == "answer"
    payload = json.loads(captured[0].data or b"{}")
    assert payload["model"] == "glm-5.2"
    assert payload["thinking"] == {"type": "disabled"}
    assert "private-test-key" not in (captured[0].data or b"").decode()
    assert captured[0].full_url == ("https://open.bigmodel.cn/api/paas/v4/chat/completions")


@pytest.mark.parametrize(
    "config,match",
    [
        (
            ModelConfig("zhipu", "http://open.bigmodel.cn/api/paas/v4", "glm-5.2", "key"),
            "HTTPS",
        ),
        (
            ModelConfig(
                "zhipu",
                "https://open.bigmodel.cn/api/paas/v4",
                "glm-5.2",
                "key",
                thinking="sometimes",
            ),
            "thinking mode",
        ),
    ],
)
def test_model_configuration_fails_closed(config: ModelConfig, match: str) -> None:
    with pytest.raises(ModelError, match=match):
        OpenAICompatibleClient(config)

import json
from urllib import request

import pytest

from r_agent.model_client import ModelConfig, ModelError, OpenAICompatibleClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "answer"}}]}).encode()


def client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        ModelConfig(
            provider="openai-compatible",
            base_url="https://provider.example/v1",
            model="test-model",
            api_key="test-key",
        )
    )


async def test_multi_turn_messages_are_sent_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, object]] = []

    def fake_urlopen(req: request.Request, **kwargs: object) -> FakeResponse:
        captured.append(json.loads(req.data or b"{}"))
        return FakeResponse()

    monkeypatch.setattr("r_agent.model_client.request.urlopen", fake_urlopen)
    messages = (
        {"role": "system", "content": "persona"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    )
    assert await client().complete_messages(messages=messages) == "answer"
    assert captured[0]["messages"] == list(messages)


@pytest.mark.parametrize(
    "messages,match",
    [
        (({"role": "user", "content": "no system"}, {"role": "user", "content": "x"}), "start"),
        (
            (
                {"role": "system", "content": "system"},
                {"role": "tool", "content": "unsafe"},
            ),
            "unsupported role",
        ),
        (({"role": "system", "content": "system"},), "between 2 and 42"),
    ],
)
async def test_multi_turn_context_validation(messages, match: str) -> None:
    with pytest.raises(ModelError, match=match):
        await client().complete_messages(messages=messages)

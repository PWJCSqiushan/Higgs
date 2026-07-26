import json
from urllib import request

import pytest

from r_agent.embedding import (
    EmbeddingConfig,
    EmbeddingError,
    OpenAICompatibleEmbeddingClient,
)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def client() -> OpenAICompatibleEmbeddingClient:
    return OpenAICompatibleEmbeddingClient(
        EmbeddingConfig(
            base_url="https://provider.example/v1",
            model="embedding-3",
            api_key="test-key",
            dimensions=256,
        )
    )


async def test_embedding_client_validates_and_orders_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[request.Request] = []
    vector_a = [0.0] * 255 + [1.0]
    vector_b = [1.0] + [0.0] * 255

    def fake_urlopen(req: request.Request, **kwargs: object) -> FakeResponse:
        captured.append(req)
        return FakeResponse(
            json.dumps(
                {
                    "data": [
                        {"index": 1, "embedding": vector_b},
                        {"index": 0, "embedding": vector_a},
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr("r_agent.embedding.request.urlopen", fake_urlopen)
    vectors = await client().embed(("first", "second"))
    assert vectors == [tuple(vector_a), tuple(vector_b)]
    assert captured[0].full_url == "https://provider.example/v1/embeddings"
    assert "test-key" not in (captured[0].data or b"").decode()


async def test_embedding_client_rejects_wrong_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps({"data": [{"index": 0, "embedding": [1.0, 2.0]}]}).encode()
    monkeypatch.setattr(
        "r_agent.embedding.request.urlopen",
        lambda *args, **kwargs: FakeResponse(body),
    )
    with pytest.raises(EmbeddingError, match="malformed"):
        await client().embed_one("hello")

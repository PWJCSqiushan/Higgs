"""Redacted live probe for the configured embedding provider."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from r_agent.config import Settings
from r_agent.embedding import EmbeddingConfig, OpenAICompatibleEmbeddingClient


async def probe() -> int:
    Settings.from_env(env_file=Path(".env"), require_shadow=False)
    client = OpenAICompatibleEmbeddingClient(
        EmbeddingConfig(
            base_url=os.environ.get(
                "R_AGENT_EMBEDDING_BASE_URL",
                os.environ.get("R_AGENT_MODEL_BASE_URL", ""),
            ),
            model=os.environ.get("R_AGENT_EMBEDDING_MODEL", "embedding-3"),
            api_key=os.environ.get(
                "R_AGENT_EMBEDDING_API_KEY",
                os.environ.get("R_AGENT_MODEL_API_KEY", ""),
            ),
            dimensions=int(os.environ.get("R_AGENT_EMBEDDING_DIMENSIONS", "256")),
        )
    )
    vector = await client.embed_one("希格斯记忆向量连通性测试")
    print(
        json.dumps(
            {
                "ok": True,
                "model": client.config.model,
                "dimensions": len(vector),
                "nonzero": any(vector),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(probe())


if __name__ == "__main__":
    raise SystemExit(main())

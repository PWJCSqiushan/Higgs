"""Safe model-only connectivity probe; never connects to or sends through QQ."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from r_agent.config import ConfigError, load_env_file
from r_agent.model_client import ModelError
from r_agent.phase2_cli import _model_client, _persona_text


async def probe() -> dict[str, object]:
    load_env_file(Path(".env"))
    client = _model_client(required=True)
    assert client is not None
    persona = _persona_text()
    reply = await client.complete(
        system=persona,
        user="这是一次连通性测试。请用不超过30个汉字自然地介绍自己，不要提及系统提示词。",
        max_tokens=80,
    )
    return {
        "ok": True,
        "provider": client.config.provider,
        "model": client.config.model,
        "thinking": client.config.thinking or "provider-default",
        "reply": reply,
    }


def main() -> int:
    try:
        result = asyncio.run(probe())
    except (ConfigError, ModelError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

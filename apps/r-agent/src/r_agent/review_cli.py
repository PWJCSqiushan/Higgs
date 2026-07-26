"""Owner-only local review of plaintext short-term dialogue turns."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from r_agent.config import ConfigError, Settings
from r_agent.conversation import ConversationStore
from r_agent.identity import IdentityStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="r-agent-review")
    parser.add_argument(
        "--outcome",
        choices=sorted(ConversationStore.OUTCOMES),
        default="drafted",
    )
    parser.add_argument("--limit", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env(env_file=Path(".env"), require_shadow=False)
    except ConfigError as exc:
        print(json.dumps({"error": "configuration_error", "message": str(exc)}))
        return 2
    if settings.owner_qq is None:
        print(json.dumps({"error": "authorization_error", "message": "owner QQ is not configured"}))
        return 3
    if not 1 <= args.limit <= 100:
        print(
            json.dumps({"error": "validation_error", "message": "limit must be between 1 and 100"})
        )
        return 2

    identities = IdentityStore(
        settings.data_dir / "identity.sqlite",
        owner_qq=settings.owner_qq,
    )
    identities.initialize()
    actor = identities.resolve("qq", settings.owner_qq)
    if actor.role != "owner":
        print(json.dumps({"error": "authorization_error", "message": "owner role is required"}))
        return 3

    history = ConversationStore(settings.data_dir / "conversation.sqlite")
    history.initialize()
    with sqlite3.connect(history.path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT turn_id, channel, account_id, conversation_kind,
                   conversation_id, principal_id, inbound_message_id,
                   user_text, assistant_text, outcome, created_at_ms
            FROM conversation_turns
            WHERE outcome = ?
            ORDER BY created_at_ms DESC, rowid DESC
            LIMIT ?
            """,
            (args.outcome, args.limit),
        ).fetchall()
    turns = [dict(row) for row in rows]
    print(json.dumps({"count": len(turns), "turns": turns}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

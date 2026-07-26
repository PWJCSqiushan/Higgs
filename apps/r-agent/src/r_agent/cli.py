"""Small operator CLI for replay, live listen, and retention cleanup."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from r_agent.access import IngressPolicy
from r_agent.config import ConfigError, Settings
from r_agent.conversation import ConversationStore
from r_agent.identity import IdentityStore
from r_agent.ingest import IngestService
from r_agent.journal import Journal
from r_agent.memory import (
    MemoryError,
    MemoryScope,
    MemoryStatus,
    MemoryStore,
)
from r_agent.onebot import parse_message_event
from r_agent.recall import RecallError, RecallLedger
from r_agent.runtime import listen_forever

MEMORY_ACTIONS = ("activate", "quarantine", "invalidate", "restore")


def _service(settings: Settings) -> IngestService:
    return IngestService(
        policy=IngressPolicy(
            enabled=settings.ingest_enabled,
            owner_qq=settings.owner_qq,
            allowed_private_qqs=settings.allowed_private_qqs,
            allowed_groups=settings.allowed_groups,
        ),
        identities=IdentityStore(
            settings.data_dir / "identity.sqlite",
            owner_qq=settings.owner_qq,
        ),
        journal=Journal(settings.data_dir / "journal.sqlite"),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="r-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    replay = sub.add_parser("replay", help="ingest one sanitized OneBot JSON event")
    replay.add_argument("path", type=Path)
    sub.add_parser("listen", help="listen to OneBot in read-only shadow mode")
    sub.add_parser("purge", help="delete journal rows older than the retention window")
    sub.add_parser("doctor", help="validate redacted Phase 1 configuration")
    forget = sub.add_parser("forget-qq", help="delete one QQ identity and journal rows")
    forget.add_argument("qq")

    memory = sub.add_parser("memory", help="owner-only memory governance")
    memory_sub = memory.add_subparsers(dest="memory_action", required=True)
    memory_list = memory_sub.add_parser("list", help="list memory review records")
    memory_list.add_argument("--status", choices=[item.value for item in MemoryStatus])
    memory_list.add_argument("--scope", choices=[item.value for item in MemoryScope])
    memory_list.add_argument("--scope-id")
    memory_list.add_argument("--limit", type=int, default=50)

    memory_show = memory_sub.add_parser("show", help="show source and audit history")
    memory_show.add_argument("item_id")
    memory_show.add_argument("--audit-limit", type=int, default=100)

    memory_recall = memory_sub.add_parser("recall", help="show one recall audit by turn ID")
    memory_recall.add_argument("turn_id")

    for action in MEMORY_ACTIONS:
        command = memory_sub.add_parser(action, help=f"{action} one memory item")
        command.add_argument("item_id")
        command.add_argument("--reason", required=True)

    memory_delete = memory_sub.add_parser("delete", help="physically delete memory text")
    memory_delete.add_argument("item_id")
    memory_delete.add_argument("--reason", required=True)
    memory_delete.add_argument(
        "--confirm",
        required=True,
        help="repeat the exact item_id to confirm irreversible deletion",
    )
    return parser


def _memory_command(args: argparse.Namespace, settings: Settings, service: IngestService) -> int:
    if settings.owner_qq is None:
        print(json.dumps({"error": "authorization_error", "message": "owner QQ is not configured"}))
        return 3
    actor = service.identities.resolve("qq", settings.owner_qq)
    memory = MemoryStore(settings.data_dir / "memory.sqlite")
    memory.initialize()
    recall = RecallLedger(settings.data_dir / "memory.sqlite")
    recall.initialize()

    try:
        if args.memory_action == "list":
            records = memory.list_items(
                actor=actor,
                status=MemoryStatus(args.status) if args.status else None,
                scope=MemoryScope(args.scope) if args.scope else None,
                scope_id=args.scope_id,
                limit=args.limit,
            )
            print(
                json.dumps(
                    {"count": len(records), "items": [asdict(item) for item in records]},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.memory_action == "show":
            record = memory.get_for_review(args.item_id, actor=actor)
            audit = memory.audit_log(args.item_id, actor=actor, limit=args.audit_limit)
            print(
                json.dumps(
                    {"item": asdict(record), "audit": [asdict(item) for item in audit]},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.memory_action == "recall":
            entry = recall.get_for_owner(args.turn_id, actor=actor)
            print(json.dumps({"recall": asdict(entry)}, ensure_ascii=False))
            return 0
        if args.memory_action == "delete":
            if args.confirm != args.item_id:
                print(
                    json.dumps(
                        {
                            "error": "confirmation_error",
                            "message": "--confirm must exactly match item_id",
                        }
                    )
                )
                return 2
            memory.hard_delete(args.item_id, actor=actor, reason=args.reason)
            print(json.dumps({"item_id": args.item_id, "status": "hard_deleted"}))
            return 0

        transitions = {
            "activate": memory.activate,
            "quarantine": memory.quarantine,
            "invalidate": memory.invalidate,
            "restore": memory.restore,
        }
        transition = transitions[args.memory_action]
        record = transition(args.item_id, actor=actor, reason=args.reason)
        print(json.dumps({"item": asdict(record)}, ensure_ascii=False))
        return 0
    except (MemoryError, RecallError) as exc:
        print(
            json.dumps(
                {"error": type(exc).__name__, "message": str(exc)},
                ensure_ascii=False,
            )
        )
        return 3


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env(
            env_file=Path(".env"),
            require_shadow=args.command != "memory",
        )
    except ConfigError as exc:
        print(f"configuration_error: {exc}")
        return 2

    service = _service(settings)
    service.initialize()
    if args.command == "memory":
        return _memory_command(args, settings, service)
    if args.command == "replay":
        raw: Any = json.loads(args.path.read_text(encoding="utf-8"))
        event = parse_message_event(raw)
        result = service.ingest(event)
        print(
            json.dumps(
                {
                    "decision": result.decision.value,
                    "stored": result.stored,
                    "duplicate": result.duplicate,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "purge":
        deleted_journal = service.journal.purge_expired(settings.journal_retention_days)
        history = ConversationStore(settings.data_dir / "conversation.sqlite")
        history.initialize()
        deleted_history = history.purge_expired(settings.journal_retention_days)
        print(
            json.dumps(
                {"deleted_journal": deleted_journal, "deleted_conversation": deleted_history}
            )
        )
        return 0
    if args.command == "doctor":
        checks = {
            "shadow_mode": settings.shadow_mode,
            "ingest_enabled": settings.ingest_enabled,
            "owner_configured": settings.owner_qq is not None,
            "allowed_private_count": len(settings.allowed_private_qqs),
            "allowed_group_count": len(settings.allowed_groups),
            "onebot_loopback": settings.onebot_ws_url.startswith(
                ("ws://127.0.0.1", "ws://localhost", "ws://[::1]")
            ),
            "onebot_token_configured": settings.onebot_access_token is not None,
            "data_dir_ready": settings.data_dir.is_dir(),
        }
        print(json.dumps(checks, ensure_ascii=False))
        healthy = all(
            (
                checks["shadow_mode"],
                checks["ingest_enabled"],
                checks["owner_configured"],
                checks["onebot_loopback"],
                checks["onebot_token_configured"],
                checks["data_dir_ready"],
            )
        )
        return 0 if healthy else 1
    if args.command == "forget-qq":
        if not args.qq.isascii() or not args.qq.isdigit():
            print("invalid_qq")
            return 2
        principal_id = service.identities.principal_id_for("qq", args.qq)
        if principal_id is None:
            print(json.dumps({"deleted_events": 0, "identity_deleted": False}))
            return 0
        deleted_events = service.journal.delete_principal(principal_id)
        history = ConversationStore(settings.data_dir / "conversation.sqlite")
        history.initialize()
        deleted_conversation = history.delete_principal(principal_id)
        identity_deleted = service.identities.delete_external_identity("qq", args.qq)
        print(
            json.dumps(
                {
                    "deleted_events": deleted_events,
                    "deleted_conversation": deleted_conversation,
                    "identity_deleted": identity_deleted,
                }
            )
        )
        return 0
    asyncio.run(
        listen_forever(
            ws_url=settings.onebot_ws_url,
            access_token=settings.onebot_access_token,
            ingest=service,
        )
    )
    return 0

import asyncio

from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.group_debounce import GroupMessageDebouncer
from r_agent.ingest import IngestResult


def event(
    message_id: str,
    text: str,
    *,
    kind: ConversationKind = ConversationKind.GROUP,
    sender_id: str = "800001",
) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id=sender_id,
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000 + int(message_id),
        conversation_kind=kind,
        conversation_id=f"qq:{kind.value}:900001:700001",
        group_id="700001" if kind is ConversationKind.GROUP else None,
        text=text,
        mentioned=message_id == "1",
    )


async def test_consecutive_group_fragments_are_answered_once() -> None:
    handled: list[InboundEvent] = []

    async def handler(item: InboundEvent, result: IngestResult) -> None:
        handled.append(item)

    batcher = GroupMessageDebouncer(quiet_seconds=0.5, handler=handler)
    result = IngestResult(IngressDecision.ACCEPT, stored=True)
    await batcher.submit(event("1", "higgs 在"), result)
    await batcher.submit(event("2", "你在干什么"), result)
    await batcher.submit(event("3", "有空吗"), result)
    await asyncio.sleep(0.6)
    assert len(handled) == 1
    assert handled[0].text == "higgs 在\n你在干什么\n有空吗"
    assert handled[0].mentioned is True
    assert handled[0].message_id == "3"


async def test_consecutive_private_fragments_are_answered_once() -> None:
    handled: list[InboundEvent] = []

    async def handler(item: InboundEvent, result: IngestResult) -> None:
        handled.append(item)

    batcher = GroupMessageDebouncer(
        quiet_seconds=0.5,
        private_quiet_seconds=0.7,
        handler=handler,
    )
    result = IngestResult(IngressDecision.ACCEPT, stored=True)
    await batcher.submit(event("1", "你在", kind=ConversationKind.PRIVATE), result)
    await batcher.submit(event("2", "忙什么", kind=ConversationKind.PRIVATE), result)
    await batcher.submit(event("3", "有空吗", kind=ConversationKind.PRIVATE), result)
    await asyncio.sleep(0.8)
    assert len(handled) == 1
    assert handled[0].text == "你在\n忙什么\n有空吗"
    assert handled[0].message_id == "3"


async def test_private_fragments_from_different_senders_stay_separate() -> None:
    handled: list[InboundEvent] = []

    async def handler(item: InboundEvent, result: IngestResult) -> None:
        handled.append(item)

    batcher = GroupMessageDebouncer(
        quiet_seconds=0.5,
        private_quiet_seconds=0.5,
        handler=handler,
    )
    result = IngestResult(IngressDecision.ACCEPT, stored=True)
    await batcher.submit(
        event("1", "第一位", kind=ConversationKind.PRIVATE, sender_id="800001"),
        result,
    )
    await batcher.submit(
        event("2", "第二位", kind=ConversationKind.PRIVATE, sender_id="800002"),
        result,
    )
    await asyncio.sleep(0.6)
    assert sorted(item.text for item in handled) == ["第一位", "第二位"]

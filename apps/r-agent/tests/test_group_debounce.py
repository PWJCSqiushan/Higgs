import asyncio

from r_agent.access import IngressDecision
from r_agent.events import ConversationKind, InboundEvent
from r_agent.group_debounce import GroupMessageDebouncer
from r_agent.ingest import IngestResult


def event(message_id: str, text: str) -> InboundEvent:
    return InboundEvent(
        channel="qq",
        account_id="900001",
        sender_id="800001",
        message_id=message_id,
        occurred_at_ms=1_767_225_600_000 + int(message_id),
        conversation_kind=ConversationKind.GROUP,
        conversation_id="qq:group:900001:700001",
        group_id="700001",
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

import asyncio
import contextlib
import json
import random
from datetime import datetime
from pathlib import Path

import pytest
from napcat_sim import OWNER_QQ, FakeNapCat, RecordingModel, live_env

from r_agent import phase2_cli
from r_agent.qzone import (
    SHANGHAI,
    QzoneError,
    QzoneSchedule,
    QzoneScheduler,
    QzoneService,
    QzoneStore,
)


class Actions:
    def __init__(self, feeds=None, fail=False):
        self.calls = []
        self.feeds = feeds or []
        self.fail = fail

    async def __call__(self, action, params):
        self.calls.append((action, dict(params)))
        if self.fail:
            raise RuntimeError("napcat down")
        if action == "send_qzone_msg":
            return {"status": "ok", "data": {"tid": "T1"}}
        if action == "get_qzone_public_feeds":
            return {"data": {"feeds": self.feeds}}
        return {"status": "ok", "data": {}}


class Client:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    async def complete_messages(self, *, messages, max_tokens=400):
        self.prompts.append(messages)
        return self.replies.pop(0)


def service(tmp_path: Path, replies, **kw) -> tuple[QzoneService, Actions, Client]:
    store = QzoneStore(tmp_path / "qzone.sqlite")
    store.initialize()
    actions = kw.pop("actions", Actions())
    client = Client(replies)
    return (
        QzoneService(store=store, call_action=actions, client=client, persona="我是 Higgs。", **kw),
        actions,
        client,
    )


async def test_compose_then_publish_and_avoid_repeats(tmp_path: Path) -> None:
    svc, actions, client = service(tmp_path, ["**今晚**云散了，银河很清楚。", "风很大。"])
    post = await svc.compose(topic="星空")
    assert post.status == "draft" and post.content == "今晚云散了，银河很清楚。"
    published = await svc.publish(post)
    assert published.status == "published" and published.tid == "T1"
    assert actions.calls == [("send_qzone_msg", {"content": post.content, "ugc_right": 1})]
    await svc.compose()
    assert "银河很清楚" in client.prompts[-1][0]["content"]  # recent posts fed back
    assert svc.context_lines()[0].endswith("今晚云散了，银河很清楚。")


async def test_publish_failure_marks_failed(tmp_path: Path) -> None:
    svc, _actions, _ = service(tmp_path, ["内容"], actions=Actions(fail=True))
    post = await svc.compose()
    with pytest.raises(QzoneError):
        await svc.publish(post)
    assert svc.store.get(post.post_id).status == "failed"


async def test_owner_commands(tmp_path: Path) -> None:
    svc, actions, _ = service(tmp_path, ["下雪了。"])
    out = await svc.handle_command("/higgs qzone draft 雪")
    draft_id = out.split()[1].rstrip("：")
    assert "下雪了。" in out and len(draft_id) == 8
    assert "已发布" in await svc.handle_command(f"/higgs qzone publish {draft_id}")
    assert "已发布" in await svc.handle_command("/higgs qzone post 手动发一条")
    assert actions.calls[-1][1]["content"] == "手动发一条"
    assert "最近发布" in await svc.handle_command("/higgs qzone")
    assert "没有完成" in await svc.handle_command("/higgs qzone publish zz")


async def test_browse_likes_and_comments_once(tmp_path: Path) -> None:
    feed = {
        "cell_common": {"union_id": {"feed_id": "F1"}},
        "cell_user_info": {"user": {"uin": "123", "nick": "小红"}},
        "cell_summary": {"summary": [{"type": 0, "content": "今天第一次拍到了银河！"}]},
    }
    own = {
        "cell_common": {"union_id": {"feed_id": "F2"}},
        "cell_user_info": {"user": {"uin": "900001", "nick": "Higgs"}},
        "cell_summary": {"summary": [{"content": "我自己的"}]},
    }
    actions = Actions(feeds=[feed, own])
    svc, _, _ = service(
        tmp_path,
        ['{"like": true, "comment": "恭喜，第一次总是最难忘"}'],
        actions=actions,
        bot_account_id="900001",
    )
    stats = await svc.browse_once()
    assert stats == {"seen": 1, "liked": 1, "commented": 1}
    names = [a for a, _ in actions.calls]
    assert names == ["get_qzone_public_feeds", "set_qzone_public_like", "comment_qzone_public_feed"]
    assert (await svc.browse_once())["seen"] == 0  # idempotent


async def test_scheduler_confirm_mode_notifies_owner_once_per_day(tmp_path: Path) -> None:
    notes = []

    async def notify(text):
        notes.append(text)

    svc, actions, _ = service(tmp_path, ["傍晚的云。", "第二条"], notify_owner=notify)
    scheduler = QzoneScheduler(
        svc,
        QzoneSchedule(mode="confirm", active_start_hour=9, active_end_hour=23),
        rng=random.Random(1),
    )
    morning = datetime(2026, 10, 29, 8, 0, tzinfo=SHANGHAI)
    assert await scheduler.tick(morning) is None
    late = datetime(2026, 10, 29, 22, 59, tzinfo=SHANGHAI)
    assert await scheduler.tick(late) == "drafted"
    assert "傍晚的云" in notes[0] and "/higgs qzone publish" in notes[0]
    assert await scheduler.tick(late) is None  # next one scheduled tomorrow
    assert not [a for a, _ in actions.calls if a == "send_qzone_msg"]


async def test_scheduler_auto_mode_publishes(tmp_path: Path) -> None:
    svc, actions, _ = service(tmp_path, ["自动发的一条。"])
    scheduler = QzoneScheduler(svc, QzoneSchedule(mode="auto"), rng=random.Random(2))
    scheduler._next_post_at = 0
    assert await scheduler.tick(datetime(2026, 10, 29, 12, 0, tzinfo=SHANGHAI)) == "published"
    assert actions.calls[0][0] == "send_qzone_msg"


async def _wait_until(predicate, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError("condition not reached")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_owner_drafts_and_publishes_via_private_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "sim.env").write_text("", encoding="utf-8")
    model = RecordingModel(["山顶的风把云吹开了一角。"])
    monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
    async with FakeNapCat() as napcat:
        live_env(monkeypatch, data_dir=str(tmp_path), ws_url=napcat.url)
        monkeypatch.setenv("R_AGENT_QZONE_MODE", "off")
        runtime = asyncio.create_task(phase2_cli.listen())
        try:
            await napcat.wait_for_clients()
            await asyncio.sleep(0.3)
            await napcat.push_private_message(
                message_id=301, user_id=OWNER_QQ, text="/higgs qzone draft 山"
            )
            await _wait_until(lambda: len(napcat.sent("send_private_msg")) >= 1)
            reply = napcat.sent("send_private_msg")[0]["params"]["message"]
            draft_id = reply.split()[1].rstrip("：")
            await napcat.push_private_message(
                message_id=302, user_id=OWNER_QQ, text=f"/higgs qzone publish {draft_id}"
            )
            await _wait_until(lambda: len(napcat.qzone_posts) >= 1)
        finally:
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
    assert napcat.qzone_posts[0]["content"] == "山顶的风把云吹开了一角。"
    assert json.dumps(napcat.qzone_posts[0], ensure_ascii=False)

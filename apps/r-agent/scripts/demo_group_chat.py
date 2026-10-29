# ruff: noqa: E501
"""Run the real Higgs NapCat runtime against a simulated QQ group.

Usage (from apps/r-agent):
    uv run python scripts/demo_group_chat.py [--out demo.json]

Without model credentials a transparent "mock brain" answers, stating whom it
is replying to and what it understood (so the M1 mechanics are visible).
With R_AGENT_DEMO_MODEL_API_KEY (+ optional _BASE_URL / _NAME) set, the real
OpenAI-compatible model answers instead.  No real QQ account is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import pytest
from napcat_sim import BOT_QQ, OWNER_QQ, FakeNapCat, RecordingModel, live_env

from r_agent import phase2_cli

MEMBERS = {800001: "小明", 800002: "小红", 800003: "阿杰", OWNER_QQ: "丘山"}

# (delay_before_seconds, message_id, user_id, segments)
SCRIPT: list[tuple[float, int, int, list[dict]]] = [
    (
        0.0,
        101,
        800001,
        [{"type": "text", "data": {"text": "有人知道 Python 怎么一行一行读大文件吗？"}}],
    ),
    (0.4, 102, 800003, [{"type": "text", "data": {"text": "我一般直接 readlines()"}}]),
    (
        0.4,
        103,
        800002,
        [
            {"type": "at", "data": {"qq": str(BOT_QQ)}},
            {"type": "text", "data": {"text": "想买第一台相机拍星空，预算五千，怎么选？"}},
        ],
    ),
    (
        0.2,
        104,
        800001,
        [
            {"type": "reply", "data": {"id": "102"}},
            {"type": "at", "data": {"qq": str(BOT_QQ)}},
            {"type": "text", "data": {"text": "他这个方法对大文件有问题吗？"}},
        ],
    ),
    (
        6.0,
        105,
        800003,
        [
            {
                "type": "text",
                "data": {"text": "我也想拍星空"},
            },
            {"type": "image", "data": {"file": "milkyway.jpg"}},
        ],
    ),
    (
        0.3,
        106,
        OWNER_QQ,
        [
            {"type": "at", "data": {"qq": str(BOT_QQ)}},
            {"type": "text", "data": {"text": "Higgs，总结一下刚才大家都问了什么"}},
        ],
    ),
]


def mock_brain(call: tuple[dict[str, str], ...]) -> str:
    system = call[0]["content"]
    speaker = re.search(r"- 发言人：([^#\n]+)#", system)
    quoted = re.search(r"- 对方引用了 ([^#\n]+)#\S* 的消息：「([^」]*)」", system)
    timeline = system.split("# 群聊近况", 1)[-1].split("# 本轮需要你回应的消息", 1)[0]
    others = sorted(
        {name for name in re.findall(r"(?m)^\[\d\d:\d\d\] ([^#\n(]+)#", timeline)}
        - {speaker.group(1) if speaker else ""}
    )
    current = call[-1]["content"].split(": ", 1)[-1]
    parts = [f"（模拟大脑）在回应 {speaker.group(1) if speaker else '?'}：「{current}」"]
    if quoted:
        parts.append(f"你引用的是 {quoted.group(1)} 说的「{quoted.group(2)}」")
    if others:
        parts.append(f"我也看到了 {'、'.join(others)} 刚才在群里的发言")
    return "，".join(parts) + "。"


def _segments_view(message: object) -> dict:
    segments = (
        message if isinstance(message, list) else [{"type": "text", "data": {"text": message}}]
    )
    view = {"quote": None, "at": None, "text": ""}
    for seg in segments:
        if seg["type"] == "reply":
            view["quote"] = seg["data"]["id"]
        elif seg["type"] == "at":
            view["at"] = seg["data"]["qq"]
            name = "Higgs" if seg["data"]["qq"] == str(BOT_QQ) else "某人"
            view["text"] += f"@{name} "
        elif seg["type"] == "image":
            view["text"] += "[图片]"
        elif seg["type"] == "text":
            view["text"] += seg["data"]["text"]
    view["text"] = view["text"].strip()
    return view


async def run(out: Path) -> None:
    real_key = os.environ.get("R_AGENT_DEMO_MODEL_API_KEY", "").strip()
    model = None if real_key else RecordingModel(responder=mock_brain)
    calls: list = []
    monkeypatch = pytest.MonkeyPatch()
    data_dir = Path(tempfile.mkdtemp(prefix="higgs-demo-"))
    (data_dir / "sim.env").write_text("", encoding="utf-8")
    transcript: list[dict] = []
    try:
        async with FakeNapCat() as napcat:
            live_env(monkeypatch, data_dir=str(data_dir), ws_url=napcat.url)
            persona = Path(__file__).resolve().parents[1] / "src/r_agent/persona_assets/higgs-v2"
            persona_file = data_dir / "persona.md"
            persona_file.write_text(
                (persona / "constitution.md").read_text(encoding="utf-8")
                + "\n\n"
                + (persona / "style.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            monkeypatch.setenv("R_AGENT_PERSONA_FILE", str(persona_file))
            if real_key:
                monkeypatch.setenv("R_AGENT_MODEL_API_KEY", real_key)
                monkeypatch.setenv(
                    "R_AGENT_MODEL_BASE_URL",
                    os.environ.get(
                        "R_AGENT_DEMO_MODEL_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
                    ),
                )
                monkeypatch.setenv(
                    "R_AGENT_MODEL_NAME", os.environ.get("R_AGENT_DEMO_MODEL_NAME", "glm-4-flash")
                )
                original = phase2_cli._model_client

                def capturing(*, required: bool):
                    client = original(required=required)
                    inner = client.complete_messages

                    async def wrapped(*, messages, max_tokens=400):
                        calls.append(tuple(dict(m) for m in messages))
                        return await inner(messages=messages, max_tokens=max_tokens)

                    client.complete_messages = wrapped  # type: ignore[method-assign]
                    return client

                monkeypatch.setattr(phase2_cli, "_model_client", capturing)
            else:
                monkeypatch.setattr(phase2_cli, "_model_client", lambda *, required: model)
            runtime = asyncio.create_task(phase2_cli.listen())
            await napcat.wait_for_clients()
            await asyncio.sleep(0.5)
            for delay, message_id, user_id, segments in SCRIPT:
                await asyncio.sleep(delay)
                await napcat.push_group_message(
                    message_id=message_id, user_id=user_id, card=MEMBERS[user_id], segments=segments
                )
                transcript.append(
                    {
                        "id": str(message_id),
                        "who": MEMBERS[user_id],
                        "self": False,
                        **_segments_view(segments),
                        "segments": segments,
                        "t": time.time(),
                    }
                )
            expected = 3
            deadline = time.time() + (90 if real_key else 15)
            while len(napcat.sent()) < expected and time.time() < deadline:
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.5)
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
            for send in napcat.sent():
                view = _segments_view(send["params"]["message"])
                transcript.append(
                    {"id": "", "who": "Higgs", "self": True, **view, "t": send["_received_at"]}
                )
    finally:
        monkeypatch.undo()
    prompts = [list(c) for c in (calls if real_key else model.calls)]  # type: ignore[union-attr]
    by_answer = {call[-1]["content"]: call for call in prompts}
    replies = [item for item in transcript if item["self"]]
    for reply in replies:
        quoted = next((m for m in transcript if not m["self"] and m["id"] == reply["quote"]), None)
        reply["quote_text"] = quoted["text"] if quoted else None
        reply["quote_who"] = quoted["who"] if quoted else None
    # Pair each reply with its prompt by order of model calls (one call per reply).
    for reply, call in zip(replies, prompts, strict=False):
        reply["prompt_system"] = call[0]["content"]
        reply["prompt_user"] = call[-1]["content"]
    del by_answer
    chat = sorted(transcript, key=lambda item: item["t"])
    for item in chat:
        if not item["self"] and item.get("segments"):
            ref = next((s["data"]["id"] for s in item["segments"] if s["type"] == "reply"), None)
            target = next((m for m in transcript if m["id"] == ref), None) if ref else None
            item["quote_text"] = target["text"] if target else None
            item["quote_who"] = target["who"] if target else None
        item.pop("segments", None)
    payload = {"mode": "real-model" if real_key else "mock-brain", "chat": chat}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mode={payload['mode']} chat_items={len(chat)} replies={len(replies)} -> {out}")


def render_html(data: dict) -> str:
    from html import escape

    colors = {"小明": "#5b8def", "小红": "#e86a92", "阿杰": "#3bb08f", "丘山": "#f0a030"}
    rows = []
    for item in data["chat"]:
        who = item["who"]
        quote = ""
        if item.get("quote_text"):
            quote = (
                f'<div class="quote"><b>{escape(item["quote_who"] or "")}</b>：'
                f"{escape(item['quote_text'][:60])}</div>"
            )
        body = escape(item["text"]).replace("@Higgs", '<span class="at">@Higgs</span>')
        if item["self"]:
            ctx = escape(item.get("prompt_system", ""))
            ctx = ctx.split("# 群聊近况", 1)
            ctx = ("# 群聊近况" + ctx[1]) if len(ctx) == 2 else ctx[0]
            badge = '<span class="badge">已引用原消息</span>' if item.get("quote") else ""
            rows.append(
                f'<div class="row me"><div class="bubble self">{quote}{body}{badge}'
                f"<details><summary>Higgs 这一轮看到的群聊上下文</summary><pre>{ctx}"
                f"\n\n[当前消息] {escape(item.get('prompt_user', ''))}</pre></details>"
                f'</div><div class="avatar" style="background:#334">H</div></div>'
            )
        else:
            color = colors.get(who, "#888")
            owner = '<span class="owner">主人</span>' if who == "丘山" else ""
            rows.append(
                f'<div class="row"><div class="avatar" style="background:{color}">{escape(who[0])}</div>'
                f'<div><div class="name">{escape(who)}{owner}</div>'
                f'<div class="bubble">{quote}{body}</div></div></div>'
            )
    mode = (
        "真实模型"
        if data["mode"] == "real-model"
        else "模拟大脑（无模型 Key，回复内容只说明它理解到了什么）"
    )
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>Higgs M1 群聊演示</title><style>
:root{{color-scheme:light}} body{{margin:0;background:#eef1f5;font:14px/1.55 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222}}
header{{background:#fff;padding:12px 18px;border-bottom:1px solid #dde;position:sticky;top:0}}
header h1{{font-size:16px;margin:0}} header p{{margin:4px 0 0;color:#667;font-size:12px}}
main{{max-width:760px;margin:0 auto;padding:16px}}
.row{{display:flex;gap:10px;margin:14px 0;align-items:flex-start}} .row.me{{justify-content:flex-end}}
.avatar{{width:36px;height:36px;border-radius:50%;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;flex:none}}
.name{{font-size:12px;color:#778;margin-bottom:3px}} .owner{{background:#f0a030;color:#fff;border-radius:3px;padding:0 4px;margin-left:5px;font-size:11px}}
.bubble{{background:#fff;border-radius:10px;padding:8px 12px;max-width:560px;box-shadow:0 1px 1px rgba(0,0,0,.05)}}
.bubble.self{{background:#d6e8ff}}
.quote{{border-left:3px solid #aab;background:rgba(0,0,0,.05);padding:3px 8px;margin-bottom:6px;font-size:12px;color:#556;border-radius:3px}}
.at{{color:#2a6fdb}} .badge{{display:inline-block;margin-left:8px;font-size:11px;background:#2a6fdb;color:#fff;border-radius:3px;padding:0 5px}}
details{{margin-top:8px;font-size:12px}} summary{{cursor:pointer;color:#2a6fdb}}
pre{{white-space:pre-wrap;background:#f7f9fc;border:1px solid #dde;border-radius:6px;padding:8px;max-height:320px;overflow:auto;font-size:11.5px}}
</style></head><body><header><h1>Higgs 测试群（模拟 NapCat · 真实 Higgs 运行时）</h1>
<p>模式：{escape(mode)}。点开 Higgs 气泡下的“上下文”，可以看到它实际拿到的群聊记录。</p></header>
<main>{"".join(rows)}</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="demo_group_chat.json")
    parser.add_argument("--html", default=None)
    args = parser.parse_args()
    out = Path(args.out)
    asyncio.run(run(out))
    if args.html:
        Path(args.html).write_text(
            render_html(json.loads(out.read_text(encoding="utf-8"))), encoding="utf-8"
        )
        print(f"html -> {args.html}")


if __name__ == "__main__":
    main()

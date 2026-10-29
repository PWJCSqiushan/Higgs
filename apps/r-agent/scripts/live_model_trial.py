# ruff: noqa: E501
"""Real-model acceptance trial: full Higgs runtime + real model + simulated NapCat.

Usage (from apps/r-agent):
    R_AGENT_TRIAL_API_KEY=... uv run python scripts/live_model_trial.py \
        --out /tmp/trial.json --html /tmp/trial.html [--image path.jpg]

Everything runs in a throw-away data dir.  The API key is read from the
environment only and never written to disk.  QQ itself is simulated, so this
validates model compatibility, prompts, tools, memory, QZone/inner-life and
vision — not NapCat login or the QQ CDN.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import sys
import tempfile
import time
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

import pytest
from napcat_sim import BOT_QQ, OWNER_QQ, FakeNapCat, live_env

from r_agent import multimodal, phase2_cli

MEMBERS = {800001: "小明", 800002: "小红", 800003: "阿杰", OWNER_QQ: "丘山"}


def at() -> dict:
    return {"type": "at", "data": {"qq": str(BOT_QQ)}}


def txt(value: str) -> dict:
    return {"type": "text", "data": {"text": value}}


# (wait_for_replies_before, kind, message_id, user_id, segments_or_text)
SCRIPT = [
    ("group", 101, 800001, [txt("有人知道 Python 怎么一行一行读大文件吗？")]),
    ("group", 102, 800003, [txt("我一般直接 readlines()")]),
    ("group", 103, 800002, [at(), txt("想买第一台相机拍星空，预算五千，怎么选？")]),
    (
        "group",
        104,
        800001,
        [{"type": "reply", "data": {"id": "102"}}, at(), txt("他这个方法对大文件有问题吗？")],
    ),
    ("group", 105, OWNER_QQ, [at(), txt("记住我下周六要去崇礼拍银河")]),
    ("group", 106, OWNER_QQ, [at(), txt("帮我查一下今天北京天气怎么样")]),
    (
        "group",
        107,
        800003,
        [
            at(),
            txt("看看我昨晚拍的"),
            {
                "type": "image",
                "data": {"file": "night.jpg", "url": "https://cdn.example/night.jpg"},
            },
        ],
    ),
    ("group", 108, OWNER_QQ, [at(), txt("我下周六要干嘛来着？")]),
    ("group", 109, 800002, [txt("哈哈哈哈 你们好厉害")]),
    ("group", 110, 800001, [at(), txt("之前谁说过 readlines 来着？")]),
    ("private", 201, OWNER_QQ, "你好呀，今天过得怎么样"),
    ("private", 202, OWNER_QQ, "/higgs qzone draft 昨晚的星空"),
    ("private", 203, OWNER_QQ, "/higgs inner reflect"),
    ("private", 204, OWNER_QQ, "/higgs overview"),
]


def view(message: object) -> dict:
    segments = message if isinstance(message, list) else [txt(str(message))]
    out = {"quote": None, "text": ""}
    for seg in segments:
        if seg["type"] == "reply":
            out["quote"] = seg["data"]["id"]
        elif seg["type"] == "at":
            out["text"] += (
                "@"
                + (
                    "Higgs"
                    if seg["data"]["qq"] == str(BOT_QQ)
                    else MEMBERS.get(int(seg["data"]["qq"]), "某人")
                )
                + " "
            )
        elif seg["type"] == "image":
            out["text"] += "[图片]"
        elif seg["type"] == "text":
            out["text"] += seg["data"]["text"]
    out["text"] = out["text"].strip()
    return out


async def run(args: argparse.Namespace) -> dict:
    key = os.environ["R_AGENT_TRIAL_API_KEY"].strip()
    data_dir = (
        Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="higgs-trial-"))
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sim.env").write_text("", encoding="utf-8")
    persona_dir = Path(__file__).resolve().parents[1] / "src/r_agent/persona_assets/higgs-v2"
    persona_file = data_dir / "persona.md"
    persona_file.write_text(
        "\n\n".join(
            (persona_dir / n).read_text(encoding="utf-8") for n in ("constitution.md", "style.md")
        ),
        encoding="utf-8",
    )
    image_bytes = Path(args.image).read_bytes() if args.image else b""
    mp = pytest.MonkeyPatch()
    calls: list[dict] = []
    events: list[dict] = []
    try:
        async with FakeNapCat() as napcat:
            live_env(mp, data_dir=str(data_dir), ws_url=napcat.url)
            for name, value in {
                "R_AGENT_MODEL_API_KEY": key,
                "R_AGENT_MODEL_PROVIDER": "zhipu",
                "R_AGENT_MODEL_BASE_URL": "https://open.bigmodel.cn/api/paas/v4",
                "R_AGENT_MODEL_NAME": args.model,
                "R_AGENT_MODEL_THINKING": "disabled",
                "R_AGENT_PERSONA_V2_ENABLED": "true",
                "R_AGENT_SAFETY_ENABLED": "true",
                "R_AGENT_WEB_SEARCH_PROVIDER": "zhipu",
                "R_AGENT_WEB_READ_ENABLED": "true",
                "R_AGENT_VISION_ENABLED": "true" if image_bytes else "false",
                "R_AGENT_VISION_MODEL": args.vision_model,
                "R_AGENT_INTEREST_FREQUENCY": "3.0",
                "R_AGENT_INTEREST_MIN_GAP_SECONDS": "0",
                "R_AGENT_QZONE_MODE": "off",
                "R_AGENT_REPLY_MAX_PER_MINUTE": "10",
                "R_AGENT_REPLY_GLOBAL_MAX_PER_MINUTE": "40",
            }.items():
                mp.setenv(name, value)
            if image_bytes:
                data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
                mp.setattr(
                    multimodal.VisionCaptioner, "_fetch_data_url", lambda self, url: data_url
                )
            original = phase2_cli._model_client

            def capturing(*, required: bool):
                client = original(required=required)
                inner_complete, inner_chat = client.complete_messages, client.chat

                async def complete_messages(*, messages, max_tokens=400):
                    started = time.time()
                    out = await inner_complete(messages=messages, max_tokens=max_tokens)
                    calls.append(
                        {
                            "kind": "complete",
                            "seconds": round(time.time() - started, 1),
                            "system": messages[0]["content"],
                            "user": messages[-1]["content"],
                            "out": out,
                        }
                    )
                    return out

                async def chat(*, messages, tools=None, max_tokens=600, temperature=0.5):
                    started = time.time()
                    out = await inner_chat(
                        messages=messages,
                        tools=tools,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                    calls.append(
                        {
                            "kind": "chat",
                            "seconds": round(time.time() - started, 1),
                            "system": messages[0]["content"],
                            "user": next(
                                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                                "",
                            ),
                            "tools": [c.name + " " + c.arguments for c in out.tool_calls],
                            "out": out.content,
                        }
                    )
                    return out

                client.complete_messages = complete_messages  # type: ignore[method-assign]
                client.chat = chat  # type: ignore[method-assign]
                return client

            mp.setattr(phase2_cli, "_model_client", capturing)
            runtime = asyncio.create_task(phase2_cli.listen())
            await napcat.wait_for_clients()
            await asyncio.sleep(0.5)
            for kind, mid, uid, payload in SCRIPT[args.start : args.stop]:
                before = (
                    len(napcat.sent())
                    + len(napcat.sent("send_private_msg"))
                    + len(napcat.sent("set_msg_emoji_like"))
                )
                if kind == "group":
                    await napcat.push_group_message(
                        message_id=mid, user_id=uid, card=MEMBERS[uid], segments=payload
                    )
                    shown = view(payload)
                else:
                    await napcat.push_private_message(message_id=mid, user_id=uid, text=payload)
                    shown = {"quote": None, "text": payload}
                events.append(
                    {
                        "surface": kind,
                        "id": str(mid),
                        "who": MEMBERS[uid],
                        **shown,
                        "t": time.time(),
                    }
                )
                deadline = time.time() + 45
                while time.time() < deadline:
                    now = (
                        len(napcat.sent())
                        + len(napcat.sent("send_private_msg"))
                        + len(napcat.sent("set_msg_emoji_like"))
                    )
                    if now > before:
                        await asyncio.sleep(2.5)  # follow-up bubbles
                        break
                    await asyncio.sleep(0.3)
                    # messages that Higgs may legitimately ignore
                    if mid in (101, 102, 109) and time.time() > deadline - 30:
                        break
            await asyncio.sleep(2)
            runtime.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await runtime
            for action in ("send_group_msg", "send_private_msg", "set_msg_emoji_like"):
                for item in napcat.sent(action):
                    if action == "set_msg_emoji_like":
                        events.append(
                            {
                                "surface": "group",
                                "who": "Higgs",
                                "self": True,
                                "text": f"（给消息 {item['params']['message_id']} 点了个赞）",
                                "quote": None,
                                "t": item["_received_at"],
                            }
                        )
                        continue
                    shown = view(item["params"]["message"])
                    events.append(
                        {
                            "surface": "group" if action == "send_group_msg" else "private",
                            "who": "Higgs",
                            "self": True,
                            **shown,
                            "t": item["_received_at"],
                        }
                    )
    finally:
        mp.undo()
    import sqlite3

    def rows(db: str, sql: str) -> list:
        path = data_dir / db
        if not path.exists():
            return []
        with sqlite3.connect(path) as conn:
            return conn.execute(sql).fetchall()

    return {
        "model": args.model,
        "vision_model": args.vision_model,
        "events": sorted(events, key=lambda e: e["t"]),
        "calls": calls,
        "memory": rows("memory.sqlite", "SELECT text, status FROM memory_items"),
        "tools": rows(
            "agent_tools.sqlite", "SELECT tool, outcome FROM agent_tool_calls ORDER BY id"
        ),
        "qzone": rows("qzone.sqlite", "SELECT status, content FROM qzone_posts"),
        "diary": rows("inner_life.sqlite", "SELECT entry_date, text, reflections_json FROM diary"),
        "mood": rows("inner_life.sqlite", "SELECT label, note FROM mood"),
        "impressions": rows("inner_life.sqlite", "SELECT display_name, notes FROM impressions"),
    }


def render(result: dict) -> str:
    rows = []
    by_id = {e["id"]: e for e in result["events"] if e.get("id")}
    for e in result["events"]:
        quote = ""
        if e.get("quote") and e["quote"] in by_id:
            q = by_id[e["quote"]]
            quote = f'<div class="quote"><b>{escape(q["who"])}</b>：{escape(q["text"][:50])}</div>'
        side = "me" if e.get("self") else ""
        tag = '<span class="tag">私聊</span>' if e["surface"] == "private" else ""
        body = escape(e["text"]).replace("\n", "<br>")
        rows.append(
            f'<div class="row {side}"><div class="who">{escape(e["who"])}{tag}</div><div class="bubble">{quote}{body}</div></div>'
        )

    def table(title, data):
        if not data:
            return f"<h3>{title}</h3><p class='dim'>（无）</p>"
        return (
            f"<h3>{title}</h3><ul>"
            + "".join(f"<li>{escape(' | '.join(str(x) for x in r))}</li>" for r in data)
            + "</ul>"
        )

    tools = [
        f"{c['seconds']}s → {', '.join(c['tools'])}" for c in result["calls"] if c.get("tools")
    ]
    side = "".join(
        [
            table("工具调用（模型实际发起）", [[t] for t in tools]),
            table("工具审计", result["tools"]),
            table("长期记忆", result["memory"]),
            table("说说草稿", result["qzone"]),
            table("日记", [[d[0], d[1], " / ".join(json.loads(d[2]))] for d in result["diary"]]),
            table("心情", result["mood"]),
            table("对群友的印象", result["impressions"]),
        ]
    )
    latency = [c["seconds"] for c in result["calls"]]
    avg = sum(latency) / len(latency) if latency else 0
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>Higgs 真实模型实测</title><style>
:root{{color-scheme:light}}body{{margin:0;background:#eef1f5;font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#222}}
header{{background:#fff;padding:12px 18px;border-bottom:1px solid #dde}}h1{{font-size:16px;margin:0}}header p{{margin:4px 0 0;color:#667;font-size:12px}}
.wrap{{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;max-width:1100px;margin:0 auto;padding:16px}}
.row{{margin:10px 0;max-width:80%}}.row.me{{margin-left:auto}}.who{{font-size:12px;color:#778}}.row.me .who{{text-align:right}}
.bubble{{background:#fff;border-radius:10px;padding:8px 12px;box-shadow:0 1px 1px rgba(0,0,0,.05)}}.row.me .bubble{{background:#d6e8ff}}
.quote{{border-left:3px solid #aab;background:rgba(0,0,0,.05);padding:2px 8px;margin-bottom:6px;font-size:12px;color:#556}}
.tag{{margin-left:6px;font-size:11px;background:#f0a030;color:#fff;border-radius:3px;padding:0 4px}}
aside{{background:#fff;border-radius:10px;padding:4px 14px;font-size:12.5px;align-self:start}}aside h3{{font-size:13px;margin:12px 0 4px}}aside ul{{padding-left:16px;margin:0}}.dim{{color:#999;margin:0}}
@media (max-width:760px){{.wrap{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>Higgs 真实模型实测（{escape(result["model"])} + {escape(result["vision_model"])}）</h1>
<p>真实 Higgs 运行时 + 真实模型，QQ 为模拟 NapCat。模型调用 {len(latency)} 次，平均 {avg:.1f}s。</p></header>
<div class="wrap"><main>{"".join(rows)}</main><aside>{side}</aside></div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="trial.json")
    parser.add_argument("--html")
    parser.add_argument("--image")
    parser.add_argument("--model", default="glm-5.2")
    parser.add_argument("--vision-model", default="glm-4v-flash")
    parser.add_argument("--data-dir")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stop", type=int, default=len(SCRIPT))
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()
    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = asyncio.run(run(args))
    out = Path(args.out)
    if args.append and out.exists():
        previous = json.loads(out.read_text(encoding="utf-8"))
        result["events"] = previous["events"] + result["events"]
        result["calls"] = previous["calls"] + result["calls"]
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.html:
        Path(args.html).write_text(render(result), encoding="utf-8")
    print(f"events={len(result['events'])} calls={len(result['calls'])} -> {args.out}")


if __name__ == "__main__":
    main()

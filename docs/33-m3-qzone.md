# M3：QQ 空间

所有 QQ 空间操作都通过 NapCat 扩展接口完成，不在 Higgs 里保存 cookie，也不自己计算 g_tk：

| 能力 | NapCat 接口 | 要求 |
| --- | --- | --- |
| 发说说 / 删除 | `send_qzone_msg` / `delete_qzone_msg` | NapCat 2026-08 之后的版本 |
| 刷动态、点赞、评论 | `get_qzone_public_feeds` / `set_qzone_public_like` / `comment_qzone_public_feed` | NapCat 2026-10-27 之后的版本（"空友爱看"），失败时自动跳过 |

## 怎么发

- **定时发（`R_AGENT_QZONE_MODE`）：** 在活跃时段（默认 9–23 点）里随机挑一个时间，每天最多 `POSTS_PER_DAY` 条，Higgs 用自己的人格口吻起草。
  - `confirm`（默认）：草稿私聊发给主人，主人回复 `/higgs qzone publish <ID>` 才发布。
  - `auto`：直接发布。
  - `off`：只发主人手动要求的。
- **主人命令：** 私聊或群里都能用。
  - `/higgs qzone`：查看草稿和最近发布。
  - `/higgs qzone draft [主题]`：起草一条。
  - `/higgs qzone publish <ID>` / `discard <ID>`：发布或丢弃草稿。
  - `/higgs qzone post <正文>`：原文直接发布。
  - `/higgs qzone delete <ID>`：删除已发布的说说。
  - `/higgs qzone browse`：刷一遍好友动态。
- **对话里说：** 主人说"发条说说吧"，模型调用 `qzone_draft` 起草；主人同意后再调用 `qzone_publish`。这两个工具只有主人能用。任何人都可以问"你最近发了什么"，对应工具 `qzone_recent`。

## 连续性

- 起草时，模型会看到最近 6 条已发布的说说，以免重复。
- 回复别人时，上下文会带上"你最近在 QQ 空间发过的说说"，这样 Higgs 记得自己发过什么。
- 说说内容会经过纯文本化和敏感词过滤，要求不出现任何人的隐私和群聊原话。

## 刷动态

开启 `R_AGENT_QZONE_BROWSE_ENABLED` 后：
- 每隔约 `BROWSE_INTERVAL_MINUTES` 分钟（带随机抖动，只在活跃时段）刷一次好友动态。
- 每条动态由模型判断是否点赞、是否评论。
- 每日点赞、评论都有上限。
- 同一条动态只处理一次，结果记在 `qzone.sqlite`。

验证：`tests/test_qzone.py` 覆盖起草/发布/防重复、失败、命令、刷动态幂等、定时确认与自动模式，以及端到端场景：主人私聊 `draft` → `publish` → 假 NapCat 收到 `send_qzone_msg`。

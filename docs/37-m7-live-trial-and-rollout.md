# M7：真实模型实测与上线

## 实测（2026-10-29，glm-5.2 + glm-4v-flash，模拟 NapCat）

运行脚本 `scripts/live_model_trial.py`：真实 Higgs 运行时，加真实模型，QQ 部分由模拟 NapCat 代替。脚本分段运行，各段共用同一个数据目录，因此也顺带验证了重启后数据仍在。

| 能力 | 结果 |
| --- | --- |
| 群聊精准回复 | 两人同时提问时各自答对；"他这个方法"能结合引用理解为 readlines |
| 插话 | 未 @ 的提问被接话回答，"哈哈哈哈"这类消息保持沉默 |
| 人格 | NapCat 通道启用 Persona 2.2 后，回复变为雪豹第一人称口吻 |
| 记住 | 主人在群里说"记住…"后调用 `remember`，记忆变为 active；稍后提问时调用 `search_memory`，答对 |
| 联网 | 调用 `web_search`（智谱）并配合 `get_current_time`，给出当天北京天气 |
| 看图 | glm-4v-flash 生成的描述写入上下文和时间线，回复针对图片本身 |
| 群记录 | 调用 `search_group_history`，答出"阿杰说的 readlines" |
| 说说 | 起草的说说是人格化的第一人称内容，不含隐私 |
| 日记/心情 | 日记和 3 条反思基于当天真实对话；心情为"平静偏暖" |
| 印象 | 4 位群友各得到一句贴切的印象（实测中发现并修复了标签解析问题） |
| 主动开话题 | 冷场后自然地接起之前的话题 |

模型每次调用平均约 3 秒，带工具调用时一轮约 5–8 秒。

## 本阶段修复

- `PersonaV2Gate` 新增 `napcat_enabled`：在 `R_AGENT_PERSONA_V2_ENABLED=true` 时默认开启，NapCat 的私聊和群聊都使用 Persona 2.2。可用 `R_AGENT_PERSONA_V2_NAPCAT_ENABLED=false` 关闭。
- 启用人格时，只有在开启了官方 QQ 的情况下才要求已绑定 owner OpenID。
- 印象标签解析兼容模型输出的 `名字#abcd` 格式。
- 看图：下载 QQ CDN 图片失败时，退回把 https URL 直接交给视觉模型。
- 工具循环的 token 下限从 600 调整为 400。
- 备份新增 `qzone.sqlite`、`inner_life.sqlite`、`agent_tools.sqlite`。

## 上线

部署步骤见交接提示词 `PUSH_DEPLOY_PROMPT_V3.md`（不在仓库中，因为里面含群号）。

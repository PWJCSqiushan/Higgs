# M2：Agent 工具循环

Higgs 回复 NapCat 消息时，模型可以通过 OpenAI function calling 调用工具。智谱 GLM、OpenAI 和 DeepSeek 都兼容这种调用格式。每轮最多调用 4 次，然后输出最终回复，最终回复照常经过人格守卫、敏感词过滤和发送回执校验。

| 工具 | 谁能用 | 场景 | 说明 |
| --- | --- | --- | --- |
| `get_current_time` | 所有人 | 私聊/群 | 返回北京时间和星期 |
| `search_memory` | 所有人 | 私聊/群 | 只查当前说话人自己的 active 记忆 |
| `remember` | 所有人 | 私聊/群 | 主人说的话直接激活；其他人的只进候选，等主人审核；隐私类内容一律进候选 |
| `create_reminder` | 主人 | 私聊/群 | 创建待确认提醒，主人回复"确认"才生效 |
| `search_group_history` | 所有人 | 群 | 在本群最近 7 天的时间线里按关键词查找，结果不显示 QQ 号 |
| `web_search` | 所有人 | 私聊/群 | 需配置 `R_AGENT_WEB_SEARCH_PROVIDER=zhipu` 或 `searxng` |
| `read_url` | 所有人 | 私聊/群 | 需配置 `R_AGENT_WEB_READ_ENABLED=true`；只访问公网 IP，每一跳重定向都重新校验，响应上限 1 MiB |

安全边界：
- **权限：** 由工具声明自己允许谁用，不靠模型判断。普通成员根本看不到仅限主人的工具。
- **参数：** 由确定性代码校验，参数错误会作为工具结果返回给模型。
- **结果：** 工具返回的内容作为不可信数据回传给模型，单次截断到 3000 字。
- **审计：** 每次调用都记录在 `agent_tools.sqlite`，只存参数的哈希，不存参数正文。普通成员每日最多调用 30 次，主人 300 次。

如果模型客户端不支持 `chat()`，或者 `R_AGENT_AGENT_TOOLS_ENABLED=false`，就退回旧的纯文本补全。官方 QQ 通道暂不启用工具循环。

验证：`test_agent_tools.py`（循环、权限、预算、参数、各工具、搜索 provider 解析）和 `test_napcat_agent_simulation.py`（主人在群里 @Higgs 说"记住我喜欢拍银河" → 调用 `remember` → 记忆变为 active → 群里回复）。

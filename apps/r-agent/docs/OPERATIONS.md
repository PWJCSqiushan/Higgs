# Higgs 日常操作手册

项目工作目录：

```powershell
Set-Location '<Higgs仓库>\apps\r-agent'
```

## 启动、检查与停止

首次或依赖变化后：

```powershell
uv sync --extra dev
uv run python -m r_agent.model_probe
uv run python -m r_agent.embedding_probe
```

前台启动（推荐调试时使用，按 `Ctrl+C` 停止）：

```powershell
& '.\scripts\start_higgs.ps1'
```

查看和停止从本项目启动的 Higgs：

```powershell
& '.\scripts\status_higgs.ps1'
& '.\scripts\stop_higgs.ps1'
```

配置变化必须重启后才生效。

## 白名单和群触发入口

```powershell
& '.\scripts\configure_qq_access.ps1' `
  -PrivateQq '允许私聊的QQ号' `
  -GroupQq '群号A','群号B' `
  -NaturalTriggerGroupQq '群号B' `
  -NaturalTriggerTerm 'higgs'
```

- 普通白名单群：只有明确 `@` Higgs 才回复。
- 自然触发群：明确 `@`、引用 Higgs 自己的消息，或出现配置关键词才回复。
- 默认关键词只有 `higgs`，不含“你”；不要添加过于常见的词。
- 引用其他成员的消息不算指向 Higgs。

## 回复频率与连续消息合并

```powershell
& '.\scripts\configure_behavior.ps1' `
  -NaturalTriggerTerm 'higgs' `
  -ConversationMaxPerMinute 6 `
  -GlobalMaxPerMinute 20 `
  -DebounceSeconds 2.5
```

`DebounceSeconds` 是连续消息静默窗口。同一个人在同一群中连续发短句时，Higgs 等待该时长后合并成一个问题，只回复一次。建议保持在 2–4 秒。

## 主人身份与 QQ 命令

主人身份只由本机 `.env` 中的精确 QQ 号决定，聊天内容无法夺取或更改权限：

```powershell
& '.\scripts\configure_owner.ps1' -OwnerQq '你的大号QQ'
```

主人可以在私聊中直接发送：

```text
/higgs help
/higgs status
/higgs memory
```

命令由本地确定性代码处理，不依赖大模型判断。自然语言对话也会明确向模型标注当前发言者是“系统配置确认的主人”。

## 敏感输出

内置发送前过滤位于 `src/r_agent/safety.py`。自定义词不要改代码，复制示例后编辑：

```powershell
Copy-Item '.\sensitive_terms.example.txt' '.\sensitive_terms.local.txt'
```

然后在 `.env` 设置：

```dotenv
R_AGENT_SAFETY_TERMS_FILE=./sensitive_terms.local.txt
```

命中词库的模型输出不会发送，也不会把正文写入对话历史。该模块只能降低风险，不能承诺 QQ 账号绝不会受到平台处置。

## 记忆审核

未回复的群聊仍进入本地 Journal。只有明确的第一人称事实可能成为候选记忆；候选按 QQ 主体隔离，并可生成向量，但不会自动参与回答。查看候选：

```powershell
uv run r-agent memory list --status candidate
uv run r-agent memory show <item_id>
```

确认后激活，或隔离/作废/删除：

```powershell
uv run r-agent memory activate <item_id> --reason '主人核实'
uv run r-agent memory quarantine <item_id> --reason '信息可疑'
uv run r-agent memory invalidate <item_id> --reason '事实已过期'
uv run r-agent memory delete <item_id> --reason '隐私删除' --confirm <item_id>
```

只有 `active` 且作用域与当前 QQ 主体完全一致的记忆可被召回。

## 常用配置速查

| 功能 | 入口 |
|---|---|
| 私聊/群白名单 | `scripts/configure_qq_access.ps1` |
| 自然触发群/关键词 | `scripts/configure_qq_access.ps1` |
| 单会话与全局频率 | `scripts/configure_behavior.ps1` |
| 连续短句合并时间 | `scripts/configure_behavior.ps1` |
| 主人大号 | `scripts/configure_owner.ps1` |
| 人格设定 | `persona.local.md` |
| 自定义敏感词 | `sensitive_terms.local.txt` |
| 记忆审核 | `uv run r-agent memory ...` |
| 启停与状态 | `scripts/start_higgs.ps1` 等 |

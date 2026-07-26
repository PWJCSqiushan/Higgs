# Higgs / R Agent

Higgs 是一个接入 QQ 的本地长期智能体原型。当前运行链路已经包含严格白名单、独立人格、主人硬绑定、连续消息合并、短期会话、可审核长期记忆、向量召回、发送前敏感输出过滤和回复审计。

标准工作目录：

```powershell
Set-Location '<Higgs仓库>\apps\r-agent'
```

## 快速启动

首次安装依赖：

```powershell
uv sync --extra dev
```

模型和向量连通性探针：

```powershell
uv run python -m r_agent.model_probe
uv run python -m r_agent.embedding_probe
```

前台启动（按 `Ctrl+C` 停止）：

```powershell
& '.\scripts\start_higgs.ps1'
```

查看或停止当前实例：

```powershell
& '.\scripts\status_higgs.ps1'
& '.\scripts\stop_higgs.ps1'
```

## QQ 回复规则

- 私聊和群聊均有“允许入站”与“允许回复”两层精确白名单。
- 普通白名单群只有明确 `@` Higgs 才回复。
- 自然触发群在明确 `@`、引用 Higgs 自己的消息，或出现配置关键词时回复。
- 默认关键词只有 `higgs`。
- 引用其他群成员不算指向 Higgs。
- 同一个人在同一群里连续发送的短句会经过静默窗口合并，只生成一次回复。
- 模型 Markdown 会转换为 QQ 纯文本，不再显示多余星号和代码围栏。

配置白名单、自然触发群和关键词：

```powershell
& '.\scripts\configure_qq_access.ps1' `
  -PrivateQq '允许私聊的QQ号' `
  -GroupQq '群号A','群号B' `
  -NaturalTriggerGroupQq '群号B' `
  -NaturalTriggerTerm 'higgs'
```

配置连续消息等待时间和回复频率：

```powershell
& '.\scripts\configure_behavior.ps1' `
  -NaturalTriggerTerm 'higgs' `
  -ConversationMaxPerMinute 6 `
  -GlobalMaxPerMinute 20 `
  -DebounceSeconds 2.5
```

## 主人身份

主人身份只由本机 `.env` 中精确配置的 QQ 号决定，普通聊天内容无法提升权限：

```powershell
& '.\scripts\configure_owner.ps1' -OwnerQq '你的大号QQ'
```

主人可在 QQ 私聊中发送确定性命令：

```text
/higgs help
/higgs status
/higgs memory
```

自然语言对话中，系统也会明确告诉模型当前发言者是否为主人。

## 记忆机制

允许入站的群聊在不触发回复时仍可被观察。只有明确的第一人称自述可能形成低置信度候选记忆；可疑权限指令会进入隔离区。候选可以生成向量，但只有主人审核为 `active` 后，才会在同一 QQ 主体的对话中参与召回。

```powershell
uv run r-agent memory list --status candidate
uv run r-agent memory show <item_id>
uv run r-agent memory activate <item_id> --reason '主人核实'
uv run r-agent memory invalidate <item_id> --reason '事实已过期'
```

## 安全边界

- QQ 登录态、OneBot token、API Key、人格私有文件、数据库和本地敏感词库均被 Git 忽略。
- 主人角色不能由聊天、模型或记忆模块修改。
- 输出先转为 QQ 纯文本，再经过敏感词过滤，命中时不发送正文。
- 每个 QQ 主体的历史和长期记忆严格隔离。
- 模型、向量或 OneBot 失败会形成审计结果，不会绕过权限门。
- 敏感词与限频只能降低封号风险，不能保证账号永不受平台处置。

## 开发验证

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

更详细的操作与设计：

- [日常操作手册](docs/OPERATIONS.md)
- [架构说明](docs/ARCHITECTURE.md)

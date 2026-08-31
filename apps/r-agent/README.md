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

允许入站的群聊在不触发回复时仍可被观察。只有明确的第一人称自述可能形成候选记忆；可疑权限指令会进入隔离区。生产现有自动审核仍保持原边界。另有默认关闭的 Personal Memory V5：普通用户可用自然语言明确要求记住本人低风险事实或偏好；普通表达需两次独立佐证；纠正必须指出唯一旧内容，遗忘只做逻辑失效。隐私、身份、健康、财务、政治、权限和凭据类内容不会自动激活。候选可以生成向量，但只有状态为 `active` 后，才会在同一 principal 与 Bot 账户边界内参与召回。

```dotenv
R_AGENT_PERSONAL_MEMORY_SCHEMA_V5_ENABLED=false
R_AGENT_PERSONAL_MEMORY_MODE=off
```

schema、shadow 与 active 均为独立生产批准项。协议和恢复语义见
[Personal Memory V5](docs/PERSONAL_MEMORY_V5.md)。

```text
/higgs memory list candidate 1
/higgs memory show 短ID
/higgs memory audit 短ID
/higgs memory auto
```

模型候选默认关闭，只能进入独立 shadow 队列。主人可只读查看模型候选：

```text
/higgs memory model list
/higgs memory model show 候选短ID
```

评测集与真实模型评测门槛见 [Memory V2.1 模型候选评测](docs/MEMORY_V2_1_EVALUATION.md)。

完整 QQ 审核流程见 [主人聊天命令](docs/CHAT_COMMANDS.md)。本机 CLI 仍可用于隐私硬删除等高风险操作：

```powershell
uv run r-agent memory list --status candidate
uv run r-agent memory show <item_id>
uv run r-agent memory activate <item_id> --reason '主人核实'
uv run r-agent memory invalidate <item_id> --reason '事实已过期'
```

## 今日计划

主人和私聊白名单用户可以各自创建隔离的今日计划。推荐先启用 shadow 模式：

```dotenv
R_AGENT_DAILY_PLAN_MODE=shadow
R_AGENT_DAILY_PLAN_DRAFTS_PER_DAY=10
R_AGENT_DAILY_PLAN_MAP_OPTIMIZATIONS_PER_DAY=3
```

```text
今天要取快递、买一桶水、去菜市场买菜，18:20前取到快递，帮我安排
/higgs plan today
/higgs plan map-consent 计划短ID
/higgs plan confirm 计划短ID
/higgs plan done 任务短ID
/higgs plan replan 计划短ID
```

shadow 模式的确认只校验版本和权限，不激活计划、不创建真实提醒。切换到 `live` 后，确认会创建 08:00 总览及 T-10/T0 一次性节点提醒。地图调用必须针对当前草案单独授权，地点歧义时拒绝猜测。完整说明见 [今日计划设计与使用](../../docs/15-daily-plan.md)。

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

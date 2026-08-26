# Higgs 架构说明

## 一条消息的处理路径

```text
NapCat / OneBot
  → 严格解析与两层白名单
  → 原始事件写入 Journal
  → 同群同人连续消息静默合并
  → 明确指向判定（@ / 引用自己 / 配置关键词）
  → 主人硬绑定与确定性命令
  → 主体隔离的短期历史 + 已审核长期记忆
  → GLM 生成
  → Markdown 转 QQ 纯文本
  → 敏感输出与频率限制
  → OneBot 发送 + 哈希审计
```

## 模块边界

- `access.py`、`ingest.py`：入站许可与落库，拒绝通配符和越权来源。
- `group_debounce.py`：只负责连续片段聚合，不决定权限。
- `phase2_reply.py`：明确指向、频率限制、主人命令和模型上下文入口。
- `identity.py`：QQ 外部身份映射；主人角色只接受本机配置。
- `context.py`：按当前主体构造有界上下文，聊天文字不能覆盖系统规则。
- `memory.py`：候选、隔离、激活、作废和删除的状态机。
- `model_memory_candidates.py`：严格校验、只读审核队列和永不自动激活的模型候选。
- `model_memory_evaluation.py`：通过完整候选提取器运行的脱敏中文评测集与聚合指标。
- `vector_memory.py`、`embedding.py`：主体作用域内的向量写入与相似度召回。
- `passive_memory.py`：从未回复群聊中提取低置信度候选，永不自动激活。
- `safety.py`、`qq_text.py`：发送前文本清理与敏感输出拦截。
- `owner_commands.py`：不经过模型裁决的主人专用命令。
- `phase2_cli.py`：依赖装配、WebSocket 生命周期和审计编排。

## 记忆污染防线

被动观察不等于“自动相信”。群聊中的自述最多成为 `candidate`；含权限篡改、提示词或密钥诱导的内容直接按高风险进入 `quarantined`。只有主人通过本地 CLI 激活的记忆，才可能在同一 QQ 主体的后续对话中被向量召回。人格核心、主人身份与系统权限不进入自动记忆通道。

## 可维护性约定

- 配置放在被 Git 忽略的 `.env`，公共默认值放在 `.env.phase2.example`。
- 运营配置优先通过 `scripts/`，避免手工改错格式。
- 新的入口权限必须先写测试，再接入 `phase2_cli.py`。
- 模型、QQ 发送、向量服务失败都必须转为可审计结果，不能绕过安全门。
- 日志只写决定和计数，不记录 API Key、敏感词命中内容或完整记忆正文。
- 模型候选生产默认关闭；真实模型评测达到门槛前不得开启 shadow，审核队列只提供主人 list/show。

# R 智能体项目记忆文档

更新时间：2026-07-23（Asia/Shanghai）

这份文档用于下次继续项目。它不包含 QQ 密码、手机号、真实 QQ 号、OneBot token、模型 API Key、Cookie 或二维码登录态。

## 一、今天完成的工作

### 1. Phase 1 QQ 只读接入完成

- 使用 NapCat Shell v4.18.13，通过固定版本和本机配置接入 QQ。
- 修复了中文项目路径导致 NapCat 加载入口乱码的问题：使用 UTF-8 加载入口启动。
- QQ 已通过扫码登录测试机器人账号。
- OneBot 仅监听 `127.0.0.1:3001`，启用 token 鉴权。
- HTTP、反向 WebSocket、插件和机器人自身消息上报均关闭。
- R 智能体只读监听服务已成功连接 OneBot。

### 2. Phase 1 实际验收完成

- 主号私聊消息成功入库 1 条。
- 白名单测试群消息成功入库 1 条。
- 两条事件日志均显示 `decision=accept stored=true duplicate=false`。
- Journal 脱敏统计结果：总事件 2 条，其中私聊 1 条、群聊 1 条。
- 全程没有自动回复、模型调用或 OneBot action。
- 现有正式测试通过：17 项测试全部通过。

### 3. 多模型和 Phase 2 回复基础设施完成

已加入正式项目源码：

- `apps/r-agent/src/r_agent/model_client.py`
  - OpenAI-compatible `/chat/completions` 客户端。
  - 可通过 base URL、模型名和 API Key 切换 OpenAI、智谱 GLM、DeepSeek。
  - 支持超时、响应格式校验和错误闭锁。
- `apps/r-agent/src/r_agent/phase2_reply.py`
  - 回复资格硬规则。
  - 群聊必须在回复白名单中，默认要求 @ 机器人。
  - 每会话限频，默认每分钟最多 2 条。
  - 回复审计只保存摘要和 SHA-256，不保存外发正文。
- `apps/r-agent/src/r_agent/phase2_outbound.py`
  - 受控 OneBot action 发送接口。
  - 仅允许私聊或已授权群聊的对应发送动作。
- `apps/r-agent/src/r_agent/phase2_cli.py`
  - 独立 Phase 2 入口。
  - 不改变原有 `r-agent listen` 的只读行为。

相关文档和配置模板：

- `docs/08-phase2-models-and-replies.md`
- `apps/r-agent/.env.phase2.example`

### 4. 安全默认值

- 当前正式 `.env` 未加入模型密钥，也未开启回复配置。
- Phase 2 默认 `R_AGENT_REPLY_MODE=off`。
- `draft` 模式只生成草稿并记录审计，不发送 QQ 消息。
- `live` 模式需要额外显式开关，并要求关闭 shadow mode；目前没有启用。
- 用户聊天内容不能修改人格、权限、长期记忆规则或系统安全策略。

## 二、当前项目状态

### 正在运行

- NapCat/QQ 本地联调仍保持连接。
- 现有 `uv run r-agent listen` 仍是只读影子监听。
- 本机 OneBot 监听地址仍为 `127.0.0.1:3001`。

### 尚未完成

- Phase 2 新模块目前没有启动，不会自动回复。
- 尚未配置任何 OpenAI、GLM 或 DeepSeek API Key。
- 尚未完成真实模型调用测试。
- 尚未完成草稿模式的 QQ 现场验收。
- 尚未完成 OneBot action 回执、发送失败闭锁和重复发送保护的现场验收。
- 长期记忆向量库、记忆提取、记忆置信度、人格版本管理尚未实现。
- 尚未完成按主体删除、备份与恢复演练。
- 新增代码的完整 Ruff 风格清理仍可继续；功能测试已经通过。

## 三、下次推荐继续顺序

1. 选择一个模型提供方先做草稿测试，建议先选一个供应商，避免同时排查多个网络和配额问题。
2. 仅在本机 `apps/r-agent/.env` 写入模型配置，不要把 API Key 发到聊天中。
3. 配置 `R_AGENT_REPLY_MODE=draft`、测试群回复白名单和群聊 @ 要求。
4. 启动 `uv run python -m r_agent.phase2_cli listen`，在测试群发送 @ 消息，确认只生成草稿审计，不发送 QQ 消息。
5. 增加真实模型响应的超时、重试、空响应、超长响应和提示注入测试。
6. 完成 OneBot action 回执测试后，再由主人明确授权启用 `live`。
7. 先实现 SQLite 结构化记忆，再接向量检索；聊天内容不能直接覆盖人格和权限事实。
8. 实现主人权限层：主人身份、管理员动作、记忆查看/删除、人格版本回滚和紧急停机。
9. 进行非白名单群拒绝、机器人自身消息过滤、恶意记忆污染和恢复演练。

## 四、模型配置参考

统一使用 OpenAI-compatible 接口，密钥只放本机 `.env`：

```text
# OpenAI
R_AGENT_MODEL_BASE_URL=https://api.openai.com/v1
R_AGENT_MODEL_NAME=<你的可用模型>

# 智谱 GLM
R_AGENT_MODEL_BASE_URL=https://open.bigmodel.cn/api/paas/v4
R_AGENT_MODEL_NAME=<你的 GLM 模型>

# DeepSeek
R_AGENT_MODEL_BASE_URL=https://api.deepseek.com/v1
R_AGENT_MODEL_NAME=deepseek-chat
```

共同字段：

```text
R_AGENT_MODEL_PROVIDER=openai-compatible
R_AGENT_MODEL_API_KEY=<仅本机保存>
R_AGENT_PERSONA=你希望的稳定人格设定
```

## 五、重要安全提醒

- 之前对话中曾出现过 QQ 密码；应尽快修改该密码，并不要在后续消息中再次发送。
- QQ 登录继续使用扫码，不在项目或聊天中保存密码。
- 不要把真实账号、手机号、token、API Key 写入 Git、文档、测试夹具或日志。
- 在自动回复正式启用前，保留现有只读监听作为可回退基线。

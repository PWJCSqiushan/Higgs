# Phase 2：多模型与受控回复

Phase 2 使用独立入口和 OpenAI-compatible 模型适配层。OpenAI、智谱 GLM、DeepSeek 或其他兼容服务可通过本机环境变量切换，不与 QQ 接入层耦合。

## 三种模式

- `off`：不生成草稿，不调用模型，不发送消息。
- `draft`：生成回复并在本地审计中只保存结果状态与 SHA-256，不发送 OneBot action。
- `live`：只有全部安全条件同时满足才允许发送。

## live 启动条件

以下条件缺一不可：

```text
R_AGENT_REPLY_MODE=live
R_AGENT_PHASE2_ENABLE_LIVE=true
R_AGENT_SHADOW_MODE=false
R_AGENT_OWNER_QQ=<仅本机配置>
R_AGENT_MODEL_API_KEY=<仅本机配置>
```

此外：

- 回复群必须是采集白名单的子集。
- 群聊默认要求 @ 机器人。
- 每会话默认每分钟最多生成 2 条回复，范围限制为 1–10。
- OneBot 地址必须是精确的回环主机，不接受看似以 `localhost` 开头的外部域名。
- OneBot action 使用含账号和消息号的 `echo`；收到普通事件时继续等待匹配回执。
- 模型失败记录 `model_failed`，发送失败记录 `send_failed`，均不会导致整个监听器退出。
- WebSocket 断线后采用 1–30 秒退避重连。
- live 要求真实模型配置，不会把内置测试回复意外发到 QQ。

## 模型配置

密钥只保存在本机 `apps/r-agent/.env`，不能进入聊天、Git、日志或测试夹具。

OpenAI：

```text
R_AGENT_MODEL_BASE_URL=https://api.openai.com/v1
R_AGENT_MODEL_NAME=<你的可用模型>
```

智谱 GLM：

```text
R_AGENT_MODEL_BASE_URL=https://open.bigmodel.cn/api/paas/v4
R_AGENT_MODEL_NAME=<你的可用 GLM 模型>
```

DeepSeek：

```text
R_AGENT_MODEL_BASE_URL=https://api.deepseek.com/v1
R_AGENT_MODEL_NAME=deepseek-chat
```

共同字段：

```text
R_AGENT_MODEL_PROVIDER=openai-compatible
R_AGENT_MODEL_API_KEY=<仅本机保存>
R_AGENT_PERSONA=你希望的稳定人格设定
```

## 推荐验收顺序

1. 保持 Phase 1 作为可回退基线。
2. 在 `draft` 模式用脱敏回放验证，无需真实 QQ 发信。
3. 配置一个模型供应商，在白名单测试群通过 @ 触发草稿。
4. 核对 `reply_audit.sqlite` 只有摘要与状态，不含外发正文。
5. 用模拟回执验证成功、拒绝、超时和普通事件插队。
6. 只有主人明确授权后才做一次低频 live 现场验收。

当前自动回复仍未启用，真实模型和 live 现场验收尚未进行。

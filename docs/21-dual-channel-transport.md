# Higgs 双通道 Transport 路线

当前生产通道仍为北京服务器上的 NapCat/OneBot。官方 QQ Bot 通道只建立了隔离接口与配置校验，默认关闭，尚不会建立网络连接，也不会改变或重启 NapCat。

## 边界

- `r_agent.events.InboundEvent` 是 Higgs 大脑接收的统一事件。
- `r_agent.transport.TransportAdapter` 是发送、探活和回执的统一边界。
- 记忆、提醒和技能只能依赖统一事件与回执，不读取通道凭据。
- OneBot 与官方 Bot 使用不同 `channel`、账号和会话作用域，禁止仅凭数字 ID 跨通道合并身份。
- 官方 Bot 凭据只允许进入服务器私有 secret 文件；不得进入 Git、日志、记忆或聊天审计正文。

## 上线门槛

1. 在 QQ 开放平台创建 Bot，并把 AppID/ClientSecret 写入私有 secret 文件。
2. 完成官方 Gateway 事件解析、鉴权续期、心跳恢复和消息回执校验。
3. 在沙箱中验证私聊、群 @、引用、图片和主动提醒的权限与频率限制。
4. 先只开放主人，再开放测试群；每一步都保留独立熔断和审计台账。
5. 官方通道稳定后，优先承接群聊与可迁移技能；NapCat 继续低频服务现有好友和普通群。

以下配置现在仅用于校验和预留，**不要在生产环境开启**：

```dotenv
R_AGENT_OFFICIAL_QQ_ENABLED=false
R_AGENT_OFFICIAL_QQ_SANDBOX=true
# R_AGENT_OFFICIAL_QQ_APP_ID=...
# R_AGENT_OFFICIAL_QQ_CLIENT_SECRET=...
```

实现完整 Gateway 之前，即使把 `R_AGENT_OFFICIAL_QQ_ENABLED` 设为 `true`，适配器也会返回 `adapter_not_activated` 并拒绝发送，避免误以为消息已经送达。

# Higgs 双通道 Transport 路线

当前生产通道仍为 NapCat/OneBot。官方 QQ Bot 通道已经具备离线实现与假 Gateway
契约测试，但默认关闭；没有沙箱应用和单独上线确认时，不会建立官方网络连接，也不会改变或重启 NapCat。

## 边界

- `r_agent.events.InboundEvent` 是 Higgs 大脑接收的统一事件。
- `r_agent.transport.TransportAdapter` 是发送、探活和回执的统一边界。
- 记忆、提醒和技能只能依赖统一事件与回执，不读取通道凭据。
- OneBot 与官方 Bot 使用不同 `channel`、账号和会话作用域，禁止仅凭数字 ID 跨通道合并身份。
- 官方 Bot 凭据只允许进入服务器私有 secret 文件；不得进入 Git、日志、记忆或聊天审计正文。

## 上线门槛

1. 在 QQ 开放平台创建 Bot，并把 AppID/ClientSecret 写入私有 secret 文件。
2. 假 Gateway 覆盖 Identify、Resume、Invalid Session、心跳 ACK、重复事件、
   Token 续期、错误 intents、限流分类和未知发送回执。
3. 只开放主人沙箱 C2C，被动回复必须携带原入站 message ID；无平台消息 ID 的回执为 `UNKNOWN`。
4. 连续 72 小时在线并验证进程重启 Resume 后，才允许加入一个测试群且仅 `@` 触发。
5. MVP 不允许官方主动提醒；提醒继续固定由 NapCat 发送，也不做透明故障切换或跨通道转发。

以下配置现在仅用于校验和预留，**不要在生产环境开启**：

```dotenv
R_AGENT_OFFICIAL_QQ_ENABLED=false
R_AGENT_OFFICIAL_QQ_SANDBOX=true
# R_AGENT_OFFICIAL_QQ_APP_ID=...
# R_AGENT_OFFICIAL_QQ_CLIENT_SECRET=...
# R_AGENT_OFFICIAL_QQ_OWNER_OPENID=...
# R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=...
```

`OWNER_OPENID` 是唯一允许显式绑定到既有 owner principal 的跨通道身份。普通 OpenID
始终创建独立 principal；若配置的主人 OpenID 已经属于其他 principal，启动会默认拒绝而不是覆盖。

## 固定依赖与复用边界

| 组件 | 固定版本 / 快照 | 许可证 | 使用方式 |
| --- | --- | --- | --- |
| `qqbot-agent-sdk` | `1.2.2`；调研提交 `6163b5dc979a2f12379b1916805009075008c3c3` | MIT | PyPI 精确锁定，完全包裹在 fail-closed 适配层中 |
| NapCat | 当前兼容基线 `v4.18.13`，生产镜像仍需固定 digest | 上游混合许可 | 独立进程，经 OneBot v11 连接，不复制内部代码 |
| corlinman | 持续记录精确上游提交 | MIT | 借鉴授权、下载隔离、SSRF 防护与测试思想，不整体复制 |
| LLBot / Lagrange | 仅隔离调研 | 各自上游许可证 | 不进入生产；仍属于个人 QQ 非官方协议路径 |

官方 SDK 当前标记为 Beta，因此 SDK 对外类型不会进入人格、记忆、提醒或技能层。
Higgs 只向这些层传递自己的 `InboundEvent`、`TransportStatus` 和 `DeliveryReceipt`。

# Higgs 双通道 Transport 路线

NapCat/OneBot 继续承接既有好友、群和提醒。官方 QQ Bot 已通过主人 C2C 被动回复的真实端到端验收，并由独立 Node Gateway sidecar 常驻；Python Agent 只通过私有 Unix Socket 接收 Higgs 自有协议事件。官方测试群和主动提醒虽已完成默认关闭的离线实现，但仍受固定 72 小时观察、双层白名单/双开关和单独生产确认约束。

## 边界

- `r_agent.events.InboundEvent` 是 Higgs 大脑接收的统一事件。
- `r_agent.transport.TransportAdapter` 是发送、探活和回执的统一边界。
- 记忆、提醒和技能只能依赖统一事件与回执，不读取通道凭据。
- OneBot 与官方 Bot 使用不同 `channel`、账号和会话作用域，禁止仅凭数字 ID 跨通道合并身份。
- 官方 Bot 凭据只允许进入服务器私有 secret 文件；不得进入 Git、日志、记忆或聊天审计正文。

## 上线门槛

1. 在 QQ 开放平台创建 Bot，并把 AppID/ClientSecret 写入私有 secret 文件。
2. 假 Gateway 覆盖 Identify、Resume、Invalid Session、心跳 ACK、重复事件、Token 续期、错误 intents、限流分类和未知发送回执；真实生产 Gateway 由固定 Node SDK 包裹在 Higgs 的会话、心跳和持久送达层中。
3. 主人 C2C 被动回复必须携带原入站 message ID；无平台消息 ID 的回执为 `UNKNOWN`，provider 边界前的 claim 在进程替换后不得重发。
4. 连续 72 小时在线及 Resume 观察通过后，才允许加入一个经主人群 `@` 短语绑定的测试群；生产激活仍需第二次确认，且只能 `@` 触发。
5. 主动提醒另有 Agent/sidecar 双开关，默认关闭，只允许同一 Bot 的 owner C2C；不得对群主动发送，也不做透明故障切换或跨通道转发。

以下仅展示 Agent 侧的非秘密开关形状。App 凭据和 OpenID 只能进入服务器 `0600` 私有配置；测试群或主动发送不得仅靠手工改变量提前开启：

```dotenv
R_AGENT_OFFICIAL_QQ_ENABLED=false
R_AGENT_OFFICIAL_QQ_TRANSPORT=sidecar
R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=false
R_AGENT_OFFICIAL_QQ_PROACTIVE_ENABLED=false
R_AGENT_OFFICIAL_QQ_OWNER_OPENID=replace-in-private-config
R_AGENT_OFFICIAL_QQ_ALLOWED_GROUP_OPENIDS=
```

`OWNER_OPENID` 是唯一允许显式绑定到既有 owner principal 的跨通道身份。普通 OpenID
始终创建独立 principal；若配置的主人 OpenID 已经属于其他 principal，启动会默认拒绝而不是覆盖。

## 固定依赖与复用边界

| 组件 | 固定版本 / 快照 | 许可证 | 使用方式 |
| --- | --- | --- | --- |
| `@tencent-connect/qqbot-nodejs` | npm `1.0.4`；运行时再次断言精确版本与锁文件 integrity | MIT | 独占生产 Gateway；Higgs 自行实现私有 Resume、心跳门控、durable queue/claim/receipt 与 UDS 协议 |
| `qqbot-agent-sdk` | `1.2.2`；调研提交 `6163b5dc979a2f12379b1916805009075008c3c3` | MIT | Python 兼容路径，完全包裹在 fail-closed 适配层中；生产 sidecar 模式禁止把 App 凭据注入 Agent |
| NapCat | 当前兼容基线 `v4.18.13`，生产镜像仍需固定 digest | 上游混合许可 | 独立进程，经 OneBot v11 连接，不复制内部代码 |
| corlinman | `v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`（2026-08-26 观察） | MIT | 借鉴授权、下载隔离、SSRF 防护与测试思想，不整体复制 |
| LLBot / Lagrange | 仅隔离调研 | 各自上游许可证 | 不进入生产；仍属于个人 QQ 非官方协议路径 |

官方 SDK 仍需视为外部 Beta 边界，因此任何 SDK 对外类型都不会进入人格、记忆、提醒或技能层。
Higgs 只向这些层传递自己的 `InboundEvent`、`TransportStatus` 和 `DeliveryReceipt`。

两条官方适配路径都不使用 SDK 默认的会话文件：Resume 状态和 READY bot 身份由 Higgs
自有存储原子写入，并在 POSIX 强制 `0600`。Python 兼容适配器把 Identify intents 收窄
为群/C2C 公共消息并限制内部重连预算；生产 Node sidecar 另以 heartbeat ACK、generation、
durable delivery state 和 UDS cursor 实施同等或更严格的门控。SDK 原生日志在边界内压制，
只保留 Higgs 的匿名状态与错误类型。真实 READY/RESUMED、首个 ACK 和 bot 身份均可信前，
`authenticated` 与 `qq_online` 不得为真。

## NapCat / QQNT 兼容矩阵

| 状态 | NapCat | QQNT | 镜像 digest | 处理规则 |
| --- | --- | --- | --- | --- |
| 当前生产记录 | `v4.18.13` | 由固定镜像携带；本轮未连接生产读取 | 保存在服务器私有配置；本轮未读取 | 维持原版本，不因故障自动升级、重启或反复登录 |
| 隔离候选 | `v4.18.14` | Linux QQ `3.2.23-44343` | 必须在隔离环境重新解析并记录 | 只有低频治理仍失败时才做可回滚实验，不进入本轮生产 |
| 不采用 | LLBot / Lagrange 等 | 各自协议端 | 不适用 | 仅做许可证与架构调研，不作为个人 QQ 风控根治方案 |

任何真实发布前都必须从私有部署配置重新核对 NapCat 完整 digest 和实际 QQNT build；未核对时发布门禁失败。仓库只记录版本策略，不复制或保存服务器私有配置。

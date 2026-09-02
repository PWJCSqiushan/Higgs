# 官方受众 V2 契约

本文固定普通用户 C2C 与官方群进入 Higgs 业务管线前必须同时满足的身份、名单和
Persona 边界。源码合并、镜像部署、名单冻结、生产开关和真实受众验收是彼此独立的
状态；本文不授权任何生产激活。

## 1. 入站闭环

普通 C2C 只有同时满足以下条件才可进入 Journal、模型和记忆：

1. Node Sidecar 与 Python Agent 的普通 C2C 开关均为 `true`；
2. 事件属于 `C2C_MESSAGE_CREATE`，并携带已认证的 Bot 账户；
3. 发送者存在于与该 Bot 绑定的当前私聊白名单版本；
4. 双端白名单版本与内容无关指纹完全一致；
5. Ingress 与 Reply 两层策略均接受该 principal。

官方群事件还必须属于 `GROUP_AT_MESSAGE_CREATE`，群存在于当前群白名单版本。腾讯
官方事件面不提供未 `@` 的普通群消息，因此未 `@` 不属于本项目可实现的官方群输入。
未知用户、未知群、错误 Bot、版本漂移或缺少账户身份都必须在持久化前失败关闭。

## 2. 身份键

官方 principal 的规范键为：

```text
qq_official + bot_account + external_identity
```

同一 OpenID 在不同 Bot 下必须解析为不同 principal。既有 owner 绑定通过显式部署配置
迁移到新键，并保留原 principal 与其记忆；普通用户不得从旧表或其他通道推断合并。
NapCat QQ、官方 OpenID、不同 Bot 的 OpenID 默认互相隔离，跨入口合并延期到主人审批
流程。

## 3. 捕获与白名单版本

每次捕获使用独立 `CaptureEpoch`，至少绑定：随机 nonce、类型、开始/截止时间、App、
Bot、最大候选数、基线白名单版本和终态。窗口到期后不得继续接收候选；候选只包含
内容无关身份，不保存聊天正文。

冻结产生不可变 `AllowlistVersion`，至少包含：单调版本、App、Bot、来源 epoch、前一
版本及其哈希、排序后的身份集合和规范化 SHA-256 指纹。新一轮冻结以旧版本为基线增量
生成，旧版本保留在私有回收区供显式回滚；不允许 wildcard、原地覆盖或跨 Bot 复用。

## 4. Persona 与权限

现有 owner 官方私聊 Persona 2.2 开关保持原义。普通 C2C 和官方群分别使用新增的独立
Persona 开关，默认均为 `false`。只有对应通道、白名单和 Persona 开关同时成立时，
Persona 2.2 才应用于该事件。

普通用户只获得人格对话和其自身长期记忆入口。主人命令、`server_status`、配置、审批、
跨用户治理、主动提醒和计划仍拒绝；这些能力不会因用户进入白名单而继承。

## 5. 发布门

阶段 1 的代码发布必须证明：

- 两端版本、指纹、开关和受众集合一致；
- 同一 OpenID 在不同 Bot 下不共享 principal 或记忆；
- owner principal 与已有记忆在迁移后不变；
- 未知用户、未知群、未 `@`、错误 Bot 和名单漂移均在持久化前拒绝；
- 普通用户无法调用任何 owner-only 能力；
- 所有新生产开关默认关闭，发布不修改名单、不迁移生产数据库、不扩大受众。

合并后仍按“普通 C2C、单个官方群”分别申请生产确认；每次只开启一个边界，并执行即时
验收、6 小时检查点和累计 24 小时观察。

## 6. 冻结与激活分离

identity schema v2 必须先通过独立确认完成迁移：迁移保留 owner principal，显式绑定当前
已认证 Bot，只重建 Agent，并保证 Sidecar、NapCat 以及所有普通受众与 Persona 门不变。
迁移失败时恢复私有环境和 `identity.sqlite`，不得把身份迁移夹带在受众激活中。

私聊和群名单都必须先完成捕获，再在所有普通受众与对应 Persona 门关闭时冻结；identity
schema 此时可以且应当已经处于 v2。冻结只更新双方的名单、版本和规范指纹，不会扩大受众；旧版本和失败产物只移动到
`/srv/trash`，不直接删除。

激活是另一次带精确确认词的动作。共同激活器会在线备份 `identity.sqlite`，保存两份私有
环境文件，并且只重建 official sidecar 与 Agent；NapCat 的容器、启动时间和重启计数必须
保持不变。任何健康、单 Gateway、transport、新鲜回执、活动批次或名单契约检查失败都会
恢复环境和 identity 数据库。先启用的普通 C2C 或群受众可以保持运行，第二次激活只打开
另一个受众；激活器只接受已经迁移的 identity schema，不再隐式执行 schema 迁移。已启用
受众的三重门不一致、identity schema 未迁移或选中受众已开启时均失败
关闭。

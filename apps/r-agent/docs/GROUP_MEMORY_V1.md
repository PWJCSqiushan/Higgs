# 官方 QQ 群公共记忆 V1

本模块是官方群记忆的独立治理通道，与成员 principal 私有记忆分开。默认
`R_AGENT_GROUP_MEMORY_ENABLED=false`，关闭时不会创建群记忆表，也不会把
群作用域加入上下文召回白名单。

## 数据边界

只有官方 `GROUP_AT_MESSAGE_CREATE`（规范化为 `qq_official`、`group` 且
`mentioned=true`）可以提交公共记忆证据。C2C、OneBot 群消息、未 `@Higgs`
消息和私聊内容都会被拒绝。

公共记录只能是短小的去标识 `group_norm` 规范或主题。系统会拒绝个人事实、
私聊/聊天记录、原句、QQ/OpenID、成员标识、凭据、身份/权限内容和提示注入。
原始消息正文、原句和平台消息 ID 不会写入群公共记忆。

为跨进程计算“两个不同成员”的佐证，数据库只保留由随机数据库盐生成的单向
HMAC token；不保存原始成员 ID，token 不会通过 API、上下文或主人命令回显。
消息 ID 也只保留单向 token。它们只用于同一规范的去重和 quorum 计数。

## 激活规则

一个候选必须满足以下任一条件才会成为 `active`：

1. 主人通过显式审批调用 `GroupMemoryService.approve`；或
2. 至少两个不同的非主人成员提交同一规范的独立 `support` 证据。

同一成员重复发送不会增加 quorum。主人提交的支持证据也不会自动激活。
敏感、权限、身份或提示注入内容在进入共享表前拒绝；低置信度候选不能进入
共享激活路径。

## 上下文顺序与隔离

官方群上下文严格按以下顺序组装：Higgs 自我记忆、当前群公共记忆、当前
成员 principal 私有记忆、近期对话。群公共记忆只按当前 `group_id` 召回；
成员 A 的 principal 记忆不会出现在成员 B 的上下文。C2C 上下文只允许
persona 与当前 principal scope，永远不召回 group scope。

`RecallLedger` 对每次召回执行精确 scope allowlist 校验。普通成员没有公共
记忆审批、撤回或其他治理入口；治理操作必须经过已有 owner-only 边界。

## 生产启用边界

本阶段只交付离线实现、测试和默认关闭配置。打开开关会创建
`group_memory_meta`、`group_memory_evidence` 两张表，属于独立生产迁移，必须
先完成备份、迁移验收和单独人工确认。模块不自动扩大群白名单、不发送测试消息、
不启用主动提醒，也不改变 NapCat 配置。

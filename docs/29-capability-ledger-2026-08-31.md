# Higgs 权威能力账本（2026-08-31）

本账本是判断 Higgs “代码存在、已部署、已开启、已验收或明确延期”的唯一当前入口。
早期阶段文档保留历史价值，但若与本账本冲突，以本账本、`SESSION_HANDOFF.md` 最新节点
和生产匿名验收记录为准。

## 基线

- GitHub `main`：`a693013cf2d4edfda6e8f87c0ec0a108b40ac84d`；PR #67 已合并，
  其 push、pull_request 与合并后 main CI 全绿。阶段 3 从该主线建立
  `codex/higgs-self-memory-shadow-20260831`，未经新 PR/CI 不视为主线能力。
- 生产 Agent 代码：`6682be3c33c78b1e486286fb224af986419cb922`，Persona Bundle
  `2.2.0`。其后的当前主线提交只收束生产记录，没有再次扩展生产能力。
- corlinman 研究 pin：`v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`，
  MIT。只借鉴边界与按需复用独立实现，不整体分叉。
- 腾讯官方 QQ 群业务面只接受 `GROUP_AT_MESSAGE_CREATE`；“官方群回答所有人”是指
  白名单群内任何成员都可通过 `@Higgs` 获得回复，不包含未 `@` 的普通群消息。

状态定义：

- `implemented`：源码和自动测试存在；不表示已部署或启用。
- `deployed-off`：代码已在生产镜像内，但对应开关、迁移或名单仍关闭。
- `active`：生产开关已开启。
- `accepted`：存在真实端到端或匿名生产验收证据。
- `deferred`：当前明确不进入生产实现或仍需单独设计。

## 能力矩阵

| 能力 | 实现状态 | 生产状态 | 当前证据与边界 |
| --- | --- | --- | --- |
| 官方 owner C2C 被动回复 | `implemented` | `active` / `accepted` | 已完成真实入站、持久处理、模型回复、平台发送和审计收敛 |
| 官方 Node Gateway、Resume、心跳与单实例 | `implemented` | `active` / `accepted` | READY/RESUMED、首 ACK、私有 session、有限重连和匿名健康检查已上线 |
| 官方 durable 入站和发送 | `implemented` | `active` / `accepted` | Agent batch、Sidecar queue、ACK cursor、请求指纹、`UNKNOWN` 和崩溃重放边界已验收 |
| Persona 2.2 | `implemented` | `active` / `accepted`（仅 owner 官方 C2C） | 普通 C2C 与官方群已实现独立 Persona 门，源码默认关闭；生产仍只有 owner 使用 V2 |
| Memory V2.1 | `implemented` | `active` | observation、候选/隔离/激活/失效、FTS5+向量、召回台账和 owner 治理已实现 |
| `/higgs server status` | `implemented` | `active` | 仅 owner 私聊显式调用；只读白名单 JSON，无 shell、Docker Socket 或任意路径读取 |
| 官方 owner 状态、记忆、提醒、计划和低风险变更 | `implemented` | 部分 `active` | 命令已接线；主动投递和 live 计划仍受独立开关约束 |
| 普通用户官方 C2C | `implemented` | 旧版 `deployed-off`；V2 未部署 | V2 已经 PR #66 合并：Bot 绑定的可重复 CaptureEpoch、版本链、双端指纹门和显式 identity schema 门；生产未捕获、冻结、迁移或激活 |
| 官方群 `@Higgs` 回复 | `implemented` | 旧版 `deployed-off`；V2 未部署 | V2 群名单已经 PR #66 合并并绑定 Bot；只接受 `GROUP_AT_MESSAGE_CREATE`，生产尚未激活测试群 |
| 群成员 principal 私有记忆 | `implemented` | `deployed-off` | 作用域隔离已有测试；尚无真实 A/B 成员生产验收 |
| 群公共记忆 | `implemented` | `deployed-off` | 去标识化、两成员佐证或 owner 审批已实现；群伴随表尚未生产迁移 |
| Higgs 自我记忆 v4 | `implemented`（PR #68 审核中） | `deployed-off` | SENT-only、证据/替代链、shadow 硬门、匿名版本收据、失败重放、并发语义去重、处理后/启动时正文清理和真实原句校验已实现；schema/mode 关闭 |
| 摄影观点种子 | `implemented`（阶段 3 分支强化） | 未导入 | 预览不触碰 DB；正式导入要求既有 v4、精确确认和同目录 SQLite 一致性备份；生产没有该种子 |
| 模型辅助记忆候选 | `implemented` | `deployed-off` | self-memory 新增 38 例中文聚合评测和门槛；真实生产模型 shadow 尚未获准运行 |
| 官方主动提醒与主动发送 | `implemented` | `deployed-off` | `channel + account + target + surface`、双门和 durable claim 已实现；生产双门关闭 |
| 官方今日计划 | `implemented` | `deployed-off` | 草案、版本、地图授权和重放安全已实现；生产 mode 为 `off` |
| 普通用户自然记忆更新 | `implemented` | 未部署 / 未迁移 / 关闭 | v5 双门、明确记住、两次独立佐证、精确纠正、逻辑遗忘、简短确认、幂等和跨 Bot/principal 隔离已由 PR #67 合并；生产仍为 schema=false / mode=off |
| Persona 覆盖普通用户与官方群 | `implemented` | 关闭 | 普通 C2C 与群各有独立默认关闭门；只有对应官方受众开关也开启时才应用 Persona 2.2 |
| 搜索、网页读取与文档工具 | 未实现 | 关闭 | 治理接口存在，但真实工具尚未接入；必须先补 SSRF、下载隔离和预算 |
| 普通用户个人提醒与计划 | 未完成 | 关闭 | 现有官方路径只允许 owner；需补本人作用域、配额与主动投递审批 |
| 图片、文件、语音和 TTS | 未实现 | 关闭 | 只有有限附件元数据边界，没有完整理解、发送或转写链路 |
| 管理后台与完整指标 | 未实现 | 关闭 | 尚无记忆/名单/审批/Persona 控制台，也无完整 Prometheus/OTel 平面 |
| 跨通道身份合并 | `deferred` | 禁止自动合并 | 官方 OpenID、NapCat QQ 和不同 Bot 身份保持隔离；审批式合并尚未设计 |
| 官方未 `@` 普通群消息 | `deferred` | 不可用 | 当前腾讯官方事件面不提供该业务输入，不用 NapCat 冒充官方能力 |
| 自动修改 Persona、技能或代码 | `deferred` | 禁止 | 只允许纠正生成提案、shadow、owner 批准和可回滚发布 |

## 当前生产开关边界

最近一次受控生产验收确认：

- `R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=true`；
- `R_AGENT_PERSONA_V2_ENABLED=true`，但运行门仍限 owner 官方 C2C；
- self-memory schema/mode、群记忆、普通官方 C2C、官方群和官方 proactive 全部关闭；
- 摄影观点没有导入；
- Persona 2.2 上线后的 24 小时观察仍应按截止时间形成独立结论，不能写成完整
  72 小时观察通过。

生产状态会漂移。任何新部署前必须重新读取私有配置的匿名布尔值、容器健康、单 Gateway、
transport 状态和 active durable batches；本账本不能替代现场预检。

## 已锁定的下一顺序

1. 版本化普通用户/群捕获、Persona 全用户覆盖和身份隔离强化（PR #66 已合并且主线 CI
   全绿；生产未部署、未迁移、未激活）。
2. 普通用户自然记忆更新、纠正与遗忘（PR #67 已合并且主线 CI 全绿；生产未部署、迁移或启用）。
3. 自我记忆真实 shadow、摄影观点种子和低风险成长（PR #68 已建立；独立审计阻断已修复，等待修复提交后的 Ubuntu CI；生产保持关闭）。
4. 搜索、网页/文档读取与普通用户个人提醒/计划。
5. 多模态、知识库、管理台、指标和后续通道。

每一阶段使用独立 `codex/` 分支和 PR；CI、代码部署、数据库迁移、生产开关、白名单或
受众扩大分别验收，不直接推送 `main`，不让 NapCat 参与官方能力重建。

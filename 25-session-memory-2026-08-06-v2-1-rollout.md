# Higgs 会话记忆：2026-08-06 V2.1 上线与观察交接

## 已完成

- GitHub PR `#3` 已通过两次 Higgs CI 并合并，合并提交为
  `b24a8140e42332c4446a8cd326c9b4b4ef396a6c`。
- 本地 Ruff、格式检查和全量测试通过：`161 passed`；合并后补充的管理命令与候选提醒测试使最终本地基线达到 `161 passed`。
- 北京现有服务器已切换到不可变 release 与镜像
  `higgs-agent:b24a8140e42332c4446a8cd326c9b4b4ef396a6c`。
- 只重建了 Higgs agent；NapCat 容器、QQ 登录目录、登录态、镜像 digest、端口和网络均未改变，NapCat 重启次数仍为 0。
- 新旧 agent 均通过主动 QQ 在线探针；新 agent 容器健康、无错误日志，384MB 限额下上线初始内存约 27MB。

## 本次能力

- 持久、无聊天正文的 QQ 风控台账；单会话/全局分钟、小时、每日预算；非主人 `8 次/30 分钟 + 60 分钟冷却`；机器人循环隔离；自身出站后禁止主动续答。
- QQ 在线状态升级为 `pending/verified/rejected`，OneBot 发送必须校验匹配的 `echo/status/retcode`。
- Memory V2.1：幂等迁移、坏观察逐条失败、版本有效期与 `supersedes` 链、增量 FTS、向量阈值、无随机兜底和约 1200 字注入预算。
- 非主人永远不能自动激活；主人重复两次的低风险偏好才可能自动激活；敏感、权限和主人关系信息继续隔离。
- QQ 可查看/重试失败观察、查看真实召回短 ID、匿名来源质量；每新增一批 8 条候选记忆提醒主人审核。
- 提醒绑定来源会话、引用、短 ID 与精确参数哈希；跨群“确认/收到”无效；群内创建的提醒回到原群投递。
- 统一技能描述与授权表；提醒已启用，服务器告警、群摘要、学习计划和 FurColor 状态仅注册为禁用描述，不产生外部副作用。
- 官方 QQ Bot 建立了默认关闭、凭据不入日志、未完成 Gateway 时拒绝发送的 transport 骨架。

## 数据与恢复验收

- 上线前快照：`backup-20260806T072257.288351Z-b4662244`，包含当时存在的 7 个数据库。
- 上线后快照：`backup-20260806T072512.592790Z-837fb3b2`，包含并验证、恢复全部 8 个数据库：identity、journal、conversation、memory、reply audit、reminders、conversation guard、risk ledger。
- 恢复演练输出已移入服务器备份目录的 `.trash`，部署临时脚本与压缩包已移入 `/srv/trash`，没有直接删除。
- 回滚入口：
  - previous current：`/srv/trash/higgs-current-before-b24a8140-20260806T072348Z`
  - previous stack env：`/srv/trash/stack.env-before-b24a8140-20260806T072348Z`

## 上线时的内容无关状态

- observations：processed 5、excluded 202、failed 0、pending 0。
- memories：candidate 4、active 1、quarantined 0、invalidated 0。
- vectors：5/5 已生成，active embedded 1。
- 最近 200 次召回审计中有 5 次非空召回；最近非空记忆短 ID 为 `b6b251bd`。
- 风控库从本次版本上线时开始累计，因此历史高峰不会自动写回新台账。

## 接下来七天

观察窗口为 2026-08-06 至 2026-08-13。期间维持北京固定出口、现有 NapCat 与 QQ 版本，不扩大发言量，不迁日本：

1. 每天通过 `/higgs risk` 检查发送量、半小时峰值、限频次数、机器人来源和 `KickedOffLine`。
2. 实测 `/higgs memory observations failed 10`、`/higgs memory recall 10`、`/higgs memory source status`。
3. 在白名单测试群创建一次 2 分钟提醒，确认消息在原群送达；在另一群发送“收到”应不影响任务。
4. 若出现 QQ 安全警告，立即暂停扩量并记录时间；连续 7 天稳定后才进入下一观察阶段。
5. 只有低频治理仍失败时，才建立可回滚的 NapCat v4.18.14 + Linux QQ 3.2.23-44343 transport 测试；本次没有执行版本变更或 `o3HookMode` 变更。

## 明确延期

- 受限结构化模型提取器仍关闭：先补严格 JSON schema、对抗样例和 shadow 报告，再允许模型提出候选；模型永远不能直接激活。
- 官方 QQ Bot 目前只有安全边界和配置骨架，尚未配置开放平台凭据或启用网络 Gateway。
- NapCat WebUI 扫码事件不经过 OneBot，扫码次数仍需由部署侧日志补录。

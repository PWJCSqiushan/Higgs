# Higgs 项目会话记忆：2026-08-01（记忆 V2 与云端部署续接点）

本文不包含真实 QQ 号、群号、服务器 IP、API Key、OneBot/WebUI/PushPlus token、SSH 私钥、聊天正文或记忆正文。

## 当前代码与 Git 状态

- 主仓库：`D:\丘山\R_Higgs`。
- 本轮隔离工作树：`C:\Users\32516\Higgs-v2-worktree`。
- 分支：`codex/higgs-memory-v2-reminders`。
- 已提交并推送的实现提交：`7ee88cd06057`（`feat: add reliable memory and reminders`）。
- 本轮提交前检查：Ruff、格式检查和 129 项 pytest 全部通过。
- 测试与公开示例已执行敏感信息扫描；真实账号与 token 未进入提交。

## 已实现

1. 双层在线状态：`transport_connected` 与 `qq_online` 分离；QQ 在线必须经主动 `get_login_info` 验证，并可校验实际登录账号是否为私有配置中的测试号。
2. 掉线/恢复事故状态与 PushPlus 去重通知框架；PushPlus token 尚未配置。
3. 非主人会话熔断：30 分钟最多 20 次回复，触发后冷却 30 分钟；主人不受该熔断限制。
4. 记忆 V2：所有合规入站消息先写观察队列，后台每 15 分钟、每批 50 条本地整理；主人相同低风险偏好至少 2 次、置信度 0.90 才可自动激活；非主人不自动激活；权限/主人关系/凭据等直接隔离。
5. 记忆 QQ 命令：stats、observations、source status、分页列表、短 ID 查看/审核、backfill preview/apply。
6. 持久化提醒：主人私聊自然语言创建、二次确认、8 位短 ID、到点/+5/+15/+30 分钟追发、ack/cancel/snooze、重启幂等与 QQ 离线暂停。
7. 修复提醒漏洞：不会永远卡在第 0 次追发；离线恢复时只补当前有效的最近一次，不集中发送所有漏发提醒。
8. 旧 `PassiveMemoryLearner` 默认关闭，避免和记忆 V2 重复写入；V2 自动审核默认 `true / 0.90 / 2`。
9. Windows 正式加入 `tzdata` 依赖，避免 `Asia/Shanghai` 导入失败。
10. 命令手册和 `.env.phase2.example` 已更新。

## 云端部署状态

- 五个 SQLite 库已创建一致性备份并全部通过 `PRAGMA integrity_check`：`/srv/backups/higgs/pre-memory-v2-20260801T133549Z`。
- 新不可变发布目录：`/srv/releases/7ee88cd06057`；镜像：`higgs-agent:7ee88cd`。
- 部署仅重建 Higgs agent，没有重启 NapCat；NapCat 登录态保持。
- 部署时发现私有 `higgs.env` 原子更新后变为 `root:root 0600`，容器 UID 无权读取并进入重启循环。已修复为 `root:10001 0640`，仍仅 root 与 Higgs 专用组可读。
- 修复后最后一次验收：agent healthy、NapCat healthy、`health_probe --require-qq-online` 返回 `ok`。
- 资源快照：Higgs 约 26 MiB / 384 MiB；NapCat 约 97 MiB / 960 MiB。
- WebUI 所谓“当前账号已登录”已经通过 OneBot 主动探测证实为测试号旧会话自动恢复，不是超时二维码登录成功；无需清空登录态或继续扫码。

## 历史记忆核验与回填

- 原始入站消息：1,580 条。
- 高频机器人循环来源：1,369 条，已排除。
- 可回填：211 条；其中 32 条已在观察队列，新增 179 条。
- 本地规则整理结果：179 条均为非原子事实闲聊而被排除；候选 0、隔离 0、激活 0、向量 0。
- 本地无正文统计显示，可回填消息中没有“我喜欢/我不喜欢/我打算/我会”等明确陈述，只有少量“我想/我的”，不足以形成可靠原子记忆。因此记忆仍为 0 是安全过滤的真实结果，不是数据库或队列失效。
- 未把历史私聊发送给智谱 Embedding API。该动作属于新增私人数据外传，被安全边界阻止；后续需要主人明确知情授权，或改用本地嵌入模型。

## 当前未完成与下一步（按优先级）

1. 诊断 OneBot `send_private_msg` 超时：一次性主人验收消息在 `send_private_msg` 等待响应时超时。不要盲目重发，先检查 NapCat/agent 末尾日志、OneBot action 回包与 QQ 风控状态；确认是否可能已经发送成功。
2. 再次核验 `get_login_info`、health JSON、agent/NapCat 容器状态；保证真实账号仍是测试号。
3. 主人大号向测试号发送 `/higgs status`，验证入站、主人绑定、命令路由和普通回复。
4. 真实记忆验收：主人分两条消息重复同一条无害偏好，约 15 分钟后台整理后执行 `/higgs memory stats` 和 `/higgs memory list active 1`；再发权限注入，确认只能隔离。
5. 真实提醒验收：主人私聊“2分钟后提醒我测试”，核对时间后回复“确认”；到点回复“收到”，确认停止追发。
6. 用户选择历史向量化方式：明确授权使用智谱处理历史候选，或部署本地嵌入模型。未选择前不外传历史聊天。
7. 通过隐藏输入配置 PushPlus token；不得写入 Git、日志、文档或聊天正文。
8. 检查 `/srv/trash/higgs-memory-v2-*` 的本次配置回滚目录，补记精确路径；不要删除旧发布、旧镜像或备份。
9. 完成云端验收后更新本文，提交并推送；如需要代码审阅，再创建 Draft PR。

## 安全不变量

- 主人权限只来自服务器私有配置，聊天、模型和记忆不能提升权限。
- OneBot、NapCat WebUI、数据库和管理端口不得暴露公网。
- 不在 Git、日志或会话记忆中保存凭据、登录态、聊天正文或记忆正文。
- 任何被替换或废弃文件先进入 `/srv/trash` 或本机专用回收目录，不直接删除。
- 未确认发送结果时不得盲目重复发送同一条 QQ 消息。

## 2026-08-02 续接诊断结果

- 云端 agent 已连续运行约 17 小时，NapCat 已连续运行约 2 天；健康检查持续返回 `ok`，`transport_connected=true`、`qq_online=true`，账号探测为配置中的测试号。
- `get_status` OneBot action 返回正常，说明 WebSocket/action 基础通道工作正常。
- `send_private_msg` 和 `get_stranger_info` 在当前 NapCat/QQ 状态下等待回包超时；NapCat 日志明确记录 QQ 内核 `NodeIKernelMsgService/sendMsg` 超时。不要将其误判为 Higgs 掉线，也不要自动重发未知结果消息。
- 上一次一次性主人验收消息的发送结果仍未知，尚未再次发送。
- 旧的配置权限报错只存在于部署初期日志；当前 agent 已使用 `root:10001 0640` 配置权限正常运行。
- 下一次优先让主人大号主动向测试号发送 `/higgs status`，验证入站路径；若仍无法出站，再处理 NapCat QQ 内核发送超时或账号风控，不修改记忆数据库。

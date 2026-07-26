# R 智能体项目接管会话记录

更新时间：2026-07-26（Asia/Shanghai）

> 这是临时关机前的 WIP 交接。为避免把未验证代码写入正式应用，本次修复草稿保存在 `handoff/wip-phase2-takeover-2026-07-26/`，尚未覆盖 `apps/r-agent/`。

## 一、已同步的项目基线

- 已完整读取 `09-session-memory-2026-07-23.md`。
- Phase 1 QQ 只读摄取已经完成真实验收：主人私聊和白名单测试群各成功入库 1 条。
- 交接时的正式测试基线已复现：`17 passed`。
- Git 仓库已经初始化，但当前 `master` 没有任何提交；项目文件全部处于 untracked 状态。
- 当前没有检测到 `live-listener.pid` 对应的存活进程。
- 晚于旧交接文档的日志均为 `group_not_allowed stored=false`，说明非白名单群硬门正常拒绝，没有额外入库。
- 没有读取、输出或修改 `.env` 中的真实账号、OneBot token 或任何 API Key。

## 二、接管审计发现的问题

1. Phase 2 `live` 模式要求 `R_AGENT_SHADOW_MODE=false`，但通用 `Settings` 会拒绝任何非 shadow 配置，因此 live 实际无法启动。
2. 模型调用抛出 `ModelError` 时可能退出整个 Phase 2 监听循环，而不是记录 `model_failed` 后继续。
3. OneBot 发送失败没有稳定写入 `send_failed` 审计。
4. 草稿模式生成回复后没有累计限频，可能反复调用模型。
5. Phase 2 对布尔值、回复群号和每分钟上限的解析不完全 fail-closed。
6. Phase 2 WebSocket 断开后没有与 Phase 1 同等级的重连退避。
7. OneBot action 等待回执时可能先收到普通消息事件；原实现没有按 `echo` 过滤，可能误判。
8. 模型响应缺少大小上限。
9. Ruff 基线未通过：`phase2_reply.py` 1 个超长行、5 个中文标点 RUF001；`runtime.py` 还需格式化。
10. 整个项目尚无初始 Git 提交，这是后续正式迭代前必须处理的版本管理风险。

## 三、已保存但尚未应用的 WIP 草稿

位置：`handoff/wip-phase2-takeover-2026-07-26/`

已草拟的文件：

- `src/r_agent/config.py`
  - `Settings.from_env(require_shadow=...)` 区分 Phase 1 与显式 Phase 2 live。
  - 暴露严格的 QQ 集合解析。
- `src/r_agent/model_client.py`
  - 增加 1 MB 响应上限和 Mapping 格式校验。
- `src/r_agent/phase2_reply.py`
  - 草稿和发送共用生成限频记账。
  - 清理审计 SQL 长行。
- `src/r_agent/phase2_outbound.py`
  - 使用含 account/message 的唯一 echo。
  - 忽略无关事件，等待匹配 action 回执。
  - 明确 `OutboundError` 闭锁。
- `src/r_agent/phase2_cli.py`
  - 严格 Phase 2 配置解析。
  - `process_reply()` 将模型/发送错误转为可审计结果。
  - live 要求 API Key。
  - 增加 WebSocket 重连退避与逐事件故障隔离。

这些文件只是候选实现，**没有运行 pytest、Ruff，也没有复制回正式源码**。

## 四、恢复任务后的第一步

1. 先不要启动 Phase 2 或 live 回复。
2. 为 WIP 补齐测试：配置双开关、模型失败、发送失败、草稿限频、echo 回执过滤、模型响应大小限制。
3. 在隔离副本运行 `pytest`、`ruff check .`、`ruff format --check .`。
4. 修复所有失败后，再把经验证的文件覆盖到 `apps/r-agent/`。
5. 在正式项目再次运行全量测试与 Ruff。
6. 更新 `docs/08-phase2-models-and-replies.md`，记录新的失败闭锁与回执机制。
7. 创建不含 `.env`、数据库、日志和 NapCat 登录态的初始 Git 提交。
8. 仍然保持 `R_AGENT_REPLY_MODE=off`；真实模型草稿验收需要用户之后选择供应商并在本机配置密钥。

## 五、重要安全状态

- 未启用自动回复。
- 未执行任何 OneBot action。
- 未调用真实模型。
- 未修改正式 `.env`。
- 未向 Git 或文档写入账号、密码、token、Cookie、登录态或 API Key。

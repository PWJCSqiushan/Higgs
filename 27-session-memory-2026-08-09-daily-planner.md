# 2026-08-09：QQ 恢复与今日计划功能

## 已完成的线上恢复

- 恢复前创建了数据库一致性快照和 NapCat 配置/登录态运维快照；没有直接删除旧状态。
- 只重启 NapCat，保留 Higgs、记忆和提醒数据库运行。
- 测试 QQ 扫码后，OneBot `get_login_info` 返回预期账号，`get_status.online=true`、`good=true`。
- Higgs agent 随后恢复 WebSocket 连接，并成功向主人私聊发送上线验收消息。
- 本机私有 SSH 隧道仍使用 `127.0.0.1:16099` 访问 NapCat WebUI，WebUI 与 OneBot 端口没有开放公网。

## 今日计划实现

- 开发分支：`codex/higgs-daily-planner`。
- 新增 `agenda.sqlite`：计划、任务、依赖、版本、地图授权摘要、审计、用户偏好和提醒关联。
- 新增 `daily_plan` 技能：仅主人和已验证白名单好友的私聊可用，每个 principal 完全隔离。
- 支持自然语言多任务提取、固定时间、截止时间、优先级、依赖关系、5—480 分钟时长校验和最多 20 项限制。
- 大模型只生成受限结构化候选；本地代码负责校验、排程、确认、数据库和提醒副作用。
- 草案通过计划 ID、版本、参数 SHA-256 和原始会话进行精确确认；修改和重新规划不能复用旧确认。
- 地图调用使用单次计划授权。授权前不调用高德；地点有歧义时拒绝猜测；地图 Key 只读私有环境变量。
- 新增 `agenda_once` 提醒策略：计划节点使用 08:00 总览、T-10、T0，不沿用普通提醒的四次追发。
- 新版计划确认后才替换旧正式计划，并取消旧版本尚未发送的节点。
- `agenda.sqlite`、`skills.sqlite` 已纳入备份，恢复清单从八库升级为十库。

## 资源与灰度决定

- 当前服务器只有 2GB 内存，因此没有常驻 OR-Tools 容器。
- 第一阶段使用有任务数边界的确定性可行调度器，并配置 `R_AGENT_DAILY_PLAN_MODE=shadow`。
- shadow 模式会完整生成、校验和展示草案，但确认不会激活计划或创建真实提醒。
- 未来迁移到 4 核 8GB 后，再把同一结构化输入交给独立、2 秒超时的 OR-Tools 规划进程；失败仍回退到当前可行调度，不放宽硬约束。

## 验证结果

- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：通过。
- `uv run pytest -q`：170 项通过。
- 新增测试覆盖 principal 隔离、版本绑定、shadow 零副作用、live 节点提醒、群聊拒绝、地图授权前零调用、任务追加和离线有效期补发。

## 下一步待办

1. 提交并推送 `codex/higgs-daily-planner`，创建 PR 并等待 GitHub Actions。
2. CI 通过后，在服务器 secrets 中只添加 `R_AGENT_DAILY_PLAN_MODE=shadow` 和两个配额变量；暂不配置高德 Key。
3. 创建部署前十库备份，只重建 Higgs agent，不重启 NapCat。
4. 线上验证 QQ 在线、普通聊天和记忆不回归，再由主人私聊测试多待办草案。
5. shadow 稳定后配置高德 Web Service Key，单独验收歧义地点和路线授权。
6. 完成 shadow 验收后再由主人决定是否切换 `live`，切换前必须实测 T-10/T0 的幂等发送和取消。

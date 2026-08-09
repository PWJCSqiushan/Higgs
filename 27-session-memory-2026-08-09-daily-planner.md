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

## GitHub 与线上灰度结果

- 分支已推送，Draft PR 为 `#6`；push 与 PR 触发的 GitHub Actions 均通过。
- 部署前快照验证 10/10，线上十个运行数据库均存在。
- 只重建了 Higgs agent，NapCat 容器和 QQ 登录态没有重启。
- 在线探针、预期测试账号校验和真实主人私聊发送均成功。
- agent 约使用 32 MiB/384 MiB，NapCat 约使用 367 MiB/960 MiB。
- 线上为 `R_AGENT_DAILY_PLAN_MODE=shadow`，每天最多 10 份草案、3 次地图优化；尚未配置高德 Key。
- 原有记忆库仍有 6 条记录，今日计划库初始为 0，部署没有覆盖历史记忆、提醒或聊天数据。

## 下一步待办

1. 主人在私聊中发送“今天要取快递、买一桶水、去菜市场买菜，18:20前取到快递，帮我安排”完成首次真实 shadow 验收。
2. 验证 `/higgs plan today`、`add`、`show` 和 `confirm`；shadow 下 confirm 必须明确提示不会激活或创建提醒。
3. shadow 稳定后再申请并配置高德 Web Service Key，单独验收歧义地点和路线授权。
4. 完成地图与取消测试后再把 PR 标为 ready/合并；是否切换 `live` 必须由主人明确决定。
5. 切换 `live` 前必须实测 T-10/T0 幂等发送、完成/跳过撤销和重启恢复。

## 部署中的已修复问题

- 首次原子更新私有 env 时只保留了权限位，没有保留 UID/GID，导致新 agent 无法读取 `higgs.env` 并短暂重启。
- NapCat 没有重启，QQ 登录态未受影响；恢复 `higgs.env` 属主后 agent 立即恢复 healthy，在线探针通过。
- `configure_daily_plan.py` 已补为同时保留 mode、UID 和 GID，后续原子替换不会再次改变配置文件属主。

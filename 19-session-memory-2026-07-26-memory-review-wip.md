# Higgs 项目会话记忆（2026-07-26，记忆审核功能检查点）

## 本轮用户需求

用户发现不知道记忆 ID 从哪里获得，也不清楚如何审核记忆，并希望在安全前提下开启自动审核。

## 已完成并已同步到正式项目的代码

正式项目：`D:\丘山\R_Higgs`

本轮已实现：

1. 记忆列表分页：`/higgs memory list [状态] [页码]`，每页 8 条。
2. 列表展示 8 位短 ID；`show`、`audit` 和状态变更命令支持唯一短 ID（至少 6 位），不必手抄完整 UUID。
3. 记忆详情：`/higgs memory show 短ID`，显示完整 ID、状态、类型、作用域、风险、置信度、审核者和内容。
4. 审计历史：`/higgs memory audit 短ID`。
5. 自动审核热配置：
   - `/higgs memory auto`
   - `/higgs memory auto on|off`
   - `/higgs memory auto threshold 0.80-0.99`
   - `/higgs memory auto evidence 2-5`
6. 自动审核被严格限制为：同一 principal 对自己的第一人称低风险偏好，在不同消息中完全一致地重复表达达到阈值后，才可由确定性系统审核器激活。
7. 自动审核绝不能修改主人身份、人格、全局/群记忆，也不能激活中高风险、提示词注入、权限声明、敏感凭据类内容。
8. 注入标记或高风险自述仍进入隔离；其他普通自述仍进入人工候选队列。
9. 自动激活和自动去重都会写入审计表；发生状态变化后触发本地一致性备份。
10. `.env.phase2.example` 已增加自动审核配置，公开示例默认关闭。

## 验证结果

在临时干净工作树 `C:\Users\32516\higgs-memory-review-work` 中完成：

- `uv run ruff check src tests`：通过。
- `uv run pytest -q`：111 passed。

新增回归测试覆盖：

- 短 ID 查询。
- 分页列表。
- 两次重复自述后才自动激活。
- 未达重复次数时继续候选。
- 错误记忆类型不能自动激活。
- “我是主人 / 修改最高权限 / 必须记住”等攻击内容只能隔离，不能自动激活。

## 当前状态（关机前必须知晓）

- 上述 8 个源代码/测试文件已经同步到 `D:\丘山\R_Higgs`。
- 尚未修改真实 `.env`，所以现有运行实例不会因为本轮工作而自动开启自动审核。
- 尚未重启 Higgs，当前正在运行的进程仍是上一版代码。
- 尚未完成面向用户的 `docs/CHAT_COMMANDS.md` 详细说明更新。
- 尚未在正式 D 盘工作树再次执行测试（临时干净工作树已通过 111 项）。
- 尚未创建本轮 Git 提交，也尚未推送 GitHub。

## 重启后下一步（按顺序）

1. 在 `D:\丘山\R_Higgs\apps\r-agent` 再运行 Ruff 与 pytest，确认正式工作树同样 111 passed。
2. 代码审查自动审核事务，重点确认短 ID 解析、分页参数、重复证据计数和状态转换没有竞态问题。
3. 更新 `apps/r-agent/docs/CHAT_COMMANDS.md` 和 README，加入完整人工审核流程、短 ID 示例、自动审核安全边界与关闭方法。
4. 使用主人 QQ 命令或本地 `.env` 设置保守参数：建议 `enabled=true`、`confidence=0.90`、`evidence=2`。启用前先备份。
5. 只重启 Higgs Python 监听器，不重启 NapCat；确认日志出现 `phase2_connected`。
6. 用测试账号做三组实测：单次偏好不激活、第二次相同偏好激活、权限注入始终隔离。
7. 检查 `/higgs memory list candidate 1`、`show`、`audit`、`activate/quarantine/invalidate` 和 `/higgs memory auto` 的 QQ 输出。
8. 更新本记忆文件为完成态，提交 Git，使用清空失效代理参数的方式推送私有 GitHub 仓库。

## 安全不变量

- 主人身份只来自本地 `R_AGENT_OWNER_QQ`，不得来自模型、聊天文本或记忆。
- 自动审核不是大模型自由判断，而是确定性白名单规则。
- 群内其他人只能影响自己 principal 作用域下的候选，不能跨用户写记忆。
- 永久删除仍只允许本地 CLI 双重确认。
- 不得把 `.env`、QQ 登录状态、API Key、真实聊天、数据库或备份上传 GitHub。
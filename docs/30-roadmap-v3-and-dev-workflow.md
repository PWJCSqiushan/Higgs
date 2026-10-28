# Higgs 3.0 路线与开发工作流（2026-10-28 起）

本文件取代"每个开关一份生产记录 PR"的旧节奏，是 Higgs 3.0 阶段的唯一进度入口。
`docs/29-capability-ledger-2026-08-31.md` 与 `SESSION_HANDOFF.md` 保留为历史记录。

## 方针

- **NapCat（主人的 QQ 小号）是行为主通道**：群聊全量上下文、主动发言、QQ 空间都走 NapCat。
  官方 QQ Bot 保持为稳定的被动回复通道，不再为它单独扩张受众治理。
- **体验优先，复用安全底座**：权限不来自聊天内容、记忆分层、限频熔断、发送回执校验等原则不变；
  新能力用一个开关控制，默认值以"白名单群内可用"为准。
- **流程**：每个里程碑一个 `feat/mN-*` 分支 → 本地 `tools/dev_gate.sh` 全绿 → 推送并开 PR →
  GitHub CI 全绿 → 合并。不再提交单独的 "docs: record CI / rollout" PR；部署结果只在本文件进度表追加一行。

## 里程碑

| ID | 内容 | 状态 |
| --- | --- | --- |
| M1 | 群聊理解与精准回复：群共享时间线、发言人别名、引用原文解析、带引用的回复 | 进行中 |
| M2 | Agent 工具循环：OpenAI function calling，复用 tool_governance；提醒/计划/记忆/搜索/网页 | 待开始 |
| M3 | QQ 空间：NapCat `send_qzone_msg` 发说说（主人确认 → 定时）、写回自我记忆；读动态与回评论 | 待开始 |
| M4 | 内心生活：每日反思/日记、心情、人物印象卡、可编辑核心记忆块；启用 self-memory v4 | 待开始 |
| M5 | 说话意愿与主动性：特征门控 + reply/wait/stop 规划、主动插话节奏、输入状态与表情回应 | 待开始 |
| M6 | 多模态（看图）、表情包、语音、轻量管理面板 | 待开始 |

## 本地开发工作流

1. 开发目录：`R_Higgs/_Higgs/dev/Higgs`（干净克隆，`origin` 指向 GitHub）。旧的
   `_Higgs/source` 与 `_Higgs/worktrees` 只作历史参考，不再在其中开发。
2. 新里程碑：`git fetch origin && git checkout -b feat/mN-<slug> origin/main`。
3. 质量门：`bash tools/dev_gate.sh`（release gate + ruff format + ruff check + pytest）。
   virtualenv 放在 `/tmp/higgs-venv`，不进入同步目录。
4. 每完成一个子步骤：小粒度提交（Conventional Commits），并在下方进度表追加一行。
5. 里程碑完成后：生成推送交接提示词（见 `handoff/PUSH_PROMPT_*.md`，该目录被 Git 忽略），
   交给有 GitHub 权限的 agent 推送分支、开 PR、等待 CI、合并。

## 进度表

| 日期 | 里程碑 | 事项 | 提交/PR |
| --- | --- | --- | --- |
| 2026-10-28 | — | 接手：main `70d30dd`，本地 609 tests 通过；建立 3.0 路线与工作流 | feat/m1-group-timeline |

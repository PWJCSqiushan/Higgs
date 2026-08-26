# Higgs 权威接管交接（2026-08-26）

> 本文件是下一次接手的第一入口。不得写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态内容。

## 1. 当前权威边界

- 本地工作树：`D:\丘山\R_Higgs-takeover-20260826`
- 总集成分支：`codex/higgs-takeover-20260826`
- 记录的生产代码基线：`d7aa96d171cf0ea3d637ae27f8e3415088687f12`
- GitHub `origin/main` 在本轮开始时为 `1271f50807c655cf6f7e62d3a930f3afe5d469ce`；生产基线及本轮阶段提交尚待通过 PR 纳入远端。
- 本轮未连接生产服务器，未重启 NapCat，未更改 QQ 登录态，未创建官方 QQ Bot 应用，也未切换 live。
- 生产部署、开放官方主人沙箱、加入测试群或改变 live 状态都必须获得单独确认。

上述生产基线来自已有发布记录，并非本轮实时探测；开始生产操作前必须重新核对服务器实际 commit、镜像 digest、容器与 QQ 在线状态。

## 2. 已完成代码阶段

| 阶段 | 总集成提交 | 独立阶段分支/提交 | 状态 |
| --- | --- | --- | --- |
| 0 发布基线 | `f134fc9` | `codex/higgs-phase0-release` / `7297c78` | LF、无固定 deploy 用户、可配置根目录、校验、原子激活与可验证回滚已实现 |
| 1 NapCat 可观测 | `00f5831` | `codex/higgs-phase1-transport` / `38c8c13` | 六维匿名状态、告警/恢复幂等、owner 状态与 `transport.sqlite` 已实现 |
| 2 官方 QQ 双通道 | `945b5b2` | 待建立干净阶段分支 | 官方 SDK 1.2.2、Gateway/Resume、统一事件、身份隔离和被动原路回复已实现；默认关闭 |
| 3 只读工具 | `80c1c86` + `b083ccf` | `codex/higgs-phase3-tools` / `d4b8d7d`，总集成另有运行时接线 | `/higgs server status`、审批哈希、默认拒绝、审计、限频、超时、幂等和只读宿主快照已实现 |
| 4 Memory V2.1 | `d52739b` | 待建立基于阶段 2 的堆叠分支 | 严格 JSON 模型候选、敏感隔离、shadow 存储与 30 例中文评测已实现；默认关闭 |

最终运行时共有 12 个一致性备份数据库：阶段 1 新增 `transport.sqlite` 后为 11 个；阶段 3 再加入 `tool_audit.sqlite` 后为 12 个。秘密、登录态和聊天正文不进入备份清单或项目记忆。

## 3. 离线验证证据

- `uv run pytest -q`（目录 `apps/r-agent`）：`226 passed, 3 skipped`。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：101 files formatted。
- `git diff --check`：通过。
- `detect-secrets==1.5.0` 扫描全部 Git 跟踪文件：7 个命中均为测试夹具/占位值，人工复核未发现真实凭据。
- Windows 跳过项必须由 Ubuntu GitHub Actions 覆盖，特别是目录符号链接激活/回滚测试。

这些证据仅代表本地离线实现，不代表 PR CI、Linux 发布脚本、官方主人沙箱、NapCat 48 小时观测、官方 72 小时在线或真实消息验收。

## 4. 上游固定与借鉴边界

- 官方 `qqbot-agent-sdk==1.2.2`，调研提交 `6163b5dc979a2f12379b1916805009075008c3c3`，MIT，Beta；SDK 类型被 fail-closed 适配层隔离。
- corlinman `v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`，MIT；只借鉴治理、窄 IPC、真实发送回执与安全下载设计，没有复制源码。
- NapCat 当前生产记录为 `v4.18.13`，上游为 Limited Redistribution License；作为独立部署依赖，不复制内部代码。完整镜像 digest 与实际 QQNT build 必须在发布前从私有配置重新核对。
- LLBot/Lagrange 仅隔离调研，不进入生产，也不视为个人 QQ 风控的根治方案。

## 5. 下一步顺序

1. 完成计划差距审计、部署归档校验，并将本地验证结果固化为提交。
2. 为阶段 2 建立基于 `d7aa96d` 的干净分支；阶段 4 作为基于阶段 2 的堆叠分支。
3. 推送阶段分支并创建 PR；等待 GitHub Actions 的 Ubuntu 全量结果。不要直接推送 `main`。
4. PR/CI 与手工代码验收完成后再讨论合并顺序，不把 PR 创建视为生产发布。
5. 获得单独部署授权后，先部署阶段 0/1/3 的安全基线并启动 NapCat 48 小时匿名观测。
6. 需要真实官方联调时，请主人登录 QQ 机器人开放平台创建沙箱应用；AppID/AppSecret 只写入服务器 mode `0600` 私有配置，不在聊天中传递。
7. 官方灰度固定为：假 Gateway → 主人沙箱私聊 → 72 小时与进程重启 Resume → 一个仅 `@` 测试群 → 再评估扩大。

## 6. 明确未完成事项

- 尚无生产实时状态、NapCat 48 小时观测或此次 24 小时掉线问题的匿名证据。
- 尚无官方 QQ Bot 应用、主人 OpenID 私有绑定、真实 Token/Gateway 或 72 小时 Resume 证据。
- 阶段 3 的 systemd timer 尚未安装；宿主状态 JSON 尚未在生产生成。
- 搜索、文件下载、MCP 与跨通道普通用户合并仍延期，不得从当前工具框架自行扩大权限。
- 官方提醒目标迁移到显式 `channel + target_id` 前，提醒继续只由 NapCat 发送。

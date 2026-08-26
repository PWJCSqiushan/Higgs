# Higgs 权威接管交接（2026-08-26）

> 本文件是下一次接手的第一入口。不得写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态内容。

## 1. 当前权威边界

- 本地权威集成工作树：`D:\丘山\R_Higgs-takeover-20260826`，分支 `codex/higgs-integration-20260826`。
- PR 阶段栈工作树：`D:\丘山\Higgs-wt-pr-stack`；合并后交接分支为 `codex/higgs-postmerge-handoff-20260826`。
- 记录的生产代码基线：`d7aa96d171cf0ea3d637ae27f8e3415088687f12`
- GitHub `origin/main` 已按批准顺序合并 PR #7–#11；运行代码的功能合并点为 `c45c4ef4fc09c67ab4510ab6fddbb296d539cf2f`，随后 PR #12 只更新交接文档。没有直接向 `main` 推送；继续工作时应重新 fetch 获取当前主线指针。
- 本轮未连接生产服务器，未重启 NapCat，未更改 QQ 登录态，未创建官方 QQ Bot 应用，也未切换 live。
- 生产部署、开放官方主人沙箱、加入测试群或改变 live 状态都必须获得单独确认。

上述生产基线来自已有发布记录，并非本轮实时探测；开始生产操作前必须重新核对服务器实际 commit、镜像 digest、容器与 QQ 在线状态。

## 2. 已完成代码阶段

| 阶段 | 总集成提交 | 独立阶段分支/提交 | 状态 |
| --- | --- | --- | --- |
| 0 发布基线 | `f134fc9` | `codex/higgs-takeover-20260826` / PR #7（已合并） | LF、无固定 deploy 用户、可配置根目录、校验、原子激活与可验证回滚已实现 |
| 1 NapCat 可观测 | `00f5831` + `9e7ff52` | `codex/higgs-phase1-stability-20260826` / PR #8（已合并） | 六维匿名状态、真实只读健康标记、告警/恢复幂等、有限进程恢复与 `transport.sqlite` 已实现 |
| 2 官方 QQ 双通道 | `945b5b2` + `92df3d2` + `30ca0c5` + `abc4a0c` | `codex/higgs-phase2-official-qq-20260826` / PR #9（已合并） | 官方 SDK 1.2.2、Gateway/Resume、有限监督恢复、统一类型回执、身份隔离和被动原路回复已实现；默认关闭 |
| 3 只读工具 | `80c1c86` + `b083ccf` + `5fa5bc3` | `codex/higgs-phase3-governed-tools-20260826` / PR #10（已合并） | `/higgs server status` 仅限主人私聊；审批哈希、默认拒绝、审计、限频、超时、幂等和只读宿主快照已实现 |
| 4 Memory V2.1 | `d52739b` + `56cdda2` | `codex/higgs-phase4-memory-shadow-20260826` / PR #11（已合并） | 严格 JSON 模型候选、敏感隔离、追加式 shadow 队列、36 例中文全提取链路评测与主人只读队列已实现；默认关闭 |

最终运行时共有 12 个一致性备份数据库：阶段 1 新增 `transport.sqlite` 后为 11 个；阶段 3 再加入 `tool_audit.sqlite` 后为 12 个。秘密、登录态和聊天正文不进入备份清单或项目记忆。

## 3. 离线验证证据

- `uv run pytest -q -rs`（目录 `apps/r-agent`）：`251 passed, 4 skipped`。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：106 files formatted。
- `python tools/release_gate.py`：通过，206 个跟踪文件、226 个归档成员；秘密模式、Shell LF 与归档路径均通过。
- 三份 Compose YAML 通过 PyYAML 解析；当前 Windows 主机没有可用 Bash/WSL Linux 发行版，Shell `-n` 留给 Ubuntu CI。
- `git diff --check`：通过。
- `detect-secrets==1.5.0` 扫描全部 Git 跟踪文件：7 个命中均为测试夹具/占位值，人工复核未发现真实凭据。
- Windows 跳过项必须由 Ubuntu GitHub Actions 覆盖，包括健康标记、目录符号链接激活/回滚和只读状态文件测试。

五个 PR 的 push 与 pull request 两组 Ubuntu CI 均通过，Shell 语法检查和 Linux 零跳过门已通过。PR #7–#11 已按顺序合并；这些证据仍不代表官方主人沙箱、NapCat 48 小时观测、官方 72 小时在线、生产部署或真实消息验收。

## 4. 生产只读预检（部署前）

- 已使用本机既有密钥与已知主机指纹完成 SSH 只读连接；没有输出或记录服务器地址、凭据和账号标识。
- 服务器实际运行版本仍为记录中的 `d7aa96d`；Docker 与现有 Higgs systemd 服务 active，NapCat 容器 healthy，但 QQ 已离线，agent 因权威在线探针失败而 unhealthy。
- NapCat 最近日志存在两次踢线信号，没有发现网络风暴或发送超时信号；不自动重启或尝试登录。
- 现有十个数据库中九个 `integrity_check=ok`。`memory.sqlite` 的五条旧记录仍使用 ALTER TABLE 之前的物理行编码，旧版 SQLite 对新增的 `importance/source_trust` 默认值报告 NOT NULL 完整性错误；逻辑读取值正常。
- 已增加一次性的 schema v3 物化迁移：只把缺失的默认字段写成既定默认值，并用新测试固定；PR #14 与合并后主线 CI 已通过。
- 私有环境文件权限保持 root-only/agent-only；OneBot 未发布宿主端口。官方 QQ 与模型候选提取在部署时必须显式保持关闭。
- 已创建 root-only 部署前原始恢复快照，十库与两份私有配置均有可回滚副本；九库验证通过，旧 memory 告警按原样保留。
- 已安装并激活不可变源码发布 `acb49ed1377d9fe43fa7737e9af4eb3309e67585`，旧 current 链接已移入 `/srv/trash`；运行中的旧 agent/NapCat 容器尚未重建。
- 两次镜像构建都在 `uv sync --frozen` 访问锁文件中的上游 wheel URL 时停滞，均已有限等待后取消且无残留构建进程。临时容器通过腾讯镜像安装同一 SDK/依赖仅需数秒，确认不是依赖冲突。
- OpenCloudOS Dockerfile 已改为先从腾讯镜像按锁定版本预热实际 venv，再强制两次 offline frozen sync；新增顺序测试后本地为 `251 passed, 4 skipped`，必须先经 PR/CI 才继续构建。
- 上述运行依赖预热已在生产构建中成功，但最终离线安装发现 build-system 的 hatchling 不在运行依赖导出中。已固定 `hatchling==1.27.0` 并增加独立构建后端预热；服务器隔离探针验证该版本及五个构建依赖可从腾讯镜像取得，本地仍为 `251 passed, 4 skipped`。
- 后续生产构建进一步证明 editable 项目安装会额外索取仅开发态需要的 `editables`。最终项目同步现明确使用 `--no-editable`，保持生产安装为普通 wheel 语义，并继续要求全程离线。

## 5. 上游固定与借鉴边界

- 官方 `qqbot-agent-sdk==1.2.2`，调研提交 `6163b5dc979a2f12379b1916805009075008c3c3`，MIT，Beta；SDK 类型被 fail-closed 适配层隔离。
- corlinman `v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`，MIT；只借鉴治理、窄 IPC、真实发送回执与安全下载设计，没有复制源码。
- NapCat 当前生产记录为 `v4.18.13`，上游为 Limited Redistribution License；作为独立部署依赖，不复制内部代码。完整镜像 digest 与实际 QQNT build 必须在发布前从私有配置重新核对。
- LLBot/Lagrange 仅隔离调研，不进入生产，也不视为个人 QQ 风控的根治方案。

## 6. 下一步顺序

1. 先让 OpenCloudOS 构建后端预热修复通过 PR/Ubuntu CI，再从新的主线提交生成并校验不可变发布包。
2. 构建新 agent 镜像，原子更新私有镜像指针并显式关闭官方 QQ/模型候选提取；只重建 agent，完成 schema v3 后复核十二库完整性。
3. 安装宿主只读状态 timer；确认安全恢复策略后再处理 NapCat Compose 变更，随后请主人扫码恢复登录并启动 48 小时匿名观测。
4. 需要真实官方联调时，请主人登录 QQ 机器人开放平台创建沙箱应用；AppID/AppSecret 只写入服务器 mode `0600` 私有配置，不在聊天中传递。
5. 官方灰度固定为：假 Gateway → 主人沙箱私聊 → 72 小时与进程重启 Resume → 一个仅 `@` 测试群 → 再评估扩大。

## 7. 明确未完成事项

- 尚无生产实时状态、NapCat 48 小时观测或此次 24 小时掉线问题的匿名证据。
- 尚无官方 QQ Bot 应用、主人 OpenID 私有绑定、真实 Token/Gateway 或 72 小时 Resume 证据。
- 阶段 3 的 systemd timer 尚未安装；宿主状态 JSON 尚未在生产生成。
- Memory V2.1 仅有确定性/模拟模型评测；尚未使用真实模型配置运行聚合评测，因此不得启用生产候选提取。
- 搜索、文件下载、MCP 与跨通道普通用户合并仍延期，不得从当前工具框架自行扩大权限。
- 官方提醒目标迁移到显式 `channel + target_id` 前，提醒继续只由 NapCat 发送。

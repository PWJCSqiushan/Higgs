# Higgs 权威接管交接（2026-08-26）

> 本文件是下一次接手的第一入口。不得写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态内容。

## 1. 当前权威边界

- 本地统一项目根：`D:\丘山\R\_Higgs`；主仓库在 `source`，阶段工作树在 `worktrees`，私有归档和发布包分别在 `archives`、`artifacts`。
- 本地权威集成工作树：`D:\丘山\R\_Higgs\worktrees\R_Higgs-takeover-20260826`，分支 `codex/higgs-integration-20260826`。
- PR/生产验收工作树：`D:\丘山\R\_Higgs\worktrees\Higgs-wt-pr-stack`；当前记录分支为 `codex/higgs-recovery-and-local-consolidation-20260827`。
- 官方 QQ 硬化已由 PR #21 合并到 GitHub `main` 的 `aa877df`；当前同一工作树转入仅更新交接记录的 `codex/higgs-official-qq-handoff-20260827`。代码尚未生产部署，官方通道继续关闭。
- 生产源码/Agent 镜像仍为 `b7d0beceed3f5bd057ad15490cb5b0f2ac0a01d3`；GitHub 主线随后已合并确定性测试和生产交接记录，生产运行提交与文档主线必须继续明确区分。
- GitHub 已按批准顺序合并 PR #7–#17；所有功能、迁移和 OpenCloudOS 离线构建修复均通过分支、PR 与合并后主线 CI，没有直接向 `main` 推送。
- 已按主人确认完成本阶段生产部署，并保持既有 `live` 回复模式；官方 QQ 和模型记忆候选仍显式关闭。
- 开放官方主人沙箱、加入测试群、启用模型候选或改变 live 状态仍必须获得单独确认。

上述生产提交与健康结论来自 2026-08-26 的实时发布验收；后续继续操作仍须重新核对主线、镜像和匿名 transport 状态，不能把本次结果当作永久在线保证。

## 2. 已完成代码阶段

| 阶段 | 总集成提交 | 独立阶段分支/提交 | 状态 |
| --- | --- | --- | --- |
| 0 发布基线 | `f134fc9` | `codex/higgs-takeover-20260826` / PR #7（已合并） | LF、无固定 deploy 用户、可配置根目录、校验、原子激活与可验证回滚已实现 |
| 1 NapCat 可观测 | `00f5831` + `9e7ff52` | `codex/higgs-phase1-stability-20260826` / PR #8（已合并） | 六维匿名状态、真实只读健康标记、告警/恢复幂等、有限进程恢复与 `transport.sqlite` 已实现 |
| 2 官方 QQ 双通道 | `945b5b2` + `92df3d2` + `30ca0c5` + `abc4a0c` | `codex/higgs-phase2-official-qq-20260826` / PR #9（已合并） | 官方 SDK 1.2.2、Gateway/Resume、有限监督恢复、统一类型回执、身份隔离和被动原路回复已实现；默认关闭 |
| 2A 官方 QQ fail-closed 硬化 | `aa877df` | `codex/higgs-official-qq-mvp-20260827` / PR #21（已合并） | 私有 Resume/READY 身份、真实鉴权状态、精确 intents、有限 SDK 重连、异常会话断链和发送幂等已完成；仍默认关闭 |
| 3 只读工具 | `80c1c86` + `b083ccf` + `5fa5bc3` | `codex/higgs-phase3-governed-tools-20260826` / PR #10（已合并） | `/higgs server status` 仅限主人私聊；审批哈希、默认拒绝、审计、限频、超时、幂等和只读宿主快照已实现 |
| 4 Memory V2.1 | `d52739b` + `56cdda2` | `codex/higgs-phase4-memory-shadow-20260826` / PR #11（已合并） | 严格 JSON 模型候选、敏感隔离、追加式 shadow 队列、36 例中文全提取链路评测与主人只读队列已实现；默认关闭 |

2026-08-27 的官方 QQ 后续硬化在独立分支继续进行：SDK Resume 状态改为 Higgs 自有的原子 `0600` 私有文件；真实 READY/RESUMED 前不再报告认证成功；断线和心跳超时清除在线状态；READY 身份被安全持久化供进程重启 Resume；过期或不完整的 Resume 会清除旧身份并等待新 READY；官方关闭时其身份和群配置不进入 OneBot 权限集合。该分支还把 SDK intents 收窄到群/C2C 公共消息、把内部重连限制为 5 次、对异常 Invalid Session 同时停止读取循环并主动关闭 WebSocket、屏蔽 SDK 中可能包含会话 ID/OpenID 的日志，并关闭同进程并发幂等竞态。所有行为仍默认关闭且尚未生产部署。

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

## 4. 生产预检、部署与实时验收

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
- PR #16 固定并预热 `hatchling==1.27.0`；PR #17 将最终项目安装固定为非 editable。两者的分支、PR 和合并后主线 CI 均通过，最终不可变发布与镜像提交为 `b7d0beceed3f5bd057ad15490cb5b0f2ac0a01d3`。
- 最终镜像在生产宿主完成断网、只读 smoke test，`r-agent==0.2.0` 与 `qqbot-agent-sdk==1.2.2` 版本断言通过；Agent 已只重建到该不可变镜像。
- schema v3 物化迁移后，十二个运行数据库全部 `integrity_check=ok`；旧记忆仍为六条。最新 startup 一致性备份包含十二库、`quick_check=ok` 且 manifest 明确不含秘密。
- 宿主只读状态 service/timer 已安装并 active，允许字段 JSON、原子写入、权限和新 Agent 只读挂载均已验证。
- NapCat 已重建并应用固定 digest、`on-failure:5` 与共享健康标记；WebUI 管理 Token 只在受控本地页面中使用，未进入聊天、文档或磁盘临时文件。
- 2026-08-26 21:17（Asia/Shanghai）实时匿名验收为：NapCat healthy、OneBot 可达、QQ 权威在线、账号匹配、最近健康/action 回执均成功，Agent healthy，恢复结果已写入 `transport.sqlite`。此时起进入至少 48 小时观察，不把初始恢复视为稳定性结论。
- 观察在 2026-08-26 23:38 记录到明确 `KickedOffLine`，初次恢复后约 2 小时 21 分即再次失效；OneBot 端口和 NapCat 容器仍健康，但 QQ 权威状态离线、Agent unhealthy。该结果证明原有长期在线问题尚未解决。
- 失效会话持续约 11 小时 54 分。WebUI 同时出现“登录态失效”和“账号已登录、无法重复登录”，确认是 QQ 进程残留的假登录状态；密码路径未被 Agent 读取、保存或继续使用。
- 经主人明确要求处理登录后，只执行一次受控 NapCat 重启以清除旧进程，未形成自动重启循环；随后由主人扫码。2026-08-27 11:34 实时复核重新满足 QQ 在线、账号匹配、OneBot/action/health 成功及 NapCat/Agent healthy，恢复事件写入 `transport.sqlite`。
- 该人工恢复只维持约 1 小时 54 分：2026-08-27 13:28 再次出现明确 `KickedOffLine`，登录态失效；NapCat 容器和 OneBot 仍可达，QQ 权威离线且 Agent unhealthy。主人再次明确授权临时恢复后，只执行一次受控重启并由主人扫码，没有循环登录。2026-08-27 16:00 匿名权威复核重新满足 QQ 在线、账号匹配、NapCat/Agent healthy，随后关闭本地 WebUI 隧道。第二次快速踢线使 48 小时稳定性结论明确失败，即使当前临时在线也不得宣称问题解决。

## 5. 上游固定与借鉴边界

- 官方 `qqbot-agent-sdk==1.2.2`，调研提交 `6163b5dc979a2f12379b1916805009075008c3c3`，MIT，Beta；SDK 类型被 fail-closed 适配层隔离。
- corlinman `v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`，MIT；只借鉴治理、窄 IPC、真实发送回执与安全下载设计，没有复制源码。
- NapCat 当前生产记录为 `v4.18.13`，上游为 Limited Redistribution License；作为独立部署依赖，不复制内部代码。完整镜像 digest 与实际 QQNT build 必须在发布前从私有配置重新核对。
- LLBot/Lagrange 仅隔离调研，不进入生产，也不视为个人 QQ 风控的根治方案。

## 6. 下一步顺序

1. 请主人登录 QQ 机器人开放平台创建沙箱应用；AppID/AppSecret 不经聊天，只在操作时写入服务器 mode `0600` 私有配置。生产模式在当前适配器中显式拒绝。
2. 官方灰度固定为：假 Gateway → 主人沙箱私聊 → 72 小时与进程重启 Resume → 一个仅 `@` 测试群 → 再评估扩大；提醒仍只走 NapCat。
3. 观察任务保留到原定截止时间并生成匿名结论；已经捕获两次快速 `KickedOffLine`，结论必须为失败，不以再次人工恢复重置证据。

## 7. 本地目录结构（2026-08-27）

- 已将散落在 `D:\丘山` 根目录的主仓库、八个 D 盘阶段/交接工作树、私有归档和发布包统一移动到 `D:\丘山\R\_Higgs`；没有删除文件。
- 结构固定为：`source`（主仓库）、`worktrees`（Git 工作树）、`archives`（私有归档）、`artifacts`（发布包）。
- 所有移动前 D 盘工作树均为干净状态；移动使用 `git worktree move`，主仓库移动后执行 `git worktree repair`。九个 D 盘工作树逐一验证路径、分支、提交和 `git status` 正常。
- 移动后旧 `.venv` 的启动脚本仍引用旧绝对路径；九份旧虚拟环境已完整移入 `archives/replaced-venvs/20260827-114344`，未删除。当前 PR 工作树已从锁文件重建环境，Ruff、格式和完整 pytest（`251 passed, 4 skipped`）重新通过；其他工作树需要使用时再按各自锁文件重建。
- 四个早期工作树仍位于 `C:\Users\32516`，不属于本次 D 盘根目录清理；其中 Memory V2.1 旧工作树存在八项未提交内容，严禁在未单独审计前移动、清理或覆盖。

## 8. 明确未完成事项

- 48 小时观察尚未结束，且已捕获一次明确 `KickedOffLine`；不能宣称长期在线问题已解决。人工恢复后的连续在线时长需重新累计，同时保留原观察窗口的失败证据。
- 尚无官方 QQ Bot 应用、主人 OpenID 私有绑定、真实 Token/Gateway 或 72 小时 Resume 证据。
- 官方硬化已经 PR #21 合并但尚未部署；`TransportRegistry` 仍未成为运行时统一编排入口，主人状态命令也尚未汇总官方通道。官方发送的同进程并发幂等已封闭，但跨进程回执持久化和已知失败/未知回执细分仍待后续独立切片。
- 阶段 3 的 systemd timer 与宿主状态 JSON 已部署验收；模型仅允许 shadow 建议，真实工具调用仍受 owner、显式命令和治理边界限制。
- Memory V2.1 仅有确定性/模拟模型评测；尚未使用真实模型配置运行聚合评测，因此不得启用生产候选提取。
- 搜索、文件下载、MCP 与跨通道普通用户合并仍延期，不得从当前工具框架自行扩大权限。
- 官方提醒目标迁移到显式 `channel + target_id` 前，提醒继续只由 NapCat 发送。

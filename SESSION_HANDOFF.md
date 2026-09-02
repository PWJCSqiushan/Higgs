# Higgs 权威接管交接（2026-08-26）

> 本文件是下一次接手的第一入口。不得写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态内容。

## 0. 当前权威状态（2026-09-01）

- GitHub `main` 已包含生产记录 PR #72，合并提交为
  `0cd89e2fee1869b259d5d84d256e1fb7d2ddc508`；当前功能判断先读
  `docs/29-capability-ledger-2026-08-31.md`，再读本文件末尾最新节点。
- 生产 release、Agent 与官方 Sidecar 镜像均为 `35c1fcd3e30e703f29b5c7874c5a840ae17e24a7`，
  Persona Bundle 为 `2.2.0`。官方 owner C2C 被动回复、durable 处理和 Persona 2.2 保持启用。
- self-memory schema/mode、群记忆、普通用户 C2C、官方群和 proactive 仍关闭；摄影观点
  尚未导入。普通用户/群、自我记忆、Stage 4 工具和普通用户任务现为 `deployed-off`，
  不能写成已经对用户开放。
- 官方群业务面只接收 `GROUP_AT_MESSAGE_CREATE`；白名单群成员必须 `@Higgs`，未 `@`
  的普通群消息不进入官方 Bot 管线。
- 下方“当前权威边界”是 2026-08-29 的历史快照，保留用于追溯，不再代表当前生产版本。

权威能力状态、过时文档清单和后续顺序见
[`docs/29-capability-ledger-2026-08-31.md`](docs/29-capability-ledger-2026-08-31.md)。

## 1. 当前权威边界

- 本地统一项目根：`D:\丘山\R\_Higgs`；主仓库在 `source`，阶段工作树在 `worktrees`，私有归档和发布包分别在 `archives`、`artifacts`。
- 本地权威集成工作树：`D:\丘山\R\_Higgs\worktrees\R_Higgs-takeover-20260826`，分支 `codex/higgs-integration-20260826`。
- 当前官方 QQ 修复工作树：`D:\丘山\R\_Higgs\worktrees\Higgs-wt-official-heartbeat-auth`；分支为 `codex/higgs-official-heartbeat-auth-20260829`。修复已由 PR #36 合并为主线 `f18ff1b8b4a86845316f960fdb7b8a350e5a2eec`，PR 与合并后主线 CI 全绿。
- 官方 Node UDS 运行时与一次性主人绑定器已经分别完成独立 PR/CI。主人 OpenID 已由首个合法官方 C2C 事件私有绑定到两份 `0600` 服务器配置；身份值从未回显，也未进入聊天、日志或项目记忆。
- 群聊风控误判修复已由 PR #23 合并到 GitHub `main` 的 `38a5ddc`，合并后主线 CI 通过；该修复现已随 Agent-only 发布进入生产。
- 生产源码、Agent 与官方 sidecar 镜像现为主线合并提交 `f18ff1b8b4a86845316f960fdb7b8a350e5a2eec`。平台 Gateway、首个心跳 ACK、私有 Resume 与 Agent 官方传输均已真实恢复，`qq_official` 当前为 `verified/resumed`、身份匹配为真；回复开关仍为 false。NapCat 容器在发布前后身份、启动时间和 health 均未改变，但个人 QQ 权威状态当前为离线，因此 Agent 的综合 Docker health 仍为 unhealthy。
- GitHub 已按批准顺序合并 PR #7–#17；所有功能、迁移和 OpenCloudOS 离线构建修复均通过分支、PR 与合并后主线 CI，没有直接向 `main` 推送。
- 已按主人确认完成官方回复关闭的 shadow 部署，并把现场摄取竞态修复经独立 PR/CI 发布到生产。官方 Bot 当前在线且业务摄取已恢复，但按设计不会回复；模型记忆候选仍显式关闭。
- 开放官方主人沙箱、加入测试群、启用模型候选或改变 live 状态仍必须获得单独确认。

上述最新生产提交与健康结论来自 2026-08-29 的实时发布验收；后续继续操作仍须重新核对主线、镜像和匿名 transport 状态，不能把本次结果当作永久在线保证。

## 2. 已完成代码阶段

| 阶段 | 总集成提交 | 独立阶段分支/提交 | 状态 |
| --- | --- | --- | --- |
| 0 发布基线 | `f134fc9` | `codex/higgs-takeover-20260826` / PR #7（已合并） | LF、无固定 deploy 用户、可配置根目录、校验、原子激活与可验证回滚已实现 |
| 1 NapCat 可观测 | `00f5831` + `9e7ff52` | `codex/higgs-phase1-stability-20260826` / PR #8（已合并） | 六维匿名状态、真实只读健康标记、告警/恢复幂等、有限进程恢复与 `transport.sqlite` 已实现 |
| 1A 群聊风控按成员隔离 | `38a5ddc` | `codex/higgs-group-sender-guard-20260827` / PR #23（已合并） | 自动化来源与非主人熔断在群聊中改为盐化的成员级作用域；群级/全局发送预算保持不变；已随 Agent-only 发布进入生产 |
| 2 官方 QQ 双通道 | `945b5b2` + `92df3d2` + `30ca0c5` + `abc4a0c` | `codex/higgs-phase2-official-qq-20260826` / PR #9（已合并） | 官方 SDK 1.2.2、Gateway/Resume、有限监督恢复、统一类型回执、身份隔离和被动原路回复已实现；默认关闭 |
| 2A 官方 QQ fail-closed 硬化 | `aa877df` | `codex/higgs-official-qq-mvp-20260827` / PR #21（已合并） | 私有 Resume/READY 身份、真实鉴权状态、精确 intents、有限 SDK 重连、异常会话断链和发送幂等已完成；仍默认关闭 |
| 2B 官方主人一次性捕获 | `187a959` + `36e936d` | `codex/higgs-official-owner-capture-20260828` / PR #25（已合并） | 显式单测试用户确认、首个 READY 后 C2C、无正文日志、私有备份、原子 OpenID 绑定与成功即停已实现并禁用态部署；尚未真实捕获 |
| 2C 官方 Node UDS 与首 ACK 认证 | `f18ff1b` | `codex/higgs-official-heartbeat-auth-20260829` / PR #36（已合并） | Node 独占 Gateway、私有 Resume、`0600` UDS、Python 业务摄取及 `heartbeat_pending` 首 ACK 门控已部署；当前 `verified/resumed`，回复仍关闭 |
| 3 只读工具 | `80c1c86` + `b083ccf` + `5fa5bc3` | `codex/higgs-phase3-governed-tools-20260826` / PR #10（已合并） | `/higgs server status` 仅限主人私聊；审批哈希、默认拒绝、审计、限频、超时、幂等和只读宿主快照已实现 |
| 4 Memory V2.1 | `d52739b` + `56cdda2` | `codex/higgs-phase4-memory-shadow-20260826` / PR #11（已合并） | 严格 JSON 模型候选、敏感隔离、追加式 shadow 队列、36 例中文全提取链路评测与主人只读队列已实现；默认关闭 |

2026-08-27 的官方 QQ 后续硬化在独立分支继续进行：SDK Resume 状态改为 Higgs 自有的原子 `0600` 私有文件；真实 READY/RESUMED 前不再报告认证成功；断线和心跳超时清除在线状态；READY 身份被安全持久化供进程重启 Resume；过期或不完整的 Resume 会清除旧身份并等待新 READY；官方关闭时其身份和群配置不进入 OneBot 权限集合。该分支还把 SDK intents 收窄到群/C2C 公共消息、把内部重连限制为 5 次、对异常 Invalid Session 同时停止读取循环并主动关闭 WebSocket、屏蔽 SDK 中可能包含会话 ID/OpenID 的日志，并关闭同进程并发幂等竞态。代码已随禁用态 Agent 发布进入生产，所有行为仍默认关闭。

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
- 2026-08-27 群聊风控修复本地完整 pytest 为 `271 passed, 4 skipped`；Ruff 与格式检查通过。新增旧 `risk_events` 在线迁移、群成员来源隔离、熔断隔离、运行管线 sender scope 透传和明文身份不落风控库测试。
- PR #23 的分支与 pull request 两组 Ubuntu CI 均通过；合并提交 `38a5ddc` 的主线 CI 同样通过。该证据只代表源码合并，不代表生产部署。
- 后续交接 PR #24 在晚间暴露两个 `today` 计划测试依赖真实墙钟；测试现固定上海上午时间及对应 epoch。针对文件 10 项、Ruff、格式检查和本地完整 pytest（`271 passed, 4 skipped`）通过，等待 PR #24 重跑 Ubuntu CI。
- 2026-08-28 官方主人捕获切片本地完整 pytest 为 `282 passed, 5 skipped`；Ruff、格式、Git Bash 语法和发布门通过。新增文件的 `detect-secrets==1.5.0` 扫描为零命中；5 个 Windows 跳过项包含既有符号链接场景与新增 POSIX `0600`/symlink 契约，必须由 Ubuntu CI 补跑。

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
- 2026-08-27 群聊匿名审计发现：白名单与自然触发配置均已正确保存，但多个普通成员的高频入站被旧实现按整个群累计，错误触发 24 小时来源冷却和 1 小时会话熔断；主人绕过这两层，因此表象为只回复主人。经明确授权，先为两个风控库创建私有一致性备份，再只清除该群的误判来源状态、熔断状态和 8 条临时计数；没有读取正文、发送测试消息、重启或重新登录。

## 5. 上游固定与借鉴边界

- 官方 `qqbot-agent-sdk==1.2.2`，调研提交 `6163b5dc979a2f12379b1916805009075008c3c3`，MIT，Beta；SDK 类型被 fail-closed 适配层隔离。
- corlinman `v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`，MIT；只借鉴治理、窄 IPC、真实发送回执与安全下载设计，没有复制源码。
- NapCat 当前生产记录为 `v4.18.13`，上游为 Limited Redistribution License；作为独立部署依赖，不复制内部代码。完整镜像 digest 与实际 QQNT build 必须在发布前从私有配置重新核对。
- LLBot/Lagrange 仅隔离调研，不进入生产，也不视为个人 QQ 风控的根治方案。

## 6. 下一步顺序

1. 先设计并实现官方入站事件与发送回执的协调持久化，封闭 SDK 先保存 sequence、业务事件尚未进入 Agent journal 时的崩溃丢失窗口；完成前不得把 `R_AGENT_OFFICIAL_QQ_REPLY_ENABLED` 改为 true。
2. 单独修复 systemd 生命周期边界：当前官方 unit 的 `ExecStop` 会停止整栈，而 `ExecStart --wait` 又受个人 QQ 离线导致的 Agent unhealthy 影响。不得直接 `restart` 该 unit；应先通过独立 PR/CI 设计不影响 NapCat 的官方进程 Resume 验收入口。
3. 在回复关闭状态持续观察官方通道至少 72 小时，记录匿名 heartbeat、Resume、重连、transport 转换和容器重启次数；不得发送自动测试消息。当前官方 unit enabled/inactive、旧基础 unit disabled/active，主机重启路径尚未验收。
4. 在事件/回执协调持久化和崩溃恢复方案完成前，不得开启官方回复。之后灰度顺序仍为主人沙箱私聊 → 72 小时与进程重启 Resume → 一个仅 `@` 测试群 → 再评估扩大；提醒继续只走 NapCat。
5. NapCat 的原 48 小时观察已以多次快速 `KickedOffLine` 判定失败并停止；不自动重启、重复登录或把容器健康误报为 QQ 在线。

## 7. 本地目录结构（2026-08-27）

- 已将散落在 `D:\丘山` 根目录的主仓库、八个 D 盘阶段/交接工作树、私有归档和发布包统一移动到 `D:\丘山\R\_Higgs`；没有删除文件。
- 结构固定为：`source`（主仓库）、`worktrees`（Git 工作树）、`archives`（私有归档）、`artifacts`（发布包）。
- 所有移动前 D 盘工作树均为干净状态；移动使用 `git worktree move`，主仓库移动后执行 `git worktree repair`。九个 D 盘工作树逐一验证路径、分支、提交和 `git status` 正常。
- 移动后旧 `.venv` 的启动脚本仍引用旧绝对路径；九份旧虚拟环境已完整移入 `archives/replaced-venvs/20260827-114344`，未删除。当前 PR 工作树已从锁文件重建环境，Ruff、格式和完整 pytest（`251 passed, 4 skipped`）重新通过；其他工作树需要使用时再按各自锁文件重建。
- 四个早期工作树仍位于 `C:\Users\32516`，不属于本次 D 盘根目录清理；其中 Memory V2.1 旧工作树存在八项未提交内容，严禁在未单独审计前移动、清理或覆盖。

## 8. 明确未完成事项

- NapCat 的 48 小时观察已失败并结束；捕获到多次明确 `KickedOffLine`，不能宣称个人 QQ 长期在线问题已解决。
- 官方 QQ Bot 应用、私有凭据、主人测试用户、主人 OpenID 私有绑定及回复关闭 shadow 已具备；真实 Gateway 已在线，但尚无 systemd 重启 Resume、72 小时连续在线或真实回复证据。
- 官方硬化已经 PR #21 合并并随禁用态 Agent 部署；`TransportRegistry` 仍未成为运行时统一编排入口，主人状态命令也尚未汇总官方通道。官方发送的同进程并发幂等已封闭，但跨进程回执持久化和已知失败/未知回执细分仍待后续独立切片。
- 群聊风控按成员隔离修复已由 PR #23 合并并随 Agent-only 发布进入生产；没有发送真实群聊测试消息，因此当前只有代码、CI 与部署证据，尚无真实普通成员回归验收。
- 阶段 3 的 systemd timer 与宿主状态 JSON 已部署验收；模型仅允许 shadow 建议，真实工具调用仍受 owner、显式命令和治理边界限制。
- Memory V2.1 仅有确定性/模拟模型评测；尚未使用真实模型配置运行聚合评测，因此不得启用生产候选提取。
- 搜索、文件下载、MCP 与跨通道普通用户合并仍延期，不得从当前工具框架自行扩大权限。
- 官方提醒目标迁移到显式 `channel + target_id` 前，提醒继续只由 NapCat 发送。

## 9. 2026-08-28 关机前官方沙箱部署检查点

- 主人确认继续官方 QQ 下一步后，重新执行本地发布门：完整 pytest 为 `271 passed, 4 skipped`，Ruff、格式检查、秘密扫描、Shell LF 与发布包校验均通过。
- 已在本地 `artifacts` 生成提交 `d2d40a7e47618022e258d3a534f62aab68b04833` 的完整发布包；另生成从当前生产基线到该提交的运行时补丁及压缩件。产物均只含 Git 跟踪代码与文档，不含凭据、账号、OpenID、聊天正文或服务器信息。
- 腾讯云 OrcaTerm 的 MFA 已由主人完成，随后只执行匿名 shell 探针与生产基线读取。探针成功；当前源码链接仍指向既有生产发布，NapCat healthy，Agent 因既有 QQ 离线状态 unhealthy。没有上传文件、激活发布、构建镜像、修改私有配置、重启容器或发送消息。
- 本机现有 SSH 私钥均未通过该服务器的严格已知主机验证，未创建新密钥、未更改服务器访问权限。OrcaTerm 文件管理器上传控件未能通过自动化文件选择器触发；腾讯云实例“文件管理”页面已确认存在独立“上传”入口，暂停时尚未选择或传输文件。
- 现有官方适配器必须预先配置主人 OpenID 才能启动，平台测试用户列表只显示 QQ 号且不提供 OpenID；代码中没有首条消息自动捕获或待审批机制。不得绕过该门控或把 QQ 号当作 OpenID。下一次应先完成禁用态不可变发布，再为一次性、无正文日志、仅单一测试用户可用的显式主人 OpenID 捕获流程建立独立代码切片与测试，走 PR/CI 后才运行。
- 关机后 OrcaTerm/MFA 会话可能过期。续接顺序：恢复腾讯云登录 → 使用实例文件管理上传并核验完整发布包 SHA-256 → 激活不可变发布 → 确认官方仍关闭 → 只构建和重建 Agent（`--no-deps`），前后验证 NapCat 容器 ID 与启动时间不变 → 验收禁用态 → 开发并审核主人 OpenID 捕获切片 → 私有绑定 → 再申请/确认官方主人沙箱启用与真实私聊验收。

## 10. 2026-08-28 禁用态官方适配器生产部署

- 腾讯云实例文件管理成功上传完整 Git 归档；服务器端 SHA-256 与本地发布记录完全一致后才继续。服务器无法访问 GitHub 的只读查询已有限等待并主动中止，没有形成后台下载或残留进程。
- 私有配置预检确认文件权限为 `0600`、AppID/AppSecret 各恰好一条、主人 OpenID 为零条、官方启用值为安全关闭；没有回显任何值。
- 原子激活不可变源码发布 `d2d40a7e47618022e258d3a534f62aab68b04833`，旧 `current` 由发布脚本移入 `/srv/trash`。新 Agent 镜像使用相同 40 位提交标签构建成功。
- 主机没有 Python，第一次直接调用原子配置脚本只返回命令不存在且未修改配置；随后使用新 Agent 镜像临时、无网络运行同一脚本，备份两份私有环境文件到 `/srv/trash` 并原子更新镜像标签，未输出秘密。
- 仅执行 `docker compose ... up -d --no-deps --no-build agent`。部署前后匿名比较确认 NapCat 容器身份与启动时间完全一致；NapCat 未重启、未重新登录、未发送测试消息。
- 部署后 Agent 正在运行并使用新不可变镜像；12 个 SQLite 文件可见，官方 `transport_state` 行数为零，近 10 分钟 fatal 标记和秘密变量标记均为零。OneBot 端点仍可达且 NapCat 容器健康，但个人 QQ 权威在线为 false、账号匹配未知，Agent 因强制在线健康门保持 unhealthy；这不是官方适配器启动失败。
- 群成员级风控修复已随本次 Agent-only 发布进入生产，但未发送真实消息验证。官方通道仍关闭，主人 OpenID 捕获机制尚未实现；下一代码切片必须继续保持显式运维启动、单一首个 C2C、无正文日志、原子私有绑定、成功即退出和默认关闭。

## 11. 2026-08-28 官方主人 OpenID 捕获切片

- 新建统一目录内独立工作树 `Higgs-wt-official-owner-capture` 和分支 `codex/higgs-official-owner-capture-20260828`，基于禁用态部署记忆提交 `fa8a300`；未修改或覆盖其他工作树。
- 新增独立运维 CLI 和服务器包装脚本。包装脚本要求固定确认短语，验证平台只有主人一个测试用户的责任仍由操作员承担；使用独占 `flock`，只启动一个 `docker compose run --rm --no-deps agent` 临时进程，不操作常驻 Agent 或 NapCat。
- 捕获适配器只接受 READY/RESUMED 后首个合法 `C2C_MESSAGE_CREATE`，忽略群聊、未知事件、未就绪事件、scope 不匹配和第二个并发身份；不会构造业务入站事件、写入消息 ID/正文或发送任何回复。
- 私有绑定前拒绝 symlink、非普通文件、超大文件、非 `0600`、重复凭据、已存在主人、官方已启用或非沙箱状态。原文件先复制到私有备份目录，再以同目录临时文件、fsync、权限/所有者继承和 `os.replace` 原子写入；失败临时文件只移入私有备份目录，不直接删除。
- 成功后只输出匿名状态，复核主人变量恰好一条、私有文件仍为 `0600`、官方仍关闭，并立即停止临时 Gateway。超时或启动失败同样停止 Gateway，不添加主人绑定。
- 功能提交经 rebase 后为 `187a959`，已推送独立分支并创建 PR #25。GitHub 在该提交上运行的两组 Ubuntu `Higgs CI / test` 均通过，合并状态为 clean；本地定向测试为 `14 passed, 3 skipped`，完整 pytest 为 `282 passed, 5 skipped`，Ruff、格式、Git Bash `-n`、发布门和新增文件秘密扫描均通过。
- 文档检查点提交 `36e936d` 后的两组 PR CI 均通过；PR #25 经人工验收合并为主线提交 `9cfbc69363008330d6b9bcbd9002c0aaa7bf2290`，合并后主线 CI 与 Dependency Graph 均通过。

## 12. 2026-08-28 一次性主人捕获禁用态生产部署

- 从主线合并提交生成只含 Git 跟踪文件的发布包，本地与服务器端 SHA-256 完全一致；腾讯云文件管理显示一项上传任务完成。没有把私有配置、登录状态或账号数据装入发布包。
- 部署前匿名门控为 AppID 一条、ClientSecret 一条、主人 OpenID 零条、官方启用 false。原子激活不可变发布 `9cfbc69363008330d6b9bcbd9002c0aaa7bf2290`，旧 `current` 进入 `/srv/trash`；新 Agent 镜像以相同提交标签构建成功。
- 使用新镜像离线运行既有原子配置脚本，私有环境先备份到 `/srv/trash`，再更新不可变镜像标签；没有打印秘密。只执行 Agent 的 `--no-deps --no-build` 重建，匿名比较确认 NapCat 容器身份与启动时间均未改变。
- 部署验收为 Agent running、active release 与镜像匹配、捕获脚本可执行、主人 OpenID 仍为零条、官方启用仍为 false。真实捕获 Gateway 尚未启动，未读取或写入主人 OpenID，也未发送任何 QQ 消息。

## 13. 2026-08-28 官方捕获 Resume 现场诊断与修复中

- 平台仍仅登记主人测试用户；三次显式五分钟捕获均安全超时，未绑定身份、未记录消息正文或 ID、未发送回复，官方通道始终关闭。通过平台提供的官方机器人入口重试后仍未捕获，因此排除单纯误发旧个人 QQ 会话。
- 实时匿名时序诊断确认 Gateway 在 2、10、25 秒均 READY 且 authenticated；首个心跳周期后，45 与 75 秒仍有 ACK、底层连接未立即退出，但 authenticated 被清空且事件始终为零。SDK 1.2.2 对 op 9 清除 Resume 后以 graceful close 结束读取，外层 loop 未进入异常重连，Higgs 旧状态因此可能残留假连接；捕获器又没有生产 supervisor，后续 C2C 被 fail-closed 门控丢弃。
- 新建独立分支 `codex/higgs-official-capture-resume-fix-20260828`：一次性捕获改用独立私有会话文件，并在每次启动前只清理该 App 的捕获记录，强制 fresh Identify，不再读取或污染生产 Resume；有效 op 7/op 9 立即发布 disconnected，session 清理同时清除 connected、身份与开始时间并标记匿名 `session_invalidated`。
- 新增回归测试覆盖捕获会话与生产 Resume 隔离、旧捕获记录强制清理、有效 op 7/op 9 断线通知及 session invalidation 的完整 fail-closed 状态；定向测试为 `29 passed, 1 skipped`，完整 pytest 为 `285 passed, 5 skipped`，Ruff、格式与发布门通过。当前 Windows 环境没有可用 Bash/WSL 发行版，两个发布脚本的 `bash -n` 留给 Ubuntu CI 复核。尚未提交、推送、部署或再次要求主人发送消息。

## 14. 2026-08-28 捕获 Resume 修复部署与有限监督修复中

- 捕获 Resume 修复经独立 PR #27、分支 CI、PR CI 与合并后主线 CI 通过，合并提交为 `fa62bebadadac727a9fd743feb290f2482dab676`。对应不可变发布已只重建 Agent；匿名验收确认源码、栈与容器镜像一致，NapCat 容器身份和启动时间未变，官方通道仍关闭，主人 OpenID 仍未绑定。
- 主人在修复后的真实捕获窗口从官方入口发送后，私有配置仍为主人零条、官方关闭、权限正确。该次发送没有完成绑定，也没有记录正文、身份或消息 ID，更没有发送回复。
- 复核确定剩余缺口不是 Resume 污染，而是 `OfficialQQOwnerCapture` 只调用 `start()` 后等待事件，未运行常驻适配器已有的监督循环；SDK 正常关闭读取后临时捕获进程无法自行恢复。原监督循环只限制连续失败次数，短暂恢复会重置计数，不适合作为一次性登录窗口的总预算。
- 新建独立分支 `codex/higgs-official-capture-supervisor-20260828`：公共监督接口增加可选的总重启预算，健康恢复只重置连续预算、不重置总预算；退避结束后再次检查健康，避免连接已恢复仍被多重启一次。一次性捕获固定为最多五次总重启，监督结束或异常均匿名 fail-closed，成功/超时退出时可靠取消监督任务并停止 Gateway。
- 新增回归覆盖总预算不会被短暂健康清零、退避期间恢复不重启、非法总预算拒绝，以及捕获器确实以五次总预算运行并在成功后取消监督。当前定向测试 `33 passed, 1 skipped`，完整测试 `289 passed, 5 skipped`，Ruff、格式与发布门通过；尚未提交、创建 PR、部署或再次要求主人发送。

## 15. 2026-08-28 官方 WebSocket 真实投递阻断与替代通道决策

- 总重启预算修复已由 PR #28 合并为主线提交 `b647b00db665a76d7ef6df7d85e88358b161061a`，并完成只重建 Agent 的禁用态生产发布；匿名验收确认发布、栈和容器镜像一致，NapCat 容器身份与启动时间未变化，官方开关仍关闭、主人 OpenID 仍为空。
- 真实主人捕获任务在平台显示在线期间仍没有绑定。随后运行两类只记录布尔值与匿名原因的探针：基础 Gateway 探针连续看到 `connecting -> ready`、connected 与 authenticated；事件门控探针持续 120 秒保持 READY，却没有收到任何 C2C 回调。探针不读取或保存身份、消息 ID、正文，也不发送回复。
- 再以 `GROUP_MESSAGES | DIRECT_MESSAGES` 兼容订阅组合执行 120 秒捕获，平台仍零事件并安全超时。由此排除 Higgs 解析、owner 比对和最小单一 intent 是首要阻断；当前失败边界位于平台到固定 Python SDK 1.2.2 的事件投递链路。主人 OpenID 没有写入，私有配置与官方禁用态保持不变。
- 平台开发设置确认当前接收方式为 WebSocket，IP 白名单为空时允许调用，且主人测试用户仍存在；通知中心无异常提示。好友公开范围关闭不应影响机器人管理员或开发体验成员，故不以扩大公开范围绕过沙箱门控。
- 腾讯官方 BotGo 已把旧 WebSocket 路径标记为淘汰方向；2026 年官方 `qqbot-nodejs` 同时提供 WebSocket 与 Webhook。新建分支 `codex/higgs-official-node-transport-20260828`，下一切片改为审计并实现官方 Node 协议适配，Python 业务、权限、记忆和治理仍只接收 Higgs 自有事件；现有 Python 官方适配器保持关闭态回退。真实部署、平台接收方式切换或开启官方通道仍需单独确认。

## 16. 2026-08-28 官方 Node 诊断 sidecar 实现中

- 官方 `tencent-connect/qqbot-nodejs` 审计锁定 npm `@tencent-connect/qqbot-nodejs==1.0.4`、MIT 和纯 ESM；公开仓库快照为 `ca55d9c395b582b7fcfad0ec27209c35dd04e0b3`。npm 包固定 integrity 为 `sha512-gU5HySLplczZXMUjM7NtiUACY7YfX9YlI/R9PKzCLMgLmHvwsX9L2sitsrYPMentGUr9b8NLfSaSTsndF77NBA==`，registry signature 验证通过，但其 `gitHead=589597a6cb5a24dce8230ba53bfba5390e13c073` 不在公开 GitHub 历史，包内元数据也与公开快照不同；已直接保留 MIT 全文，且在溯源差异解决或显式接受前只作诊断。SDK 支持 WebSocket/Webhook，但与 Python 共享同一平台协议，语言替换本身不能绕过平台事件授权。
- 新增 `apps/official-qq-sidecar`：固定依赖与 lockfile，精确订阅 `1 << 25`，SDK logger 全静默；READY 身份合法后才认证，READY 前事件和发送全部拒绝。只接受 C2C 与群 `@`，事件队列、帧体、字段、ID、文本和附件元数据均有界，游标缺口 fail-closed。
- sidecar 仅以 `0600` Unix Socket 提供版本化 hello/status/events/send；默认 `capture-only=true` 时队列只保留事件类型、私聊/群聊类别、接收时间和游标，不保留或返回机器人/发送者/群/消息身份、正文或附件元数据，发送接口直接拒绝。未来关闭 capture-only 后发送仍必须携带入站回复 ID，幂等键冲突拒绝，平台回执缺少非空 ID 时只报 `unknown`。匿名捕获 CLI 只输出连接/认证布尔值、固定原因和事件计数。
- 新增 opt-in Compose overlay 与 `official-qq` profile；sidecar 只接 egress、非 root、只读根、无 capabilities、无 Docker Socket/Agent 数据/NapCat 网络。凭据必须进入独立 `0600 official-qq.env`，不会挂给 Python Agent。该 overlay 尚未部署，旧 Python 官方适配器仍关闭。
- SDK 1.0.4 不公开 heartbeat ACK，且内部重连预算不满足 Higgs 长期生产治理。因此本切片明确是有时限、无 Resume 持久化的 capture-only 诊断，不得直接作为正式常驻通道；若真实 Node 捕获成功，再单独实现 Python UDS 客户端、受治理重连/会话和双通道健康；若仍零事件，则回到平台事件授权/沙箱配置，不继续更换语言盲试。
- 本地 Node `14 passed`；Python 完整 `290 passed, 5 skipped`（Windows 既有 POSIX 跳过）；Ruff、格式、release gate、npm registry signature、固定依赖树与 staged `detect-secrets==1.5.0` 均通过。提交 `02826e0` 与文档检查点 `ca5efd6` 经 PR #29 的 push/PR 两组 `test` 和两组 `official-qq-sidecar` 全绿后合并为主线 `0ec1b5b53c1ff14313147308e0cbf49623fa4524`；合并后主线 Python 与 Node/镜像/Compose CI 再次全部通过。尚未部署或执行真实 Node 捕获。

## 17. 2026-08-28 关机前暂停：Node 真实诊断已授权、尚未部署

- 主人已明确允许部署已披露 npm 溯源差异的官方 Node 1.0.4，但授权范围仍是一次 120 秒 capture-only 诊断；不得直接把该 SDK 作为长期生产通道。诊断必须不保留身份/消息 ID/正文、不发送回复，并确保同一 AppID 的 Python 与 Node Gateway 不并发。
- PR #30 已把 PR #29 合并状态写回权威记忆并合并为主线 `0ad270549f332edb99e58ea9f132b29bdea44c56`；合并后主线 Python 与 Node/镜像/Compose CI 全绿。本地已只读抓取该主线引用，工作树干净；尚未生成或上传新发布包。
- 已连接主人打开的腾讯云终端页面，但远程 Shell 处于断开状态并要求 MFA 微信扫码。主人随后要求关机，因此没有完成 MFA，没有执行服务器命令，没有创建私有 sidecar 配置，没有构建/启动容器，也没有改变 QQ 开放平台、Python 官方开关或 NapCat。
- NapCat 48 小时观察窗口已截止；期间的多次短时掉线使其未达到稳定性标准，过期 `higgs-48` 观察自动化已删除。后续不再把个人 QQ 通道视为官方通道上线的前置条件。
- 恢复顺序固定：①重新打开腾讯云终端并完成 MFA；②匿名只读核对生产仍为上一禁用态发布、Python 官方关闭且 NapCat 不变；③从主线 `0ad2705` 生成只含 Git 跟踪文件的发布包并双端校验；④锁定 Node 基础镜像 digest，在服务器私有目录创建独立 `0600 official-qq.env`，不回显凭据；⑤只启动 capture-only sidecar，确认 READY 后由主人从官方入口发送一次；⑥运行 120 秒匿名计数并立即停止 sidecar。若 event_seen=true，再以新 PR 实现 Python UDS 正式接入；若仍为零，则回到平台事件授权/测试范围排查，不继续更换语言盲试。

## 18. 2026-08-28 Node 真实捕获成功与 UDS 正式接入启动

- 从当前主线 `358d9681f5539b6fbb204af28929500b06ea1a40` 生成只含 Git 跟踪文件的发布包，本地 SHA-256 校验后上传；服务器端再次核对相同摘要。发布包不含私有配置、登录状态、身份或聊天数据。
- 匿名生产门控确认旧 Python 官方 Gateway 关闭、Node sidecar 不存在、NapCat 容器健康；只在独立不可变目录解包并构建官方 Node sidecar，没有切换 Agent 当前发布，也没有重建或重启 NapCat。
- 私有 sidecar 配置从服务器已有秘密原子派生为独立 `0600 official-qq.env`，未回显 App 凭据；Node 基础镜像按实际 digest 锁定。sidecar 以 `capture-only=true` 启动后达到 configured、Gateway connected、authenticated 与健康状态。
- 主人从官方机器人入口发送后，120 秒匿名捕获成功看到事件，计数为 2；捕获只返回布尔状态、固定原因和数量，不读取、输出或保存身份、消息 ID、正文或附件，也未发送回复。窗口结束后 sidecar 自动停止；事后门控确认 Node 与 Python 官方 Gateway 均关闭、NapCat 仍运行且健康。
- 结论由“平台到 Python SDK 零事件”推进为“官方 Node Gateway 真实投递可用”。已新建 `codex/higgs-official-uds-runtime-20260828`，下一步实现 Python 通过共享 `0600` Unix Socket 读取严格事件并仅作入站被动回复；正式运行仍默认关闭，需完整测试、独立 PR/CI 和再次生产门控后才能灰度启用。

## 19. 2026-08-29 UDS 正式运行时代码收束

- 独立分支 `codex/higgs-official-uds-runtime-20260828` 已完成 Node 独占 Gateway、私有 Resume、`0600` UDS 和 Python 业务适配层。Agent 的 sidecar 模式无论启用与否均拒绝 App 凭据；官方回复另有默认关闭的独立开关。
- Node 发送只有在当前固定 SDK WebSocket 可观测、连接打开且最近心跳 ACK 不超过 90 秒时才允许；发送调用有独立 10 秒上限，缺平台 ID、异常或超时只能返回 `UNKNOWN`。重复事件不能重置或续期一次性回复授权，协议损坏会终止通道而不是伪装成不确定送达。
- Node 与 Python 双层执行主人和群白名单。sidecar 对非主人私聊和未获准群 `@` 在入队及授权前即丢弃；Python 继续负责相同策略、规范会话、记忆与业务。
- 新增替代基础 unit 的 `higgs-existing-official.service`，固定同时加载基础 Compose 和官方 overlay、启用 `official-qq` profile，并在每次启动前强制验证两个专用目录为 UID/GID `10001:10001`、模式 `0700`。生产迁移必须只禁用但不停止旧的 `RemainAfterExit` unit，再启用官方 unit；两者不得声明 `Conflicts=`，否则旧 unit 的整栈 `ExecStop` 会中断 NapCat。
- Node 基础镜像在示例和 CI 中固定为 Docker Official Image 的完整 digest；SDK 启动时再次断言精确 `1.0.4`。本地 Node 当前 `25 passed, 2 skipped`（两个真实 Linux UDS/session 测试交由 Ubuntu CI），Python 完整测试 `304 passed, 5 skipped`，Ruff 与格式通过。
- 正式回复仍不得开启：当前事件队列和发送回执为内存态，固定 SDK 又会在事件回调前保存 Gateway sequence，进程崩溃可能造成尚未进入 Agent journal 的事件丢失。当前可进入的下一门仅是“官方在线、业务摄取但回复关闭”的 shadow 部署；需 PR/CI 全绿及单独生产确认，随后验证 Linux UDS、Compose、systemd 重启与 Resume，再设计协调崩溃恢复。
- 功能提交 `d7e71dd` 已推送独立分支并创建 PR #32；push 与 pull request 两套 Python、Node/镜像/Compose CI 均通过，包含 Windows 本地跳过的 Linux UDS/session 测试。等待文档检查点的最终 CI 后按阶段 PR 流程合并；尚未部署或修改生产开关。
- 文档检查点 `ca72bbb` 的两套 CI 同样通过；PR #32 已合并为主线 `fd60229b80878cacf0e516967cd02b9a1e1594fb`，合并后主线 CI 成功。生产仍未部署，下一动作必须取得独立确认后才可启用“摄取开启、回复关闭”的 shadow，并先做匿名配置、目录、镜像和单 Gateway 门控。

## 20. 2026-08-29 shadow 部署门控与一次性 Node 主人绑定器

- systemd 迁移复核发现官方 unit 的 `Conflicts=higgs-existing.service` 会触发旧 `RemainAfterExit` unit 的整栈停止路径，存在误停 NapCat 的风险。修复经 PR #34 合并为主线 `0a930e2fbf2bd2256430ce92ecdf04f196b06cdd`，去除 `Conflicts` 并把迁移固定为“只 disable、不 stop”；分支、PR 与合并后主线 CI 均通过。
- 生产已成功构建该主线提交的不可变 release、Agent 镜像与官方 sidecar 镜像。两次 shadow 切换尝试均在门控失败时安全退出或回滚：current release 未切换、官方摄取与回复均保持关闭、官方 sidecar 停止、NapCat 保持运行与健康，且未出现新的容器启动事件。
- 匿名兼容性诊断确认私有配置权限、模式、App 凭据格式、Compose 和运行时预检均通过；唯一阻断是两份运行时配置都尚无主人官方 OpenID。早先 Node capture-only 诊断按设计只统计事件并丢弃身份，不能为正式 owner 门控提供绑定值。不得把 AppID 或 QQ 号冒充 OpenID，也不得绕过 owner 门控。
- 新分支 `codex/higgs-official-node-owner-bind-20260829` 实现一次性 Node 绑定器：只有在平台测试用户恰为主人一人的人工确认短语下运行；只接受 READY 后首个合法 C2C sender，直接写入私有 `0600` create-once 文件，不输出身份、消息 ID、正文、附件或凭据，成功后立即停止 Gateway。
- 服务器包装脚本要求 Python 官方通道关闭、没有其他官方 Gateway、专用目录为 `0700` 且 UID/GID 正确；私有环境先备份，双文件更新失败会事务式恢复，临时身份文件只移入 `/srv/trash`。绑定完成后再次证明官方摄取仍关闭，正式回复始终保持关闭。
- 当前本地 Node 为 `29 passed, 2 skipped`，Python 为 `305 passed, 5 skipped`；Ruff、格式、发布包、秘密边界、Shell LF 与 `git diff --check` 均通过。功能提交 `24296a1` 已创建 PR #35，push 与 pull request 两套 Python、Node/镜像/Compose CI 全绿，Ubuntu 同时验证新增绑定脚本的 Bash 语法与 Linux 零跳过测试。待文档检查点 CI 后合并；随后只部署绑定器，主人从官方入口发送一次完成私有绑定，再重试回复关闭的 shadow 上线。

## 21. 2026-08-29 关机暂停：主人绑定与官方 shadow 已上线

- PR #35 的文档检查点 CI 通过后已合并为主线 `635045d30cf6f02970ddbbb464afd165f220459e`，合并后主线 Python 与 Node/镜像/Compose CI 均通过。
- 前一晚的一次绑定窗口在超时后安全退出，未写入身份、未开启官方通道。恢复腾讯云会话并由主人完成扫码后，再运行一次受控绑定；首个合法官方 C2C 事件完成私有绑定，两份环境文件事务式更新成功，中间身份文件按约定移入 `/srv/trash`，全程没有回显任何身份、正文、消息 ID 或凭据。
- 已生成并双端校验只含跟踪文件的主线发布包，构建相同 40 位提交标签的 Agent 与 official sidecar 镜像；`current` 原子切换到不可变发布，旧链接和替换前 unit 均进入 `/srv/trash`。
- shadow 部署回执为：NapCat 容器未改变且 healthy、Agent running、official sidecar healthy、官方摄取 enabled、官方回复 disabled、旧基础 unit disabled、官方 unit enabled。平台 Gateway 因而可显示在线，但机器人当前按设计不会回复。
- 关机前原计划补做镜像、唯一 Gateway、重启次数和 `transport.sqlite` 的匿名深层核验。命令只被输入，尚未执行；收到关机通知后已用中断键清空命令行，没有产生服务器状态变更或新测试消息。
- 恢复点：重新登录腾讯云终端后先执行上述匿名只读核验；通过后再单独设计并申请 systemd 重启/Resume 验收。内存事件队列与 Gateway sequence 的崩溃窗口尚未封闭，正式回复必须继续保持 false。

## 22. 2026-08-29 shadow 现场竞态与本地修复

- 恢复 MFA 后执行匿名只读核验：不可变 release 和两镜像精确匹配；唯一 official sidecar 在线、authenticated、心跳 ACK 新鲜且 Docker health 通过；Agent 与 NapCat 均 running，NapCat healthy、两者重启计数为零，reply=false。sidecar 曾自动重启一次；官方 unit enabled 但 inactive，旧基础 unit disabled 但仍 active。
- `transport.sqlite` 显示官方通道启动后先 `pending/startup`，约 0.7 秒进入 `verified/ready`；约 29 分钟后经历约 2.5 秒 `pending/gateway_reconnecting`，随即进入持续的 `rejected/protocol_error`。sidecar 后续恢复并连续健康约 8 小时，但 Agent 的 terminal fail-closed 状态不会自愈，业务摄取因此实际中断。
- 根因是重连 READY 先于新 WebSocket 的首个 heartbeat ACK：旧 Node 状态在 READY 回调立即公开 authenticated，而 Python 看到 authenticated 但 ACK 为空，按协议矛盾永久熔断。该结论由匿名时序与源码状态机共同支持，没有读取聊天正文、身份、消息 ID 或 sidecar 日志。
- 新分支把 authenticated 语义收紧为“READY/RESUMED 身份有效且首个 ACK 已成功触达并刷新私有 session”；此前保持 `heartbeat_pending`，事件和发送均拒绝。若首个 ACK 在 90 秒内不到达，watchdog 继续以 `heartbeat_ack_timeout` fail-closed。Python 接受该明确 pending 状态而不误判协议破坏。
- 本地 Node 为 `30 passed, 2 skipped`，新增 READY/RESUMED 前后门控和首 ACK 超时回归；Python 定向 `11 passed`、完整 `306 passed, 5 skipped`，Ruff、格式和 Node 语法检查通过。尚未提交功能、创建 PR、运行 Ubuntu Linux UDS/session CI 或部署；生产 reply 继续为 false。

## 23. 2026-08-29 首 ACK 修复上线与 sidecar 持久化本地收束

- 首 ACK 修复由 PR #36 合并为主线 `f18ff1b8b4a86845316f960fdb7b8a350e5a2eec`，随后完成不可变 Agent/sidecar 生产发布。只重建这两个服务，NapCat 身份、启动时间和 health 未改变；独立后验确认官方通道 connected、authenticated、ACK 新鲜并以 `resumed` 恢复，`transport.sqlite` 进入 `verified/resumed`。回复仍为 false。
- 交接文档经 PR #37 合并为主线 `a3178122ec17e05c8215278ab3167d2936778ab1`，合并后 Python 与 Node/镜像/Compose CI 全绿。个人 QQ 当前离线导致 Agent 综合 health 为 unhealthy，但不影响已独立验证的官方 transport；不得为此自动重登或重启 NapCat。
- 新分支 `codex/higgs-official-durable-delivery-20260829` 已完成第一层协调持久化：full-mode sidecar 在 SDK 回调返回前，把严格规范化的入站事件及其被动回复授权原子写入专用私有 `0600 delivery-state.json`；文件、父目录、owner、大小、结构或 symlink 校验失败以及队列满均终止官方通道，不会静默丢弃。
- UDS hello 现在给出匿名 ACK 游标；Agent 只有在事件处理器正常返回后才逐条提交带 generation 的显式 ACK。Agent 单独重启会从 sidecar 当前 ACK 游标继续，sidecar 重启会把仍未确认事件安全重编号后重放；ACK 前处理失败不移动游标。
- 回复授权同时持久化请求指纹，发送回执也原子保存。若进程在领取发送权后、写入最终回执前崩溃，重启后同一请求只返回 `UNKNOWN`，不再调用平台；同一幂等键但不同目标、正文或 reply ID 继续拒绝。
- 本地 Node 为 `31 passed, 5 skipped`，Python 定向 `12 passed`、完整 `307 passed, 5 skipped`，Ruff、格式、Node 语法、发布门与 diff 检查通过。功能提交已进入 PR #38；push 与 pull request 两组 Python、Node/镜像/Compose CI 全绿，Ubuntu 零跳过覆盖了私有文件权限、原子重载和 symlink 场景。尚未合并或部署，生产回复仍为 false。
- 这一切片只封闭 sidecar 进程崩溃窗口；Agent 的 quiet-window、模型生成与业务副作用尚未形成持久处理状态机。因此即使本 PR/CI 与 shadow 部署通过，也不得立即开启回复；下一切片需先持久化 Agent 的处理生命周期并做重启注入测试。

## 24. 2026-08-29 sidecar 协调持久化合并与生产 shadow 发布

- PR #38 已在 push 与 pull request 两套 Python、Node/镜像/Compose CI 全绿后合并，主线提交为 `e02bbc85d04683af7e8854521117c9152ef47d96`；合并后主线 CI run `33254680991` 的两项任务再次通过，Linux 零跳过覆盖私有权限、symlink、原子重载与 Compose。
- 只含 Git 跟踪文件的发布包为 455927 字节，SHA-256 为 `99202cf6add2d6e9939315c14e14bf6d28b99dac18bbdffb9f1a23081262e62c`；本地与服务器端大小、摘要均一致，包内不含凭据、身份、聊天正文或登录状态。
- 首次生产脚本在镜像构建前因遗漏 official profile 安全失败，未替换容器；第二次已完成镜像构建和短暂侧车重建，但后续 `compose ps` 未携带 profile，自动回滚恢复旧 release、私有镜像标签与运行容器。两次均未重启或重新登录 NapCat，也未发送测试消息。
- 最终脚本把 profile 固定到所有 Compose 子命令，复用已验证的新镜像后成功原子切换 release 与私有镜像标签，只依次重建 official sidecar 和 Agent。匿名验收确认新 sidecar healthy、重启计数为零、单 Gateway、Agent running、官方 reply=false，NapCat 容器身份、启动时间和 health 完全不变。
- 独立后验从 `transport.sqlite` 确认 `qq_official` 为 `verified`，connected/authenticated、身份匹配和最近健康回执均为真，心跳新鲜且原因是 `resumed`。专用持久化目录继续为 agent 私有 `0700`；空状态尚未产生 `delivery-state.json` 属预期，首个需保存的事件、授权或回执会以 `0600` 原子物化。
- 本次 shadow 观察从 2026-08-29 21:53（Asia/Shanghai）重新计时。正式回复仍不得开启：sidecar 崩溃窗口已封闭，但 Agent quiet-window、模型生成和业务副作用还没有持久处理生命周期；下一阶段先实现 Agent 状态机、故障注入与重启恢复，再申请真实被动回复验收。

## 25. 2026-08-29 Agent 官方消息持久处理进入 PR 验收

- 独立分支 `codex/higgs-agent-durable-processing-20260829` 新增 `official_processing.sqlite`。官方入站在 sidecar ACK 前先事务式进入 Agent 队列；同发送者的私聊/群聊连续片段以持久 quiet-window 合并，源事件以通道、账号和消息 ID 去重。OneBot 仍使用原内存 debouncer，不受本切片改变。
- 状态机固定为 `pending → preparing → prepared → sending → finalizing → complete`。准确回复文本、风险预留和最终结果在跨越 provider 边界前后分别持久化；重启时 `preparing` 回到待准备，`sending` 回到已准备并复用同一文本和幂等键，`finalizing` 只重做幂等审计与会话落库。
- `RiskLedger` 与非主人会话熔断预留均新增内容无关的幂等哈希，Agent 在模型准备阶段崩溃后复用同一 reservation 和来源计数，不重复占用预算或误触发冷却。已完成记录仍按原 sent/failed/unknown 语义结算。
- 官方真实回复被配置层和运行时共同限制为启用的 durable sidecar；直连 Python SDK 不得开启回复。ACK 响应丢失后，Python 会从 sidecar 权威游标重新同步，避免把已提交 ACK 误判为 cursor 协议终止。
- 官方 MVP 在任何副作用发生前跳过日计划与提醒，只允许主人执行精确 `/higgs status`（含中文状态别名）；其他 `/higgs` 命令被固定拒绝，普通对话仍可进入模型。官方输出在持久化前限制为 sidecar 的 2000 字符上限。
- 新数据库已纳入一致性备份，运行时数据库总数为 13；完成项按既有 journal retention 清理。备份原子目录发布对短暂 Windows 句柄竞争增加有界重试，不改变 Linux 原子 rename 语义。
- 首轮故障审计发现两个上线阻断并已修复：授权过期、配置错误或幂等冲突等不可恢复的 sidecar 拒绝现在产生终态 `FAILED` 并结算风险预留，不再无限重试；已清理完成批次的源消息改存内容无关的 SHA-256 tombstone，长期停机后上游重投仍不能产生第二次回复。
- 故障测试进一步覆盖真实 `RiskLedger` 的 prepare 崩溃预留复用、`UNKNOWN → P.complete/R.unknown/A+C.send_failed` 且不重发、ACK 仅在 SQLite durable enqueue 后提交、监督循环对 ACK 响应丢失的权威游标恢复，以及 Linux `SecureDeliveryStore` 的真实 claim/receipt 跨进程替换与 provider 调用计数。adapter 自身也强制执行 reply 开关和 sidecar 凭据隔离。
- 本地门禁：Python `330 passed, 5 skipped`（Windows 仅跳过 Linux 权限/UDS 项）、Ruff 与格式通过；Node `31 passed, 7 skipped`（新增两项真实 POSIX 持久化测试交由 Ubuntu CI）、语法检查通过；发布门确认 244 个跟踪文件、267 个归档成员、秘密模式与 Shell LF 均通过。
- 功能提交 `33b34eb` 的等价远端提交已进入 PR #40；首轮 push/PR 两套 Python 与 Node/镜像/Compose CI 全绿。当前正在把上述审计修正追加到同一 PR 并等待 Ubuntu 零跳过复验。生产仍为上一主线 release、reply=false；没有发送测试消息、修改私有配置、重建容器或触碰 NapCat。用户已单独批准后续上传与 reply=false 部署；真实回复仍须在合并、生产恢复验收后再次确认。

## 26. 2026-08-30 PR #40 合并发布与双通道健康门槛修复中

- PR #40 已合并为主线 `9e55b8293a45feac3d89c8b5f32f1d94c9077185`；合并后 CI run `33259705508` 的 Python 与 Node/镜像/Compose 任务全部通过，Ubuntu 对本地 POSIX 跳过项为零跳过。只含 Git 跟踪文件的发布包为 470185 字节、267 个成员，SHA-256 为 `ffaef83ac222b6a963634cb10b554e11eefd1bebfa120c62c46b9661dd78c3df`，本地与服务器校验一致。
- 第一次部署在生产变更前因归档内脚本无 executable 位安全退出。改为显式经 Bash 调用后，新 release、Agent 与 official sidecar 镜像均已生效；只重建 sidecar 和 Agent。匿名后验确认 sidecar running/healthy、零重启、单 Gateway，`official_processing.sqlite` 已物化，官方回复仍为 false；NapCat 容器 running/healthy、零重启且未参与重建。
- 生产 Agent 当前 `running/unhealthy` 的唯一匿名健康原因是个人 QQ `get_status_offline`：OneBot 仍可达、账号匹配未知、没有账号不匹配证据。官方 sidecar 独立健康，因此不能把这一 Docker health 结果解释为官方 Gateway 离线。不得为修复综合 health 自动重启或重新登录 NapCat。
- 根因是基础 Compose 的 Agent healthcheck 仍带 `--require-qq-online`，官方 overlay 未覆盖；这会让已健康的官方双通道被个人 QQ 离线拖成整体 unhealthy，并阻断 official unit 的 `--wait`。独立分支 `codex/higgs-dual-channel-health-20260830` 已在 overlay 中仅移除个人 QQ 权威在线要求，仍保留 Agent 新鲜心跳、OneBot 可达和 NapCat 容器 marker 门槛；新增回归禁止 overlay 重新带入 `--require-qq-online`。
- 当前本地定向部署测试 `6 passed`，Ruff/格式通过；完整 Python 在正确安装 `dev` extra 后为 `330 passed, 5 skipped`，Node 为 `31 passed, 7 skipped`。下一步提交该小修、PR/Ubuntu CI、合并后只部署新的 Compose overlay 并重建 Agent，再匿名确认 Agent healthy、官方 sidecar 单实例健康、reply=false、NapCat 容器未变化。真实回复仍需该生产验收后单独确认。

## 27. 2026-08-30 双通道健康修复完成生产验收

- 健康覆盖修复提交 `5e0d82d` 经 PR #41 合并为主线 `a0f32c49db88318c696f22b4b9d345312557f465`。PR 的 push 与 pull request 两组 Python、Node/镜像/Compose CI 全绿；合并提交 tree 与本地完整门禁所验收 tree 完全一致。完整门禁为 Python `330 passed, 5 skipped`、Node `31 passed, 7 skipped`，Ruff、格式、秘密扫描、Shell LF 和 267 成员发布门全部通过。
- 本地生成了完整主线发布包并通过发布门。OrcaTerm 标准文件选择器不可用且完整 Base64 分块通道超过平台单次等待上限，因此生产未使用未完成归档；改为从当前已验收 `9e55b829` 不可变 release 克隆新不可变运行目录，只以双端 SHA-256 一致的 PR #41 `compose.official-qq.yml` 替换唯一运行时差异。测试和文档仍以 GitHub 合并提交为权威，不把该最小运行目录宣称为完整 Git 归档镜像。
- 切换脚本显式验证 overlay 摘要、Compose 配置、新旧 release 链接和回复开关；仅 `--force-recreate agent`，不重建镜像，不操作 official sidecar 或 NapCat。若 Agent 未在 90 秒内健康或任一旁路容器身份改变，脚本会恢复旧 `current` 并重建旧 Agent。本次回执为成功。
- 匿名生产验收为：新运行目录生效；Agent `healthy`；official sidecar `healthy`；同 AppID 只有一个 official Gateway；`transport.sqlite` 的 `qq_official` 为 `verified`，连接、认证、身份匹配和新鲜健康回执均通过；`R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=false`。NapCat 容器运行且健康，部署前后容器身份、启动时间和重启计数未改变；没有自动重登、重启 NapCat 或发送测试消息。
- 这解除的是个人 QQ 离线拖累官方双通道整体健康的问题，不代表个人 QQ 已恢复，也不是正式回复验收。下一动作必须由主人单独确认把官方被动回复从 false 切为 true；获准后只原子更新服务器私有配置并重建 Agent，随后由主人从官方入口发送一条测试消息，验证真实回复、持久状态机、审计和 UNKNOWN/幂等边界。NapCat 提醒与个人 QQ 通道继续保持独立。

## 28. 2026-08-30 官方被动回复已获准并开启，等待首条真实验收

- 主人明确授权“允许开启官方被动回复并只重建 Agent”。切换前匿名门控确认 Agent、official sidecar 与 NapCat 容器均健康，官方 Gateway 单实例，`qq_official` 为 `verified` 且健康回执新鲜；`official_processing.sqlite` 不存在任何非 `complete` 批次，因此不会把 shadow 期间的旧消息作为待回复恢复。
- 服务器私有 `higgs.env` 在 `/srv/trash` 创建权限收紧的可恢复备份后，以临时文件、文件 fsync、原子 replace 和目录 fsync 将唯一回复开关从 false 改为 true；没有回显或记录凭据、身份或聊天数据。切换脚本的本地与服务器 SHA-256 一致，任一后验门控失败都会恢复私有配置并重建旧 Agent。
- 生产只执行 `--no-deps --no-build --force-recreate agent`。匿名回执确认新 Agent healthy 且实际环境为 `R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=true`；官方 transport 继续 verified、Gateway 仍为一个。official sidecar 与 NapCat 的容器身份、启动时间和重启计数前后完全一致，没有重启 sidecar、重启或重登 NapCat，也没有由运维侧发送测试消息。
- 官方 Bot 现在进入真实被动回复开启态，但端到端真实回复尚待主人从官方入口发送一条“测试”验收。下一步只观察匿名处理状态、发送结果类别、幂等与重复调用计数，不读取或记录身份、正文、消息 ID 或平台回执 ID；若出现 UNKNOWN 或失败，不得盲目补发，先按 durable processing 状态机诊断。

## 29. 2026-08-30 超长官方消息标识根因确认与修复待 PR

- 主人连续两次从官方入口发送测试消息。两条消息均被唯一 Gateway 接收并由 durable processor 收敛为 `complete/model_failed`；平台发送接口没有被调用，活动批次为零，因此不存在 UNKNOWN、重复发送或旧批次重放风险。Agent、official sidecar、NapCat 均保持 healthy，官方 transport 持续 verified，reply=true。
- 匿名固定模型探针确认生产模型配置、鉴权、网络和基础生成正常。进一步的内容无关结构检查显示，测试正文仅 2 个字符，但官方平台消息标识较长，使旧 `channel:account_id:message_id` 召回审计键达到 150 字符，超过 `RecallLedger` 的 128 字符上限；召回审计未落库，请求也从未到达模型服务。这是两次 `model_failed` 的确定根因。
- 独立分支 `codex/higgs-official-recall-id-fix-20260830` 将召回 `turn_id` 改为带版本前缀的 SHA-256 固定长度键。它仍绑定 channel、account 和 message，保持去重与冲突检测语义，同时不再泄露平台标识，也不会受不同平台 ID 长度影响。新增 160 字符平台消息 ID 回归，证明键长固定为 77、原标识不出现在审计键且 owner recall 可读取。
- 本地 release gate、秘密边界、Shell LF/语法、Ruff、格式均通过；Python 完整 `331 passed, 5 skipped`，Node `31 passed, 7 skipped`（Windows 既有 Linux 专用跳过）。下一步是提交独立 PR、等待 Ubuntu CI 零跳过，合并后生成不可变发布并只重建 Agent；旧失败批次保持终态，不得重放。生产修复部署后再请主人发送一条新测试完成真实 SENT 验收。

## 30. 2026-08-30 官方 QQ Bot 首次真实端到端回复通过

- 超长官方消息标识修复经 PR #44 的 push 与 pull request 两组 Python、Node/镜像/Compose CI 全绿后合并，主线提交为 `6a95312bc3bf935295f9d9ff199c577baa7ae31d`；没有直接推送 `main`。
- 仅含 Git 跟踪文件的完整发布包为 475980 字节、267 个成员，SHA-256 为 `58723a985a1f3775669126395e0efe39b0cd093069b24fd4d6f8a6f8a2ac0551`。本地与服务器发布链路使用不可变 release；发布只构建并重建 Agent，official sidecar 和 NapCat 的容器身份、启动时间与重启计数均未改变。
- 部署后匿名门控确认 Agent、official sidecar 与 NapCat 容器均 healthy，官方 Gateway 单实例，官方 transport 保持 `verified`，reply=true，活动 durable 批次为零。先前两个 `complete/model_failed` 批次保持终态，未重放。
- 主人随后从官方入口发送一条新消息。脱敏验收显示 durable batch 进入 `complete`，处理生命周期出现预期的三个转换节点，最终发送结果与回复审计均为 `sent`，活动批次回归零；官方 transport 仍 verified，三个容器仍 healthy，Gateway 仍为一个。
- 这是 Higgs 官方 QQ Bot 的首次真实“平台入站 → 持久处理 → 模型回复 → 平台发送 → 审计收敛”端到端验收。当前已正式开放 owner 官方 C2C 被动回复 MVP；提醒仍由 NapCat 发送，不做跨通道自动转发或透明故障切换。下一阶段是 72 小时官方通道观察，然后再以单个测试群、仅 `@` 触发的方式灰度。

## 31. 2026-08-30 官方通道 72 小时匿名观察已启动

- 观察窗口固定为 2026-08-30 08:09:26 至 2026-09-02 08:09:26（Asia/Shanghai）。已创建当前任务内的 `higgs-72` 心跳观察，每 6 小时执行一次，截止后生成结论并暂停；不会把截止后的 72 小时窗口自动延长。
- 新增 `deploy/existing-server/observe_official_stability.sh`，只读检查三个容器健康与重启计数、单 Gateway、reply=true、官方 transport 验证/认证/身份匹配/健康新鲜度、窗口内转换计数和活动批次。SQLite 使用 `mode=ro` 与 `query_only`，不读日志，不输出容器 ID、身份、正文、平台消息/回执 ID 或凭据，不发送消息、重启容器、修改配置或重新登录。
- 首个基线点为 Agent、official sidecar、NapCat 均 healthy 且重启计数为零，Gateway 为一，reply=true，transport verified/连接/认证/身份匹配/健康回执全部通过，活动 durable 批次为零。观察启动后已出现一次短暂 `pending/gateway_reconnecting → verified/ready` 自愈，没有 rejected、致命转换或容器重启；该事件将保留在最终稳定性证据中。
- 72 小时结论前不开放测试群生产白名单。观察期间可以离线完成群 OpenID 受控绑定、双层白名单和仅 `GROUP_AT_MESSAGE_CREATE` 回复的测试/PR，但生产启用仍必须等待本窗口通过并另行验收。
- 本切片本地门禁已通过：远端真实 Bash 语法与只读基线执行成功；release gate 为 245 个跟踪文件、267 个归档成员、秘密边界与 Shell LF 全通过；Ruff 格式/检查通过；Python `332 passed, 5 skipped`，Node `31 passed, 7 skipped`（Windows 既有 Linux 专用跳过）。下一步提交观察脚本与起点记录的独立 PR，等待 Ubuntu 零跳过后合并；该 PR 不包含生产开关、容器或白名单变更。

## 32. 2026-08-30 官方测试群受控绑定与激活完成本地收束

- 新分支 `codex/higgs-official-test-group-bind-20260830` 实现一次性测试群绑定器。它只有在显式给出“主人只绑定一个测试群”和“72 小时观察已通过”两个确认后才运行；需要现有 owner 私有绑定、reply=true、健康单 Gateway、活动 durable 批次为零且首个群槽为空。
- 绑定窗口只接受 READY/首 ACK 后、由既有 owner OpenID 在 `GROUP_AT_MESSAGE_CREATE` 中发送且正文包含固定短语“绑定测试群”的事件。C2C、非主人、普通群消息、错误短语、READY 前或畸形事件均不能绑定。候选群 OpenID 直接写入 `0600` create-once 私有文件，不输出身份、正文、消息 ID、附件或凭据。
- 绑定脚本只暂时停止 official sidecar，运行唯一 capture-only Gateway，随后恢复原 sidecar 并等待官方 transport 重新 verified；Agent 与 NapCat 不重建，NapCat 身份、启动时间和重启计数必须不变。绑定成功后生产双层群白名单仍为空，候选只留在私有文件；失败产物移入 `/srv/trash`。
- 激活是第二个独立显式动作，同样硬性要求 72 小时观察已通过。它先把两份 `0600` 私有环境备份到 `/srv/trash`，再把同一候选原子写入 Agent 与 sidecar 的官方群白名单，仅重建 official sidecar 和 Agent，并验证单 Gateway、双运行时值一致、reply=true、transport verified、零活动批次及 NapCat 不变；任一失败恢复两份配置和旧服务。
- 生产业务面继续只接受 `GROUP_AT_MESSAGE_CREATE`，因此普通群消息不会进入 Journal、身份、记忆、模型或回复流水线。官方群成员按 `channel + member OpenID` 建立独立 principal；不会因字符串相同自动与 NapCat QQ 身份、owner 或其他成员合并。
- 本地回归为 Python `335 passed, 5 skipped`、Node `36 passed, 7 skipped`；Ruff、格式、Node 语法和两份新 Shell 的真实远端 Bash 语法检查通过。release gate 以 249 个跟踪文件、272 个归档成员通过，秘密边界与 Shell LF 均干净。PR #47 已建立且首轮四项 CI 全绿；后续增强尚待推送复验。尚未部署；72 小时观察仍在进行，当前生产群白名单没有变化。

## 33. 2026-08-30 关机暂停：主人命令与官方主动提醒离线实现中

- PR #47 已合并为主线 `b72ad8a4fab1f1ad8d261287105e6797a910b9bf`，合并后主线 CI run `33284134356` 成功。测试群代码就绪不等于生产获准；固定 72 小时窗口结束前仍不得绑定或激活群白名单。
- 新建独立工作树 `Higgs-wt-official-owner-reminders` 与分支 `codex/higgs-official-owner-reminders-20260830`，基于上述主线。腾讯官方 `tencent-connect/openclaw-qqbot` 与 `qqbot-nodejs` 的当前实现证明主动 C2C 使用同一 Bot 对明确 OpenID 发送且不携带入站 `msgId`；OpenID 必须与产生它的 Bot 账户绑定。该结论只用于离线设计，尚未发送任何主动消息。
- ReminderStore WIP 新增显式 `delivery_channel + delivery_surface + delivery_account_id + delivery_target_id`，并把四项纳入主人确认哈希。官方群提醒只允许由 owner C2C 原会话建立、投递回同一 Bot 的 owner OpenID；不允许从群创建官方群主动提醒，也不把 OpenID 解释为个人 QQ。调度器可按当前健康通道筛选到期任务，NapCat 离线不会再阻断已明确绑定的官方群提醒。
- Agent 与 sidecar WIP 增加两端独立、默认关闭的 proactive 开关。主动发送只允许 owner C2C；sidecar 在平台调用前把幂等键与请求指纹持久认领为 `UNKNOWN`，若进程在调用边界崩溃，重启后不会重复调用平台。被动回复授权、群 `@` 回复和现有 reply 开关语义保持独立。
- 官方主人私聊命令 WIP 从仅 `/higgs status` 扩展到显式 allowlist：help、status、server status、risk、提醒管理与只读记忆查询。群内主人命令、运行开关、白名单、速率、备份、记忆变更、日计划等尚未迁移，继续在任何副作用前拒绝。
- 暂停前最小验证通过：Python 相关 `67 passed`，Ruff 格式与检查通过；Node 语法通过，`37 passed, 8 skipped`，Windows 跳过项含新增 POSIX 持久 proactive claim。代码尚未跑完整 pytest、release gate、秘密扫描或 Ubuntu 零跳过；尚未提交 PR、部署、修改私有配置、重建容器或发送测试消息。
- 恢复顺序：①先确认 `higgs-72` 观察未出现 rejected/fatal/容器重建；②复核 WIP diff 与提醒旧数据迁移策略；③补齐调度/配置/Compose 静态回归及 Linux 进程替换测试；④跑完整 Python/Node/发布门；⑤更新本阶段追加记忆并提交独立 PR/CI。即使 CI 全绿，proactive 两端开关仍保持 false，生产启用必须等待 72 小时结论并取得单独确认。

## 34. 2026-08-30 主人命令与主动提醒完成本地发布门

- 提醒投递绑定升级为显式版本。生产升级前已确认的 OneBot 提醒作为 version 1 保留原审批哈希并只允许沿原 `qq` 通道履行；它们不能转换成官方 Bot/OpenID 投递。所有新提醒是 version 2，主人确认哈希同时覆盖 delivery channel、surface、Bot account 与 target。由官方通道创建的新提醒只能来自 owner C2C，并回投同一 Bot 的 owner OpenID。
- Agent 与 Node sidecar 使用两道独立、默认 false 的 proactive 开关。主动请求只允许 owner C2C 且不携带入站 `msgId`；Sidecar 在跨越 provider 边界前持久写入请求指纹与 `UNKNOWN` claim，进程替换后同一键只能返回已有 UNKNOWN/终态，不能再次调用平台。被动回复与群 `@` 仍走原授权路径，不存在 NapCat/官方群之间的透明切换。
- 官方 owner C2C 命令采用显式 allowlist：help、status、server status、risk、提醒管理和只读记忆查询。官方群 owner 命令、运行开关、白名单、速率、备份、记忆变更和日计划继续在副作用前拒绝；本切片不宣称已完成“全部主人能力”。
- 新增 `activate_official_owner_proactive.sh`，只有同时提供主动发送和 72 小时已验收两个固定确认才可执行。它检查被动服务、单 Gateway、三容器健康、提醒 schema、零活动批次，把两份私有配置备份到 `/srv/trash` 后原子开启双门，只重建 official sidecar 与 Agent；任一后验失败同时回滚配置与服务，并强制验证 NapCat 身份、启动时间和重启计数不变。
- Windows 本地完整门禁为 Python `342 passed, 5 skipped`，Ruff 检查通过；格式修正后的受影响测试 `35 passed`。Node 语法与测试为 `37 passed, 8 skipped`；跳过项均为既有/新增 POSIX 权限、UDS 和真实进程替换覆盖，必须由 Ubuntu CI 零跳过解除。新增 Shell 因本机无 Bash，真实 `bash -n` 同样必须由 CI 验收。
- 尚未部署、修改服务器私有配置、重建容器或发送消息。固定 72 小时观察尚未结束，proactive 双门必须继续为 false，测试群白名单也不得提前激活。下一步是暂存后运行基于 Git 索引的 release/secret/LF 门，提交并推送本阶段分支、创建 PR，等待两套 Ubuntu CI 全绿；即使 PR 合并，生产启用仍需窗口结论和主人新的明确确认。
- 功能与迁移修正已由 `db43583`、`457b0a5` 提交并进入 PR #48。首轮 push 与 pull request 两套 CI 共四项全绿：Ubuntu Shell 语法、Python 零跳过、Node POSIX 持久化、npm 签名、镜像和 Compose 均通过；PR 状态为 clean/mergeable。当前只追加本 CI 证据并复验同一 PR，合并后仍不得提前部署或开启 proactive。

## 35. 2026-08-30 官方主人日计划离线迁移完成

- PR #48 在复验四项 CI 全绿后以 merge commit `2f22dd54f32ee41f76d193d77076d01cd47ded9f` 合并，合并提交自己的主线 CI run `33292488279` 成功；没有直接推送 `main`。生产 proactive 双门、官方群白名单与现有容器均未改变。
- 新分支 `codex/higgs-official-daily-plan-20260830` 把今日计划迁入官方 owner C2C。`/higgs plan ...` 与自然语言多待办可进入既有确定性排程、版本化草案、只读查看、显式地图授权、完成/跳过/取消/重新规划流程；官方非主人和任何群聊在写入前拒绝。
- `shadow` 计划不需要主动发送；`live` 精确版本确认在 Agent proactive 未启用时失败关闭，计划仍停留在待确认且不会创建提醒。获准启用后，总览、T-10 与 T0 节点使用 version 2 ReminderStore 记录，审批和投递固定绑定当前 `qq_official + private + Bot account + owner OpenID`，不回退 NapCat。
- `ReminderStore.create_scheduled` 现接受显式 origin/delivery 绑定，旧 OneBot 调用保持兼容。官方创建路径新增 canonical 同一 Bot 校验：origin conversation 中的 Bot/owner 必须与 delivery account/target 完全一致，避免跨 Bot 复用 OpenID。
- 文档已说明双通道日计划、地图授权和 proactive 门禁。Windows 完整 Python 为 `345 passed, 5 skipped`，Ruff 格式/检查通过；Node `37 passed, 8 skipped` 且语法通过。本切片尚未提交 PR/CI、部署、修改配置、重建容器或发送消息；72 小时结论前不得启用 live 官方节点提醒。
- 功能提交 `5e1b8ed` 已进入 PR #49，首轮 push 与 pull request 两套 CI 四项全绿；Ubuntu 对 Python 权限项和 Node UDS/进程替换持久化均零跳过，镜像与 Compose 也通过。当前仅追加本 CI 证据并复验同一 PR；合并不等于生产部署许可。

## 36. 2026-08-30 日计划与提醒 prepare 重放边界修复完成

- PR #49 已复验全绿并合并为主线 `4827add4edc0a6847b66290d69420be243e9a083`；合并后主线 CI run `33293097006` 成功。该功能仍未部署，生产 proactive 双门和官方群白名单保持关闭。
- 上线前复核发现：官方 durable processor 在 `preparing` 阶段崩溃后会重新调用回复准备；日计划草案、计划确认和提醒创建此前会在准备阶段直接写各自数据库，因此存在“业务副作用已提交、prepared reply 尚未提交”时重放并重复写入的风险。生产当前版本不包含 PR #48/#49，所以现场未受此问题影响。
- 独立分支 `codex/higgs-official-owner-controls-20260830` 先暂停继续迁移变更性主人命令，改为修复这条阻断路径。计划草案使用由 purpose、channel、Bot account 和入站 message 计算的 SHA-256 请求键；数据库在 `BEGIN IMMEDIATE` 内先复用同请求，再原子执行每日限额和新建。相同键参数变化一律失败关闭。
- 相对时间解析和计划起点固定到入站事件发生时间，避免同一事件重放时因墙钟变化产生另一份参数。地图授权限额与确认状态转换也在事务内幂等；确认、任务完成、计划取消及替换重放不再重复追加审计事件。
- 自然提醒按原会话和 source message 幂等创建；日计划节点提醒使用内容无关的稳定 SHA-256 内部来源键。计划确认中断后重放会复用已创建节点并补齐缺失节点，不重复确认、不重复提醒；投递通道、Bot 和目标绑定冲突仍失败关闭。
- 新增请求键复用/冲突、同事件双次草案、自然提醒双次准备、确认重复、任务状态重复，以及“首个节点已创建后注入中断并恢复”的测试。当前 Windows 完整 Python 为 `349 passed, 5 skipped`；Ruff、格式、release gate、秘密边界、Shell LF、Node 语法与 Node `37 passed, 8 skipped` 均通过。
- 修复提交 `bb965cf` 已进入 PR #50。首轮 push 与 pull request 两套 Ubuntu CI 共四项全绿，Linux Python 零跳过、Node POSIX/真实进程替换、Shell 语法、npm 签名、镜像与 Compose 均通过。当前只追加 CI 证据并等待复验；尚未合并或部署，复验通过后才继续主人控制命令迁移。

## 37. 2026-08-30 官方主人低风险变更进入持久治理边界

- PR #50 已完成复验并合并为主线 `9f2c2f42277fb5de0dc6a59c537765e55a1efddd`；合并后主线 CI run `33294165462` 的 Python 与 official sidecar 两项任务均成功。该合并没有部署生产，固定 72 小时观察窗口和现有生产配置未改变。
- 独立分支 `codex/higgs-official-owner-mutations-20260830` 复用既有 `tool_audit.sqlite`，没有增加第 14 个数据库。官方 owner C2C 的每条变更命令先以通道、Bot account 和平台消息标识生成内容无关的 SHA-256 操作键，再由 Stage 3 工具治理在执行前持久领取；同键同参数重放复用终态，同键参数漂移拒绝，领取后崩溃保持 `UNKNOWN` 且不得自动重试。
- 迁移范围仅含明确、低风险的普通回复开关、触发词、频率、连续消息等待、记忆自动审核/观察重试/候选回填/状态审核、备份和提醒状态操作。官方 OpenID 与个人 QQ 数字身份不得混用，因此好友/群白名单和自然触发群变更继续拒绝；测试群仍须走既有双阶段私有绑定流程。
- 治理审计只保存 actor/参数哈希和不含命令参数、提醒正文、记忆内容、身份或平台标识的固定结果摘要。旧命令路由返回的“操作未执行”会转换为失败终态，不再伪记成功；提醒等可能包含业务正文的旧展示回复不会进入持久回执。
- 故障测试覆盖成功回放只执行一次、同键参数冲突、执行前领取后进程替换得到 `UNKNOWN`、真实配置与记忆变更重复回放只产生一次状态转换，以及失败不持久化为成功。当前本地 Python `368 passed, 5 skipped`，Node `37 passed, 8 skipped`；Ruff、格式、发布门、秘密边界、Shell LF 和 `git diff --check` 全部通过。
- 功能提交 `34a7039` 已进入 PR #51；push run `33294949353` 与 pull request run `33294958839` 的 Python、official sidecar 四项任务全绿，Ubuntu Python 零跳过，Node POSIX/UDS/进程替换、Shell 语法、npm 签名、镜像和 Compose 均通过。当前只追加 CI 证据并复验；尚未合并或部署生产。

## 38. 2026-08-30 官方热控制与双通道状态一致性修复

- PR #51 已复验全绿并通过 PR 合并为主线 `ec7929705627d363f59dd79f9b01005174a6bec0`；合并提交自己的主线 CI run `33295067908` 的 Python 与 official sidecar 两项任务均成功。主人低风险变更代码尚未部署，72 小时生产观察与现有开关没有改变。
- 新分支 `codex/higgs-official-parity-20260830` 审计运行时控制后确认一处差距：`/higgs debounce` 会热更新 OneBot 内存合并器并持久化配置，但官方 durable enqueue 仍读取进程启动时的静态 private/group 值。本切片让官方事件从同一个加锁的 live control 读取当前 quiet-window；启动时仍保留私聊/群聊各自初值，主人热更新后两条 transport 立即使用新值。
- `/higgs status` 现同时读取 `transport.sqlite` 的 OneBot 与 `qq_official` 行。个人 QQ 继续展示 NapCat、OneBot、权威在线和踢线原因；官方通道单独展示 Gateway 可达、官方账号在线、Bot 身份匹配、匿名健康回执和持续时间，不输出账号、OpenID 或平台标识。官方关闭时不会为了展示状态创建虚假行。
- README、主人命令说明、双通道路线和官方配置模块说明已从旧的“Gateway 尚未启用”更新为当前真实边界：owner C2C 被动回复已验收，测试群和 proactive 仍受固定 72 小时、双层白名单/双开关与单独生产确认约束，生产 Gateway 由固定 Node sidecar 独占，Python SDK 只保留隔离兼容路径。
- 当前本地完整 Python `369 passed, 5 skipped`，Ruff 格式/检查通过；Node 语法和 `37 passed, 8 skipped` 通过。暂存后的 release gate、秘密边界、Shell LF 与 diff 检查同样通过；没有部署、改配置、重建容器或发送消息。
- 功能提交 `bf93a7d` 已进入 PR #52；push run `33295771506` 与 pull request run `33295778538` 四项 CI 全绿，Ubuntu Python 零跳过，Node POSIX/UDS/进程替换、Shell 语法、npm 签名、镜像和 Compose 均通过。当前仅追加 CI 证据并复验，尚未合并或部署。

## 39. 2026-08-30 Persona V2 本地实现与运行链路接入

- 远端最新主线已实际抓取并核对为 `56b85adf1d844f545152cdce31dbcb8ef4f40f3d`；本分支 `codex/higgs-persona-v2-20260830` 从该合并提交建立，没有直接修改 `main`。
- 新增带逐文件 SHA-256 与聚合 hash 校验的版本化 Higgs Persona Bundle，固定 constitution、style、examples 顺序；`R_AGENT_PERSONA_DIR` 优先，旧单文件和内联人格仅作为兼容路径。显式 V2 目录损坏时失败关闭，不会静默回退。
- `R_AGENT_PERSONA_V2_ENABLED` 默认 false。启用后也只允许已绑定的官方 owner C2C 使用 V2；OneBot、官方群和普通用户继续走原人格路径。运行时系统上下文先放不可覆盖的安全/权限规则，再放 constitution、style/examples、审核记忆和近期对话。
- 模型输出新增确定性 PersonaGuard：只检测高信号身份矛盾、无必要 AI 自称和客服模板。准确技术回答不改写；违规回答最多调用模型修复一次，再失败则使用经过同一守卫验证的短降级文本，不会进入循环。
- 建立 50 条人格回归集和独立人工评测模板/汇总器。自动门验证身份矛盾为零、客服/通用腔不超过 5%、身份复述不过量；四维真人评分当前明确为未评分，等待后续 owner 20 轮真实灰度，不伪造 4/5 结论。
- 本地验收为 Python `389 passed, 5 skipped`，Node `37 passed, 8 skipped`，Ruff、格式和 release gate 通过；Node 跳过项是既有 POSIX/UDS/进程替换覆盖，须由 Ubuntu CI 零跳过收口。尚未部署、修改生产开关、重建容器或发送消息；72 小时观察与现有生产通道不受影响。

## 40. 2026-08-30 Higgs 自我记忆 v4 本地接线完成

- `memory.sqlite` 的 schema v4 新增 `self_stance`、`adopted_idea` 及自我观察、证据、元数据和观点演进表，数据库总数仍为 13。默认 `MemoryStore.initialize()` 只到 v3；只有显式 `R_AGENT_SELF_MEMORY_SCHEMA_V4_ENABLED=true` 才迁移，避免代码部署隐式修改生产数据库。
- 只有带平台消息标识和幂等键的最终 `SENT` 回执可形成 Higgs 自我观察。`off` 不观察；`shadow` 只生成 considering/隔离候选；`autonomous-low-risk` 才允许满足 0.94 门槛且无敏感、核验、核心影响或冲突的观点自动生效。激活后崩溃重放、请求键冲突和重复证据均失败关闭或幂等复用。
- 严格模型提取器分两次受限提议 Higgs 自己的稳定观点与外部可采纳思想，不允许身份、主人、权限或系统规则进入候选。外部思想来源在共享上下文中去标识；只有带 Higgs 原句证据的自我观点才允许说“我以前说过”。
- 上下文顺序现为安全权限、Persona Bundle、最多三条 Higgs 自我记忆、当前主体记忆、近期对话。已批准自我观点在中文同义问法没有向量命中时仍从小型 active 集合补足，摄影观点已覆盖超过八轮历史和服务重启后的召回测试。
- 主人命令新增 self memory 查看、来源解释、采纳、拒绝、撤回与恢复。摄影观点导入工具默认仅预览，必须精确确认并先完成一致性备份；本分支未执行生产迁移、未导入观点、未开启 shadow/autonomous、未部署或重建任何容器。

## 41. 2026-08-30 Persona、自我记忆与官方普通用户/群能力阶段收束

- Persona V2 已通过 PR #53 合并为主线 `3182fcb3d6a1b9e03420946ce0b238477b24206b`；自我记忆 v4 已通过 PR #54 合并为主线 `f06ffbbb1bcf676fa99873bcbb7bf1a255b9dcb9`。两项 PR 的 push/PR CI 及各自合并后的 main CI 全绿，Ubuntu Python 均为零跳过，Node POSIX/UDS/进程替换、镜像和 Compose 均通过。生产 Persona、自我记忆 schema/mode 与摄影种子仍全部关闭或未执行。
- 第三阶段集成分支 `codex/higgs-official-users-and-group-20260830` 同时实现 Python/Node 两端 Bot 绑定的普通 C2C 白名单、默认关闭的普通私聊/群开关、独立限频/熔断，以及限时测试用户捕获和 `0600` 原子冻结。未知 C2C 在 durable event、Journal、模型和记忆前拒绝；owner C2C 不依赖普通用户开关。
- 捕获窗口只持久化 Bot 绑定的候选 OpenID，不保存正文或消息 ID；窗口到期关闭、精确数量冻结后永久不可复开。冻结文件、Agent 环境和 sidecar 环境的实际白名单必须完全一致，任何漂移、通配符、错误 Bot 或 release capture-only 状态均 fail-closed。冻结本身不会开启普通私聊。
- 官方群公共记忆仅从获准 `GROUP_AT_MESSAGE_CREATE` 且最终回复 `SENT` 的公开互动提取。群成员 raw ID、平台消息 ID和原句不落库，只有 HMAC 佐证令牌；单个成员重复表达不能激活，必须主人显式批准或两名不同普通成员独立佐证。敏感、个人事实、私聊、身份、权限和提示注入内容拒绝进入公共 scope。
- 群上下文固定为 Higgs 自我观点、当前群去标识公共记忆、当前成员 principal 私有记忆、近期对话；C2C 不允许 group scope，成员 A 的 principal 记忆不会被成员 B 召回。`R_AGENT_GROUP_MEMORY_ENABLED`、普通 C2C 与官方群生产开关均默认 false。
- 组合分支本地门禁为 Python `430 passed, 5 skipped`、Node `47 passed, 9 skipped`，Ruff/格式、Node 语法均通过；Windows 跳过项必须由 PR Ubuntu CI 零跳过收口。尚未部署、迁移群伴随表、运行捕获、冻结/激活白名单、开启群或普通 C2C、发送消息、重建容器或改动 NapCat。
- 第三阶段已通过 PR #55 合并为主线 `81876e14f8af61789ce66e520c59f9467054e1b1`。push/PR runs `33302169174`、`33302181366` 四项全绿，合并后 main run `33302221595` 再次全绿；Ubuntu Python 零跳过，Node POSIX/UDS/进程替换、npm 签名、Shell、镜像与 Compose 均通过。固定 72 小时观察尚未截止，因此当前只完成代码合并，不部署或开启任何新能力。

## 42. 2026-08-30 最新主线生产发布、回滚事故与压缩观察

- Persona V2、自我记忆 v4、官方普通用户及群双层记忆的文档收束经 PR #56 合并，生产目标主线为 `e60afd6b0347ed79e2308b64a26d8bb476f21049`，tree 为 `7496deb84f075fcb79ebbee473f1e8ddfcac952f`。只含 Git 跟踪文件的发布包为 593709 字节、302 个归档成员，SHA-256 为 `e001694cf5334b3dfd9abef90e68ad8640cb8f218b732a8a977f0b3e50c72294`；release gate、秘密边界与 Shell LF 通过。
- 固定 72 小时窗口在约 9.44 小时匿名证据点仍为三容器 healthy、单 Gateway、reply=true、官方 transport verified、零 rejected/致命转换和零活动批次；期间有 19 次可恢复 reconnect/ready 转换。主人明确接受压缩观察并继续部署，因此该窗口没有被宣称为“72 小时通过”，而是被本次受控重建作废。
- 首次发布在重建 Agent 后被健康门拒绝。现场匿名诊断确认 Agent 因 `PermissionError` 重启：一次性发布/回滚包装器把本应由 UID/GID `10001:10001`、模式 `0600` 的 `higgs.env` 强制改成 `root:root`，Agent 无法读取运行时私有配置。通用无参数回滚还误选了不含官方 overlay 的更早 release；随后显式回到已知健康 `6a95312bc3bf935295f9d9ff199c577baa7ae31d`，修复唯一文件属主后 Agent、sidecar 与 NapCat 全部恢复 healthy，NapCat 重启计数仍为零。
- 修正版包装器保留三份私有 env 各自的数字属主和 `0600`，显式触发/验证回滚健康，并禁止 `die` 绕过回滚。第二次尝试因首次安装留下的不可变目标已存在而安全拒绝并完成 healthy 回滚；第三次先把现有 release 与同一签名归档逐文件比对，再幂等切换并成功。
- 最终匿名验收为 release、Agent/sidecar 镜像精确匹配，Agent、sidecar、NapCat healthy，官方 transport verified，活动批次为零，单 Gateway，主人被动回复保持 true，NapCat 容器未改变。Persona V2、自我记忆 schema/mode、群、普通用户和 proactive 等所有新开关继续为 false；没有发送测试消息、重登或重启 NapCat。十个服务器临时发布/回滚文件已移动到 `/srv/trash`，均可恢复。
- 原 `higgs-72` 自动化已改为 2026-08-30 19:00:18 至 2026-08-31 19:00:18 的部署后 24 小时匿名观察，每 3 小时只读检查。开发不再被观察阻塞；下一生产动作是另行确认 owner Persona V2 灰度，完成至少 20 轮真实对话评分后，才讨论自我记忆 shadow、摄影观点种子、普通测试用户或单测试群激活。

## 43. 2026-08-30 owner Persona V2 生产灰度已开启

- 主人单独授权后，仅把生产 `R_AGENT_PERSONA_V2_ENABLED` 从 `false` 原子切换为 `true`，并且只执行了一次 Agent 强制重建。Agent 仍使用发布 `e60afd6b0347ed79e2308b64a26d8bb476f21049` 的既有镜像；official sidecar 与 NapCat 的容器标识、启动时间和重启计数均未变化。
- 切换前后均验证 Agent、official sidecar、NapCat healthy，官方 Gateway 单实例，主人被动回复为 true，`qq_official` transport 为 verified、已连接、已认证、身份匹配且健康回执小于 120 秒，活动 durable batches 为零。独立后验检查中 rejected、fatal、reconnect、pending 和 active batch 均为零，三容器重启计数均为零。
- `higgs.env` 切换前以 `0600`、`10001:10001` 元数据复制到 `/srv/trash`，临时文件原子替换时保持同一属主和模式；失败路径只恢复该私有配置并只重建 Agent。首次未压缩的一次性命令因控制台拒绝启动而没有触达服务器；压缩后的同内容脚本通过 SHA-256 与 `bash -n` 后执行成功并移入 `/srv/trash`。
- 自我记忆 schema v4/mode、群记忆、普通用户 C2C、官方群和主动发送仍全部关闭；没有迁移数据库、导入摄影观点、发送测试消息、读取身份/正文、重登或重启 NapCat。Persona V2 仍只允许官方 owner C2C，其他入口继续使用原人格路径。
- `higgs-72` 已重置为 Persona V2 上线后的 24 小时观察：2026-08-30 20:03:42 至 2026-08-31 20:03:42，每 3 小时只读检查。下一步由主人完成至少 20 轮真实 owner C2C 对话，按角色一致、自然、不夸张、内容准确四维评分并提供去敏反馈；在该验收前不得开启 self-memory shadow 或其他生产新能力。
- 本节点经独立 PR #58 合并为主线 `f55e927d9cfbe96564e8a7dd7973b4c56aad1620`；PR 的 push/pull_request 四项检查与合并后的 main CI run `33310807439` 均成功，Linux Python 零跳过，Node、Shell、发布包、秘密边界、镜像和 Compose 验收通过。该文档合并没有再次部署或重建生产。

## 44. 2026-08-30 Persona 2.1 沉浸边界修复完成本地门禁

- 主人灰度对话暴露的核心问题不是遗忘身份标签，而是诚实规则把角色履历误判为未执行现实操作：回答会先承认雪豹身份，随后用数字承载、无实体、无实际经历、长期智能体或系统配置等元叙述抹除角色生活。对话正文不进入项目记录，只保留上述匿名失败类别。
- Persona Bundle 升级为 `2.1.0`。constitution 明确身体、实验室、长跑、摄影、城市高处、远郊山地和高海拔经历属于角色世界既定事实；未知具体地名、设备或履历只允许说记不确切，不得反向否定全部经历。未执行操作规则严格限于当前工具调用和外部动作。
- style/examples 增加自然身体感、第一人称经历、自我介绍和长期关系正反例；禁用能力清单、客服式追问，以及用系统实现解释关系。模型或软件承载只有主人明确询问时才可简短说明，随后必须回到 Higgs 视角。
- PersonaGuard 新增 `IMMERSION_BREAK`，确定性捕获本次真实出现的高信号角色抹除句式。违规回答仍只允许一次有界改写；改写继续出戏时使用角色一致、诚实且不编造细节的固定降级文本。普通技术讨论中的“系统配置”不会被误拦截。
- 自动回归集从 50 条扩展到 55 条，加入身份追问、摄影经历、自我介绍、长期关系和疲惫交流。Windows 完整 Python 为 `439 passed, 5 skipped`，Node 为 `47 passed, 9 skipped`；Ruff 格式/检查、release gate、秘密边界、Shell LF 与 `git diff --check` 通过。本机无 Bash，Shell `bash -n` 和 Linux 零跳过仍由 PR CI 验收。
- 当前只完成代码、测试和文档，不修改生产配置、不重建容器、不发送消息，也不改变正在进行的 24 小时观察。下一步走独立分支、PR 与 CI；合并后仍需主人单独确认，才可部署 Persona 2.1 并只重建 Agent。
- 修复已提交到 PR #60。push run `33312732031` 与 pull_request run `33312743071` 的 Python、official sidecar 四项检查全部通过；Ubuntu 完成 Python 零跳过、Shell 语法、Node POSIX/UDS/进程替换、npm 签名、镜像与 Compose 验收。当前只追加 CI 证据并复验同一 PR，仍未部署生产。

## 45. 2026-08-30 Persona 2.1 部署准备关机检查点

- PR #60 已合并为主线 `f8354699fb84f61e1d30a64ca229d03232ded1a4`，合并后的 main CI run `33312844875` 两项任务全绿。主人已明确授权部署 Persona 2.1 并且只重建 Agent。
- 发布前匿名观察健康：三容器 healthy/零重启，单官方 Gateway、reply=true、transport verified/connected/authenticated/account-match/ok，健康回执新鲜，rejected/fatal/active batches 均为零。该检查只读且未发送消息。
- 首次非切换准备尝试因服务器到 GitHub 的连接中断退出；失败暂存目录被 trap 移入 `/srv/trash`，current release、私有配置、镜像标签和所有运行容器均未改变。
- 改由本机 GitHub API取得同一合并提交，重新封装的 604685 字节发布包含 303 个成员，SHA-256 为 `558e9b17f3e20ff85e03be35aee57869a1d6321bb0bf56d6a4fbb73d61158d74`，内含 Persona `2.1.0`；发布包已上传到服务器 `/root`，不含凭据、聊天、数据库或运行状态。
- 关机时云端第二次准备任务仍在运行，仅执行归档摘要/路径/版本校验、构建 `higgs-agent:f835...` 和成功后安装不可变 release；最长 600 秒。该任务没有切换 current、没有修改 `stack.env`、没有执行 Compose 或重建容器。失败时 staging 会移入 `/srv/trash`；成功时也只留下待激活 release 和镜像。
- 恢复顺序：①只读确认该云任务终态；②重新运行匿名生产健康门并核对 current 仍为旧 release、Sidecar/NapCat 指纹未变；③若准备成功，执行带回滚的原子 current/`HIGGS_IMAGE` 切换并仅 `--force-recreate agent`；④验证 Persona 2.1、其他新开关不变、单 Gateway、transport 和零活动批次；⑤更新本记录并走独立生产记录 PR。不得盲目重复准备任务，不得重建 Sidecar 或 NapCat。

## 46. 2026-08-30 Persona 2.1 已受控部署生产

- 关机后的只读恢复检查确认旧生产仍为 `e60afd6b0347ed79e2308b64a26d8bb476f21049`，Agent、official sidecar、NapCat 均 healthy 且重启计数为零；待激活镜像和 immutable release 均存在，镜像内 Persona Bundle 可独立加载为 `2.1.0`。
- 新 Agent 镜像以已验收的旧 Agent 镜像为基座，只覆盖 PR #60 中已经 CI 验收的 `r_agent` 包；`pyproject.toml`、锁文件、Dockerfile 与依赖均未变化。发布目录先安装到规范 `/srv/releases`，随后原子切换 `current` 与 `HIGGS_IMAGE`。
- 激活前把原 `stack.env` 连同数字属主/模式复制到 `/srv/trash`，并保留旧 `current` 目标链接。失败路径会原子恢复两者、只重建旧 Agent 并重新等待健康；本次未触发回滚，备份仍保留可恢复。
- Compose 仅执行 `--no-deps --force-recreate agent`。上线结果为 Agent 使用精确 `f8354699fb84f61e1d30a64ca229d03232ded1a4` 镜像且 Persona Bundle 为 `2.1.0`；official sidecar 与 NapCat 的容器标识、启动时间和重启计数均未变化。
- 独立匿名后验通过：三容器 healthy/零重启，官方 Gateway 为一个，reply=true，`qq_official` transport 为 verified/connected/authenticated/account-match/ok，健康回执小于 120 秒，rejected、fatal 与 active batches 均为零。`stack.env` 的模式和数字属主与备份一致。
- 生产能力边界没有扩大：Persona V2 仍只用于 owner 官方 C2C；self-memory schema/mode、群记忆、普通用户 C2C、官方群和 proactive 均保持关闭。未迁移数据库、导入摄影观点、发送测试消息、读取身份或正文、重登或重启 NapCat。
- `higgs-72` 已重置为 Persona 2.1 新基线后的 24 小时观察，窗口为 2026-08-30 23:26:02 至 2026-08-31 23:26:02（Asia/Shanghai），每 3 小时只读检查。下一步由主人继续真实 owner C2C 对话验收；本次生产记录仍须独立分支、PR、CI 后合并，不得直接推送 `main`。
- 生产记录已进入 PR #61。首轮 CI 在上海深夜暴露 8 个日计划测试仍用真实入站时间、而只冻结业务模块时钟的夹具缺陷；测试事件现与既有固定上午时钟使用同一常量，避免按 CI 运行时刻误判“当天无法完成”。本地 Python `439 passed, 5 skipped`、Node `47 passed, 9 skipped`、Ruff/格式和 release gate 通过；修正后的 push/PR runs `33320282139`、`33320283690` 四项全绿，Ubuntu Python 零跳过并通过 Node、Shell、镜像与 Compose。该测试修正不改变生产代码或运行状态。

## 47. 2026-08-31 Persona 2.2 自然雪豹语气与长度分流完成离线实现

- 主人新一轮真实对话反馈被归纳为四个匿名缺陷：日常语气仍像通用助手/接待台、雪豹感没有进入自然感知与措辞、普通问题被扩写成清单或小论文，以及一次已问问题在生成失败后被错误当成“没有问过”。项目记录不保存聊天正文。
- Persona Bundle 升级为 `2.2.0`。style/examples 明确 furry 感来自身体尺度、风向/触感/高处经验和个人偏好；日常、自我或情绪话题每次最多自然点到一处，技术回答不硬塞兽类词。连续动作戏、卖萌词和把普通助手答案贴兽设装饰均被禁止。
- 新增确定性 `compact/detailed` 分流：普通对话默认 240 tokens、二至六句和一至三小段；只有明确要求展开，或提出参数、代码、故障、推导、训练/拍摄方案等具体专业任务时才使用 800 tokens。明确要求简短始终优先。
- PersonaGuard 新增普通模式过长/菜单检测和表演式 furry 检测。超过约 300 个可见字符、三项以上列表或三处以上标题会触发一次保留事实的压缩改写；两个以上高信号动作/卖萌短语会触发角色化改写。详答允许有用结构，不因长度本身被误拦。
- 短期历史会在同主体、同会话、同通道范围内补入十分钟内 `model_failed` 的至多两条未回答问题；催答时提示先承认漏问并补答，不得声称对方没有问。失败内容仍不跨主体、群或 Bot 召回。
- 自动人格回归与人工评分清单均扩展到 67 条，覆盖日常短答、自然 furry 语气、长度分流和漏答追问。定向 50 项通过；完整 Windows Python `451 passed, 5 skipped`，Node `47 passed, 9 skipped`，Ruff、格式、release gate、秘密模式、Shell LF 与 diff 检查通过。Windows 跳过项仍由 Ubuntu CI 收口。
- 本节点只完成离线代码、测试和文档；没有连接生产、部署、改开关、迁移数据库、重建容器、发送消息或改变 Persona 2.1 的 24 小时观察。必须先同步最新远端主线、独立 PR/CI 全绿，再由主人单独确认 Persona 2.2 的 Agent-only 部署。
- Persona 2.2 已进入 PR #62，基线为最新主线 `30f615e6c7bff1489405171bc298cc8f437240c4`。因 `github.com` Git 传输端点持续超时，使用 GitHub Git Data API 上传，并在建分支前逐层验证远端 tree 与本地 tree 完全一致；没有绕过分支或直接更新 main。
- push run `33323748799` 与 pull_request run `33323762741` 均成功；Ubuntu 完成 Python 零跳过、Shell 语法、秘密/发布边界、格式、Ruff，以及 Node POSIX/UDS/进程替换、npm 签名、镜像和 Compose 验收。下一步只追加本证据并复验 PR；生产仍保持 Persona 2.1。
- 追加 CI 证据后的 push/pull_request runs `33323840063`、`33323841589` 再次全绿；PR #62 已合并为主线 `6682be3c33c78b1e486286fb224af986419cb922`，合并后 main run `33323897339` 的 Python 与 official sidecar 两项任务均成功。代码阶段完成，但生产仍是 Persona 2.1；只有主人再次单独确认后，才可构建 Persona 2.2 release 并仅重建 Agent。

## 48. 2026-08-31 Persona 2.2 已受控部署生产

- 主人明确授权“测试通过后直接部署”。部署目标为已通过 PR #62 与 main CI 的主线 `6682be3c33c78b1e486286fb224af986419cb922`，tree `b51fb97520e6667b14a94c00d572ae320b61074d`；本地与 GitHub API 再次确认 tree 一致。617609 字节、302 成员的 Git-only 归档通过 SHA-256 `b11f848cfdb5786a3f1e766cd5860dfeebeb7333c151c73999adf0b1de3a105d`、release gate、秘密模式和 Shell LF 校验，内含 Persona Bundle `2.2.0`。
- 匿名部署前门确认为生产仍运行 Persona `2.1.0` 与精确旧 release；Agent、official sidecar、NapCat 全部 healthy/零重启，官方 Gateway 单实例，reply 与 owner Persona V2 为 true，`qq_official` transport verified/connected/authenticated/account-match/ok 且回执新鲜，活动批次、rejected 和 fatal 均为零。self-memory schema/mode、群记忆、普通用户 C2C、官方群和 proactive 均保持关闭。
- 新 Agent 镜像以已验收的 Persona 2.1 Agent 镜像为基座，只替换 PR #62/CI 已验收的 `r_agent` 包；依赖、锁文件与 Dockerfile 未变化。镜像切换前独立验证 Bundle 版本与聚合哈希，随后安装不可变 release。准备阶段没有切换生产，完成后把上传归档、构建文件和包装器移入 `/srv/trash`，保留可恢复副本。
- 激活脚本在 `/srv/trash` 备份原 `stack.env` 并保存原数字属主和 `0600` 模式，原子切换 `current` 与唯一 `HIGGS_IMAGE`；任一健康门失败会恢复两项并只重建旧 Agent。本次回滚未触发，备份继续保留。Compose 仅执行 `--no-deps --no-build --force-recreate agent`。
- 独立后验在新 Agent 稳定运行后再次通过：release、Agent 镜像和 Persona Bundle 精确为 `6682be3...`/`2.2.0`；三容器 healthy/零重启、单 Gateway、transport verified 且回执新鲜，活动批次、rejected、fatal、Resume 和 reconnect 均为零。`stack.env` 元数据未漂移，规范化比较确认除 Agent 镜像标签外没有其他配置变化；official sidecar 与 NapCat 容器指纹保持不变。
- 生产能力边界没有扩大：Persona V2 仍只用于 owner 官方 C2C；self-memory schema/mode、群记忆、普通用户 C2C、官方群和 proactive 继续关闭。没有迁移数据库、导入观点、发送测试消息、读取身份/正文、重新登录或重启 NapCat。
- `higgs-72` 已重置为 Persona 2.2 上线后的 24 小时只读观察，窗口为 2026-08-31 01:11:51 至 2026-09-01 01:11:51（Asia/Shanghai），每 3 小时检查 Persona 版本、开关、三容器、单 Gateway、官方 transport 和活动批次。主人可立即继续真实对话验收；开发不被观察窗口阻塞，但后续 self-memory 或普通用户/群生产开关仍需单独确认。
- 生产记录 PR #63 的首轮 runs `33324831703`、`33324845285` 与复验 runs `33324963637`、`33324966549` 全绿，随后合并为 main `d944306da48b15f29e1d3d1745c013dfb7e1b698`；合并后的 main run `33325020959` 再次全绿，Ubuntu Python 零跳过并通过 Shell、秘密/发布包、Node POSIX、镜像与 Compose。所有记录提交均未再次部署、重建或修改生产配置。

## 49. 2026-08-31 完整聊天助手接续与权威能力账本

- 从首次公开提交 `8e4656a85d` 到当前 `main` `5f6f2a6599` 的 195 个提交、PR #1–#64、
  阶段记忆、运行文档和当前源码已经完成只读复核。新建
  `docs/29-capability-ledger-2026-08-31.md`，统一用 `implemented / deployed-off /
  active / accepted / deferred` 区分代码存在、生产部署、开关启用和真实验收。
- 当前生产权威仍是 Agent `6682be3c33c78b1e486286fb224af986419cb922` 与 Persona
  `2.2.0`。官方 owner C2C 被动回复、durable 处理和 Persona 已验收；self-memory、群
  记忆、普通用户、官方群和 proactive 仍关闭，摄影观点没有导入。
- 已锁定官方群产品边界：白名单群内任何成员都可通过 `@Higgs` 对话并拥有独立 principal
  记忆；官方事件面不接收未 `@` 的普通群消息，不以 NapCat 冒充官方能力。
- 后续顺序固定为：版本化用户/群捕获与 Persona 全用户覆盖 → 普通用户自然记忆更新 →
  self-memory 真实 shadow 与摄影种子 → 搜索/网页/文档及本人提醒计划 → 多模态、知识库、
  管理台和指标。离线开发不等待固定 72 小时，但每个生产迁移、开关和受众扩大仍单独确认。
- 本节点只修改公开文档，没有连接生产、修改配置或数据库、发送消息、重建容器、读取身份
  或凭据，也没有改变正在运行的观察自动化。下一步先完成本分支质量门、PR/CI，再从最新
  主线建立阶段 1 分支。

## 50. 2026-08-31 官方普通用户与官方群 V2 离线闭环

- 阶段 1 分支从远端主线 `8c2c4982e5ff2785ff8a21089548ba1a215145df` 建立，完成
  Bot 账户绑定的私聊与群 `CaptureEpoch + AllowlistVersion`。每轮捕获拥有 nonce、截止
  时间、最大候选数和前序版本；冻结后的 Agent/Sidecar 身份集合、版本和规范指纹必须完全
  一致，v1 文件、wildcard、错误 Bot、READY/RESUME 漂移或版本链断裂均失败关闭。
- 官方 principal 已增加显式 account scope；只有单独开启 identity schema v2 后才迁移。
  普通 C2C、官方群和各自 Persona 2.2 门均默认关闭。未知用户、未知群、未 `@` 群事件和
  错误 Bot 会在 durable queue、Journal、模型与记忆之前拒绝；普通用户仍不能继承主人命令、
  工具、审批、配置或跨用户治理。
- 私聊与群捕获/冻结均可重复受控执行：新版本以前一版本为基线增量生成，旧名单、失败状态
  和私有配置只移动到 `/srv/trash`。冻结不启用受众；生产激活由另一个精确确认入口完成，
  在线备份 identity 数据库，只重建 official sidecar 与 Agent，并验证 NapCat 指纹完全不变。
- 激活支持先普通 C2C 后单群或相反顺序。已有受众的 Agent/Sidecar/Persona 三重门必须一致，
  identity schema 必须已启用；所选受众重复激活、名单 provenance 漂移、单 Gateway、健康、
  transport 新鲜度或 active batches 任一不满足都会失败并恢复私有配置与 identity 备份。
- 本地完整验收为 Python `482 passed, 5 skipped`、Node `59 passed, 9 skipped`；Ruff 格式与
  检查、Node 语法、Shell `bash -n`、release gate、秘密扫描、Shell LF 与 diff 检查均通过。
  Windows 跳过项等待 PR Ubuntu CI 零跳过收口。
- 本节点没有连接生产、运行捕获或冻结、迁移数据库、开启普通用户/群、发送消息、重建容器
  或改动 NapCat。下一步提交阶段 PR 并等待 CI；即使合并，生产仍须按普通 C2C 与单群分别
  获得确认，不能把代码合并视为上线。
- 上线脚本的复核进一步补齐 Linux `100644` wrapper 的显式 `exec sh`、校验前只读预检、
  不完整 identity 备份回收、回滚健康等待、三服务单实例、容器实际开关与重建后新鲜回执
  校验，以及单测试群精确数量门。最终版本还与捕获/冻结共享四把锁，先停 Sidecar、排空
  durable batch，再停 Agent 并从宿主备份 identity；allowlist Bot 必须与私有 session 身份
  一致。这些改动仍只存在于本阶段分支。

## 51. 2026-08-31 官方受众 V2 经 PR #66 合并

- 阶段 1 分支经 PR #66 合并为主线 `d210fb52e652715d48a153d1edcc73c03cd6e387`。
  push 与 pull_request runs 的 Python/official sidecar 四项任务全部成功；合并后 main run
  `33363558396` 再次全绿，Ubuntu Python 零跳过，并通过 Node POSIX/UDS/进程替换、Shell
  语法、发布包、秘密边界、镜像和 Compose。
- 合并只改变 GitHub 主线。生产仍运行既有 owner C2C 与 Persona 2.2；普通用户、群、两类
  Persona 表面、identity schema v2、群记忆、自我记忆和 proactive 均未开启，未执行捕获、
  冻结、迁移、部署、重建或消息发送。
- 阶段 2 已从该合并提交建立独立分支，目标仅为普通用户本人长期记忆的明确记住、自然纠正
  与自然遗忘，以及相应幂等/隔离测试。生产记忆策略仍保持原状，任何迁移或启用另行确认。

## 52. 2026-08-31 Personal Memory V5 离线闭环

- 阶段 2 在既有 `memory.sqlite` 增加独立 opt-in schema v5；默认初始化仍只到 v3，且 v5
  不要求 self-memory v4。`R_AGENT_PERSONAL_MEMORY_SCHEMA_V5_ENABLED=false` 与
  `R_AGENT_PERSONAL_MEMORY_MODE=off` 为发布默认值，代码部署不会隐式迁移或启用。
- 普通 `user` 的明确“记住”低风险本人事实/偏好可一次激活；自然陈述需置信度不低于
  `0.94` 且两个不同消息佐证。纠正仅接受明确唯一旧内容并原子建立 `supersedes`；缺旧内容
  时要求用户澄清，绝不拿唯一但无关的偏好猜测。遗忘只逻辑失效，不物理删除。
- 事务同时覆盖 intent、hash evidence、memory item、状态和审计；相同来源重放幂等，复用键
  携带不同请求时失败关闭。作用域绑定当前 principal、channel 与 Bot account；owner/blocked、
  敏感、身份、权限和提示注入不进入普通用户自动通道。旧项存在 active successor 时不能恢复。
- 收束审计进一步扩大“忽略规则/无视限制/服从指令”等注入阻断词；同一普通 principal 一旦
  出现在另一 Bot/account 就拒绝新绑定。restore 使用递归后继检查并在合法恢复时清除过期
  时间，避免多级替代链分叉或 active 记录不可召回。
- 官方 durable 准备阶段只读取已经通过入站与学习预算的 observation；active 模式的明确记忆
  动作会先完成幂等事务，再以简短、真实回复通过原有 policy、限频、安全和 durable 发送链。
  shadow 不会回复“已记住”，后台 reconcile 只做幂等收束与可选向量写入。
- 本地完整 Python 为 `515 passed, 5 skipped`；Node 为 `59 passed, 9 skipped`。Ruff、格式、
  Node 语法、release gate、秘密边界、Shell LF 与 diff 检查通过；Windows 跳过项等待 PR 的
  Ubuntu 零跳过 CI。生产没有部署、迁移、启用普通用户/群、发送消息、重建或改动 NapCat。

## 53. 2026-08-31 Personal Memory V5 经 PR #67 合并

- 阶段 2 已通过 PR #67 合并为 main
  `a693013cf2d4edfda6e8f87c0ec0a108b40ac84d`。push run `33368455489`、
  pull_request run `33368523783` 和合并后 main run `33368598779` 均全绿；Ubuntu Python
  零跳过，官方 Sidecar、Shell、发布包、秘密边界、镜像和 Compose 同时通过。
- 合并没有触发生产部署或数据库迁移。普通用户/群、Personal Memory v5、self-memory v4、
  摄影种子和 proactive 仍保持关闭；没有捕获、冻结、发送消息、重建容器或修改 NapCat。
- 阶段 3 已从该主线建立 `codex/higgs-self-memory-shadow-20260831`，只补自我记忆真实
  shadow 的匿名收据、失败重放、演进评测与摄影种子安全导入门。生产动作继续分别确认。

## 54. 2026-08-31 self-memory 真实 shadow 离线闭环

- self-memory v4 新增同库 `self_memory_shadow_runs`，每次 self/adopted lane 只记录输入与
  run key 哈希、状态、尝试次数、候选/拒绝/隔离计数、错误类型和耗时。模型、parser 或 DB
  失败进入明确 failed；pending 可幂等重放，complete 会跳过，匿名 readiness 不返回正文、
  身份或平台消息标识。
- `SelfMemoryService` 不再隐式迁移 v4；schema 必须由显式配置先迁移。shadow 在服务和调用
  两层都强制禁止自动激活，即使调用者误传 `allow_auto_activate=true` 也只能 considering。
  相同 persona/kind/content 复用同一项并追加证据；自称“以前说过”的原句必须是已验证
  SENT 回复子串。
- 成功处理后清空 self observation 的完整回复正文，只保留 SENT 绑定与内容哈希；隔离候选
  仅保存内容哈希，来源 principal 和平台消息标识同样哈希。owner 硬删除会事务式清理关联
  metadata、evidence、evolution 和孤立 observation，避免伴随表残留私密正文。
- 新增 38 条中文 self-memory shadow 数据集与聚合评测入口，覆盖 self stance、外部思想、
  空结果、隔离、拒绝、冲突、敏感、注入、身份和权限。门槛为 precision `>=0.95`、recall
  `>=0.90`、处置准确率 `>=0.95`，误激活、污染与非预期解析失败必须为 0。
- 摄影种子 preview 仍不探测数据库；确认导入必须使用既有 v4 普通文件、通过 quick_check、
  小于 512 MiB，并先用 SQLite backup API 在同目录生成、校验哈希和尽力设为 `0600` 的一致
  备份。回执不含路径或观点正文，失败保留已验证备份用于恢复。
- 本地门禁为 Python `538 passed, 6 skipped`、Node `59 passed, 9 skipped`；Ruff、格式、
  Node 语法、release gate、秘密边界、Shell LF 与 diff 检查通过。生产没有部署、迁移、运行
  shadow、导入摄影种子、开启自主成长、发送消息或重建容器；下一步为阶段 PR 与 Ubuntu CI。

## 55. 2026-08-31 PR #68 独立审计后的隐私与幂等收束

- 阶段分支已创建 PR #68；首轮 push 与 pull_request CI 均全绿，但独立只读审计发现失败
  提取的临时 SENT 正文、post-SENT 回调异常、并发相同观点和评测收据四项发布阻断，因此
  暂未合并，先在同一 PR 修复。
- observation 正文现在只保留到当前 self lane 结束；成功、空结果、隔离或异常都会释放，
  无 evidence 的 observation 同时移除。若进程在两步之间崩溃，新服务实例启动时会立即清理
  所有旧正文和孤立记录。重放只能用与既有 SENT fingerprint 精确匹配的瞬时回复文本恢复校验。
- transport 已经返回 `SENT` 后，记忆观察或 risk ledger 收尾异常只匿名告警，不能把发送状态
  反向变为 retry。self-memory proposal 增加 persona/kind/content 语义幂等指纹，不同来源
  并发写入同一观点也只复用一个 item；并发激活竞争会重新读取已激活状态。
- 评测 JSON 现带内容无关的 run ID、时间、评测器/模型/提示版本、数据集与输出集合哈希；
  外部模型 outputs 未声明精确 model/prompt 版本时退出码 2。固定 fixture 仍不代表真实模型。
- 修复后本地 Python 为 `544 passed, 6 skipped`，Node 为 `59 passed, 9 skipped`；Ruff、格式、
  release gate、秘密边界、Shell LF、Node 语法和 38 例评测均通过。生产仍未部署、迁移、运行
  shadow、导入观点、发送消息或重建容器；须重新推送并等待 PR #68 新一轮 Ubuntu CI。

## 56. 2026-08-31 PR #68 合并并进入安全工具与个人任务阶段

- PR #68 已合并为 main `517bb23a8a58aec70b7751740a86e2dae1d7da49`。审计修复后的
  push/pull_request 两套 CI 和合并后 main run `33374862049` 均成功；Ubuntu Python 零
  跳过，官方 Sidecar、Shell、发布包、秘密边界、镜像与 Compose 同时通过。
- 合并只更新 GitHub 主线。生产 self-memory schema/mode、普通 C2C、官方群、摄影种子、
  自主成长、搜索工具和普通用户主动任务仍关闭；没有部署、迁移、发送消息、重建或改动
  NapCat。生产匿名观察页面连接仍未在本节点重新建立，状态不可臆测。
- 阶段 4 已从该提交建立 `codex/higgs-safe-tools-personal-tasks-20260831`，并在隔离 worktree
  并行实现两块：安全 `web_search/read_url/document_read`；普通白名单用户本人提醒与计划。
  两块都必须默认关闭、作用域绑定当前 Bot/principal/session，并经独立审计与全量门禁后才
  能进入阶段 PR；任何真实网络工具、普通用户任务或主动投递启用仍须分别确认。

## 57. 2026-08-31 阶段 4 安全工具与个人任务完成离线集成

- 阶段分支 `codex/higgs-safe-tools-personal-tasks-20260831` 仍以 main `517bb23a8a58aec70b7751740a86e2dae1d7da49` 为基线；本节点只完成离线源码和测试，尚未创建或合并阶段 PR。
- `web_search`、`read_url` 与 `document_read` 已建立默认关闭的执行边界：角色/surface/data scope、规范参数审批哈希、actor/session 输入输出预算、幂等冲突和 hash-only 审计均失败关闭。网络逐跳校验 scheme/userinfo/端口、两次 DNS、公网 IP、重定向、内容类型、超时和响应大小；默认 transport 不联网。
- 文档读取只接受当前事件中的 opaque attachment handle，并同时绑定 Bot、sender、principal、session 与事件。隔离区路径只保存在进程内 binding，不进入 `InboundEvent` 或 durable queue；旧式 path/URL 字段在重放时拒绝。失败和超过 24 小时的隔离文件只移入 recycle，不直接删除。
- 普通用户提醒和今日计划只允许已获准的官方 C2C `user` principal。所有短 ID 操作同时校验 principal、当前 Bot、channel、surface 和 target；群、OneBot 普通用户、错误 Bot 及他人任务均拒绝。owner 旧接口继续兼容。
- `DeliveryTarget(channel, bot_account, target_id, surface)` 成为个人任务持久目标。普通任务 mode 与普通 proactive 为独立开关；owner proactive 和 ordinary proactive 在 Agent 与 Sidecar 两端分别校验，普通主动目标还必须属于当前 Bot 的冻结私聊名单。任何一边未开都不发送，提醒不会向群或跨通道回退。
- 独立审计修复后的完整回归为 Python `590 passed, 7 skipped`、Node `59 passed, 9 skipped`；Ruff、格式、Node 语法和 release gate 通过。本机没有 Bash，Shell `bash -n` 与 Windows 跳过项由 Ubuntu PR CI 收口，不能把本节点写成 PR/CI 或生产验收。
- 生产没有改变：未部署代码、配置真实搜索 provider、开放网络、迁移数据库、开启普通任务/主动投递、捕获用户、发送消息或重建容器；NapCat 未参与。下一步是收束独立审计、最终门禁、阶段 PR/CI，任何生产动作仍需单独确认。
- 阶段 PR #69 已创建。首轮 push run `33382686895` 与 pull_request run `33382728996` 的 Python/Sidecar 两项任务全部成功，Ubuntu 已收口 Windows 跳过项、Shell、POSIX/UDS、镜像和 Compose。本次追加 CI 证据后仍须等待新一轮两套 CI，再合并；生产边界不变。

## 58. 2026-08-31 PR #69 合并，Stage 4 进入主线

- 追加 CI 证据后的 push run `33382859370` 与 pull_request run `33382862796` 再次全绿；PR #69 合并为 main `4e13e2ec0014fe25fd6f322391a7455e9bd5f402`，合并后 main run `33382985494` 成功。
- Ubuntu 已执行 Python 零跳过、Shell 语法、秘密/发布包、Node POSIX/UDS/进程替换、镜像和 Compose；未以 Windows 跳过项代替 Linux 验收。
- 合并只更新 GitHub 主线。安全工具仍没有真实 provider 或业务路由，普通任务 mode/proactive、普通 C2C、群和其他阶段开关仍关闭；没有部署、迁移、捕获、发送消息、重建容器或改动 NapCat。
- 下一阶段可继续实现多模态/附件 ingress 闭环、私有知识库与管理指标；若要先让普通用户或个人任务进入生产，必须分别完成代码部署、名单/identity 前置和独立开关确认。

## 59. 2026-09-01 Persona 2.2 的 24 小时观察结论：证据不完整

- 观察窗口按约定于 2026-08-31 01:11:51 开始、2026-09-01 01:11:51（Asia/Shanghai）截止。窗口早期已有部署后匿名健康基线，但最后三个计划检查点没有附加可用的服务器终端，无法执行 `observe_official_stability.sh`。
- 因缺少截止前的只读现场证据，本窗口不得标记为“24 小时稳定性通过”，也不得臆测容器、Gateway、transport、回执新鲜度、活动批次或开关在缺失时段的状态。缺少证据本身不等同于发现生产异常。
- 本次没有发送测试消息、重启容器、重新登录、修改配置或读取/记录任何身份、凭据、正文、平台消息标识、二维码或登录状态。生产未因观察截止而发生变化。
- `higgs-72` 观察自动化已在截止后删除，避免继续越过既定窗口检查。若需要补做稳定性验收，应重新建立一个明确的新窗口并先恢复安全只读终端上下文，不能把新证据追记为本窗口的连续 24 小时结论。

## 60. 2026-09-03 identity v2 与普通 C2C 上线链路离线收束

- 新阶段从远端 main `55ff465fa038dc51cff0d83e91c2ad367571077b` 建立
  `codex/higgs-ordinary-c2c-capture-20260903`。本节点只完成离线实现和验证；没有连接或
  修改生产，没有迁移数据库、捕获/冻结用户、扩大受众、发送消息或重建容器。
- 新增独立 identity v2 生产迁移入口。它要求精确确认、owner 官方被动回复健康、所有普通
  C2C/群与对应 Persona 门关闭、零活动 durable batch，并对 `identity.sqlite` 做 SQLite
  一致性备份。迁移显式把既有 owner principal 绑定到当前已认证 Bot，保留原 principal 与
  记忆，只重建 Agent；Sidecar 与 NapCat 的容器身份、启动时间和重启计数必须完全不变。
- 任一 schema、owner 连续性、Bot 绑定、容器健康、单 Gateway、transport 新鲜度、活动批次
  或配置契约检查失败，都会恢复私有 `higgs.env` 与 identity 数据库；失败产物和备份保留在
  私有回收目录，不直接删除。迁移脚本与捕获、冻结、受众激活使用互斥锁，避免交叉执行。
- 受众激活器已改为必须先看到已经迁移的 identity v2，不再在打开普通用户/群/Persona 时
  隐式迁移身份。既有受众激活 identity 备份仍保留，用于回滚激活窗口内新建的 principal。
  普通用户捕获继续只短暂停 Sidecar、运行一个有限 Gateway，并恢复 owner transport；Agent
  和 NapCat 不参与捕获重建，冻结仍只更新版本化名单而不启用受众。
- 定向回归 `32 passed`；本地完整 Python `602 passed, 7 skipped`，Node
  `59 passed, 9 skipped`，Ruff、格式、Node 语法、release gate、秘密边界、Shell LF 和
  diff 检查通过。本机没有可用 Bash/WSL，Shell 语法及 Windows 平台跳过项必须由 PR 的
  Ubuntu CI 收口；当前不能写成 PR/CI 或生产验收。
- 下一步：提交独立 PR 并等待两套 Ubuntu CI；合并后如需生产推进，先部署脚本且保持所有
  新开关关闭，再分别取得 identity 迁移、CaptureEpoch、名单冻结和受众/Persona 激活确认。
- 阶段 PR #74 已创建。首轮 push run `33659087861` 与 pull_request run `33659126582` 的
  Python/Sidecar 四项任务全部成功；Ubuntu 已执行新增 Shell 语法、Python 零跳过、Node
  POSIX/UDS/进程替换、发布包、秘密边界、镜像与 Compose。本次追加证据后仍需等待新提交
  触发的两套 CI 再合并；生产边界没有变化。

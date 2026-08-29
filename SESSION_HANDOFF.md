# Higgs 权威接管交接（2026-08-26）

> 本文件是下一次接手的第一入口。不得写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态内容。

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

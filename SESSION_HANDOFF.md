# Higgs 权威接管交接（2026-08-26）

> 本文件是下一次接手的第一入口。不得写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态内容。

## 1. 当前权威边界

- 本地统一项目根：`D:\丘山\R\_Higgs`；主仓库在 `source`，阶段工作树在 `worktrees`，私有归档和发布包分别在 `archives`、`artifacts`。
- 本地权威集成工作树：`D:\丘山\R\_Higgs\worktrees\R_Higgs-takeover-20260826`，分支 `codex/higgs-integration-20260826`。
- PR/生产验收工作树：`D:\丘山\R\_Higgs\worktrees\Higgs-wt-pr-stack`；当前记录分支为 `codex/higgs-recovery-and-local-consolidation-20260827`。
- 官方 QQ 硬化已由 PR #21 合并到 GitHub `main` 的 `aa877df`。2026-08-28 已创建独立官方机器人并生成新凭据；AppID/AppSecret 仅写入服务器 `0600` 私有环境文件，未进入聊天、日志或项目记忆。官方代码现已随禁用态生产发布部署，但主人 OpenID 尚未绑定，官方通道继续关闭。
- 群聊风控误判修复已由 PR #23 合并到 GitHub `main` 的 `38a5ddc`，合并后主线 CI 通过；该修复现已随 Agent-only 发布进入生产。
- 生产源码/Agent 镜像现为 `d2d40a7e47618022e258d3a534f62aab68b04833`；官方通道仍关闭，个人 QQ 权威状态仍离线。GitHub 文档主线与生产运行提交必须继续明确区分。
- GitHub 已按批准顺序合并 PR #7–#17；所有功能、迁移和 OpenCloudOS 离线构建修复均通过分支、PR 与合并后主线 CI，没有直接向 `main` 推送。
- 已按主人确认完成本阶段生产部署，并保持既有 `live` 回复模式；官方 QQ 和模型记忆候选仍显式关闭。
- 开放官方主人沙箱、加入测试群、启用模型候选或改变 live 状态仍必须获得单独确认。

上述生产提交与健康结论来自 2026-08-26 的实时发布验收；后续继续操作仍须重新核对主线、镜像和匿名 transport 状态，不能把本次结果当作永久在线保证。

## 2. 已完成代码阶段

| 阶段 | 总集成提交 | 独立阶段分支/提交 | 状态 |
| --- | --- | --- | --- |
| 0 发布基线 | `f134fc9` | `codex/higgs-takeover-20260826` / PR #7（已合并） | LF、无固定 deploy 用户、可配置根目录、校验、原子激活与可验证回滚已实现 |
| 1 NapCat 可观测 | `00f5831` + `9e7ff52` | `codex/higgs-phase1-stability-20260826` / PR #8（已合并） | 六维匿名状态、真实只读健康标记、告警/恢复幂等、有限进程恢复与 `transport.sqlite` 已实现 |
| 1A 群聊风控按成员隔离 | `38a5ddc` | `codex/higgs-group-sender-guard-20260827` / PR #23（已合并） | 自动化来源与非主人熔断在群聊中改为盐化的成员级作用域；群级/全局发送预算保持不变；已随 Agent-only 发布进入生产 |
| 2 官方 QQ 双通道 | `945b5b2` + `92df3d2` + `30ca0c5` + `abc4a0c` | `codex/higgs-phase2-official-qq-20260826` / PR #9（已合并） | 官方 SDK 1.2.2、Gateway/Resume、有限监督恢复、统一类型回执、身份隔离和被动原路回复已实现；默认关闭 |
| 2A 官方 QQ fail-closed 硬化 | `aa877df` | `codex/higgs-official-qq-mvp-20260827` / PR #21（已合并） | 私有 Resume/READY 身份、真实鉴权状态、精确 intents、有限 SDK 重连、异常会话断链和发送幂等已完成；仍默认关闭 |
| 2B 官方主人一次性捕获 | `187a959` + `36e936d` | `codex/higgs-official-owner-capture-20260828` / PR #25（已合并） | 显式单测试用户确认、首个 READY 后 C2C、无正文日志、私有备份、原子 OpenID 绑定与成功即停已实现并禁用态部署；尚未真实捕获 |
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

1. 禁用态生产发布与 Agent-only 切换已完成；NapCat 容器身份和启动时间保持不变。个人 QQ 仍为持续离线，不自动重启、重复登录或把容器健康误报为 QQ 在线。
2. 官方机器人、新凭据私有落盘、主人测试用户登记和官方适配器禁用态部署已完成；平台确认 IP 白名单为空时不限制请求来源。一次性捕获切片已由 PR #25 合并并随不可变发布进入生产，下一步在动作时确认平台仍只有主人一个测试用户，然后运行五分钟捕获窗口并私有绑定主人 OpenID；之后另行申请官方主人沙箱启用确认。生产模式在当前适配器中显式拒绝。
3. 官方灰度固定为：假 Gateway → 主人沙箱私聊 → 72 小时与进程重启 Resume → 一个仅 `@` 测试群 → 再评估扩大；提醒仍只走 NapCat。
4. 观察任务保留到原定截止时间并生成匿名结论；已经捕获两次快速 `KickedOffLine`，结论必须为失败，不以再次人工恢复重置证据。

## 7. 本地目录结构（2026-08-27）

- 已将散落在 `D:\丘山` 根目录的主仓库、八个 D 盘阶段/交接工作树、私有归档和发布包统一移动到 `D:\丘山\R\_Higgs`；没有删除文件。
- 结构固定为：`source`（主仓库）、`worktrees`（Git 工作树）、`archives`（私有归档）、`artifacts`（发布包）。
- 所有移动前 D 盘工作树均为干净状态；移动使用 `git worktree move`，主仓库移动后执行 `git worktree repair`。九个 D 盘工作树逐一验证路径、分支、提交和 `git status` 正常。
- 移动后旧 `.venv` 的启动脚本仍引用旧绝对路径；九份旧虚拟环境已完整移入 `archives/replaced-venvs/20260827-114344`，未删除。当前 PR 工作树已从锁文件重建环境，Ruff、格式和完整 pytest（`251 passed, 4 skipped`）重新通过；其他工作树需要使用时再按各自锁文件重建。
- 四个早期工作树仍位于 `C:\Users\32516`，不属于本次 D 盘根目录清理；其中 Memory V2.1 旧工作树存在八项未提交内容，严禁在未单独审计前移动、清理或覆盖。

## 8. 明确未完成事项

- 48 小时观察尚未结束，且已捕获两次明确 `KickedOffLine`；不能宣称长期在线问题已解决。人工恢复后的连续在线时长需重新累计，同时保留原观察窗口的失败证据。
- 官方 QQ Bot 应用、服务器私有凭据、主人测试用户登记及禁用态适配器部署已具备，但主人 OpenID 尚未私有绑定；尚无真实 Gateway、沙箱私聊或 72 小时 Resume 证据。官方通道仍关闭。
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

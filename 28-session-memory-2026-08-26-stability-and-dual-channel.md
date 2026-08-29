# 2026-08-26：稳定性、双 QQ 通道与受治理扩展

> 本文件是追加式阶段记忆。严禁写入 QQ/OpenID、服务器地址、凭据、聊天正文、二维码或登录状态文件内容。

## 节点 1：方案锁定

- 生产基线仍为 `d7aa96d`；本轮开发分支为 `codex/higgs-takeover-20260826`，不直接推送 `main`。
- 采用双通道渐进迁移：NapCat 低频承接既有好友、群与提醒；官方 QQ Bot 使用独立身份，从主人沙箱开始。
- 不把 LLBot、Lagrange 等另一种个人 QQ 非官方协议端当作风控掉线的根治方案。
- 阶段顺序固定为：发布基线 → NapCat 可观测与安全恢复 → 官方 Bot MVP → 只读工具治理 → Memory V2.1 模型候选 shadow。
- 生产部署、正式开放测试群、切换 live 均需单独确认；当前没有官方 QQ Bot 应用，先完成离线实现和假 Gateway 测试。

## 节点 2：代码实现完成

- 公共 transport 已扩展：发送支持可选 reply message ID；状态包含鉴权、最近心跳 ACK 和最近事件；未知平台回执保持 `UNKNOWN`。
- 新增 `OneBotAdapter`，把现有 NapCat 发送与状态探针包裹到统一接口。
- 官方依赖精确锁定 `qqbot-agent-sdk==1.2.2`；调研快照提交为 `6163b5dc979a2f12379b1916805009075008c3c3`，MIT，Beta。
- `OfficialQQAdapter` 已实现配置校验、Gateway 生命周期、Token、Session/Resume、事件规范化、心跳 ACK 超时、群白名单、被动回复与回执校验。
- 官方主人身份只能由私有配置显式绑定到既有 owner principal；已存在的冲突映射默认拒绝，普通用户不自动跨通道合并。
- 官方 MVP 只允许主人 C2C 和白名单群 `@` 入站；发送必须引用原入站消息。提醒仍只走 NapCat，不进行透明切换或跨通道转发。
- 阶段 0 已完成 LF、无固定 `deploy` 用户、可配置发布根、归档校验、原子激活与可验证回滚。
- 阶段 1 已新增匿名 `transport.sqlite`，记录六维状态、转换、持续时间、告警领取和恢复结果；阶段边界数据库数为 11。
- 阶段 3 已完成受治理的 `/higgs server status`：只读宿主 JSON、审批哈希、默认拒绝、限频、超时、幂等和哈希化 SQLite 审计；最终备份数据库数随 `tool_audit.sqlite` 增至 12。
- Memory V2.1 已完成严格 JSON 候选、证据绑定、敏感/权限/提示注入隔离、追加式 shadow 存储和 36 例中文全提取链路对照评测；主人仅能只读查看模型候选队列，默认仍关闭。

## 节点 3：本地代码验收

- 总集成全量 pytest：`249 passed, 4 skipped`；Ruff 和格式检查通过。
- 发布安全门通过：206 个跟踪文件、226 个归档成员，秘密模式、Shell LF 与归档路径均合格；三份 Compose YAML 解析通过。
- 四个跳过项属于 Windows 符号链接权限约束，必须等待 Ubuntu CI 以零跳过补跑健康标记、发布激活/回滚和只读状态文件场景。
- `detect-secrets==1.5.0` 扫描全部 Git 跟踪文件；7 个命中均为测试夹具/占位值，未发现真实凭据。
- corlinman 上游更新为 `v1.56.5` / `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`（MIT）。本轮只吸收真实发送回执、三态身份、窄 IPC 和安全下载治理思想，不复制源码，也不开放搜索/下载。
- 跨阶段复核已补齐：OneBot 全部发送路径使用带三态结果的适配器；官方来源不能误建 NapCat 提醒；Gateway 仅对普通故障有限退避恢复；`server_status` 仅限主人私聊；模型候选队列无激活、覆盖或删除入口。
- 以上只是离线/假 Gateway 证据，不等于真实模型评测、官方沙箱、72 小时在线、生产发布或 48 小时 NapCat 观察验收。

## 节点 4：PR 与 CI

- 已建立五个累计阶段分支和 PR：#7 发布基线、#8 NapCat 稳定性、#9 官方 QQ 双通道、#10 只读工具、#11 Memory 模型候选 shadow；每个 PR 只相对上一阶段展示增量。
- 五个分支的 push CI 与五个 PR CI 均通过；Ubuntu 已执行发布安全门、Shell 语法、Ruff、格式、完整 pytest 和零跳过检查。
- PR #7–#11 已按授权顺序合并，运行代码的功能合并点为 `c45c4ef4fc09c67ab4510ab6fddbb296d539cf2f`；PR #12 随后只更新交接文档。未进行生产部署、QQ 登录操作、live 切换或官方沙箱联调。
- PR 和 CI 通过及代码合并只代表源码基线就绪，不代表部署、48/72 小时在线观察或真实消息验收。

## 节点 5：生产只读预检与迁移阻断

- 主人已授权进入部署准备；通过本机既有密钥和已知主机指纹完成只读预检，没有记录服务器地址、凭据或账号标识。
- 生产仍运行 `d7aa96d`。NapCat 容器 healthy 但 QQ 权威状态为离线，agent 按预期 unhealthy；日志有两次踢线信号，未自动重启或登录。
- 现有十库中九库完整。`memory.sqlite` 的五条旧记录在旧版 SQLite 下仍保留新增默认列之前的物理编码，导致 `integrity_check` 报告 `importance/source_trust` NOT NULL 问题，逻辑读取未丢失。
- 一次性 schema v3 物化迁移已通过 PR #14、Ubuntu CI 和合并后主线 CI；部署前已创建 root-only 十库与私有配置原始恢复快照，旧 memory 告警按原样保留。
- 不可变源码发布 `acb49ed1377d9fe43fa7737e9af4eb3309e67585` 已安装并切换 current，旧链接进入 `/srv/trash`；运行中的旧 agent/NapCat 尚未重建。
- 两次构建都在 frozen lock 的上游 wheel 下载阶段停滞，有限等待后已取消且无残留。隔离临时容器从腾讯镜像安装相同 SDK 与依赖成功，故障定位为锁文件源 URL 与现有服务器网络路径不兼容。
- Dockerfile 改为按锁定版本通过腾讯镜像预热实际 venv，再执行 offline frozen sync；增加部署顺序测试后本地总验收为 `251 passed, 4 skipped`，继续生产构建前必须先过 PR/CI。
- 运行依赖预热已在生产构建中成功；最终离线项目安装进一步发现 hatchling 构建后端未包含在运行依赖导出中。现固定 `hatchling==1.27.0` 并单独预热，服务器隔离探针验证可用；本地总验收仍为 `251 passed, 4 skipped`。
- 再次生产构建确认 editable 安装还会要求仅开发态需要的 `editables`；最终项目同步现明确使用 `--no-editable`，从而保持生产 wheel 安装语义且不扩大联网依赖面。

## 后续节点

1. 合并 OpenCloudOS 构建后端预热修复，从新主线重新打包并完成镜像构建。
2. 显式保持官方 QQ 与模型候选提取关闭，只重建 agent；复核 schema v3 与十二库后安装宿主状态 timer。
3. 谨慎应用 NapCat 有限重启策略，到扫码环节请主人恢复登录，随后开始 48 小时匿名观测。
4. 官方开放平台登录和沙箱应用创建到真实联调阶段再请主人配合；真实模型评测同样需要私有配置后单独执行。

## 节点 6：生产发布与观察起点

- PR #16 固定并预热 `hatchling==1.27.0`，PR #17 将最终项目安装固定为 `--no-editable`；分支、PR 与合并后主线 CI 全部通过。最终不可变源码和 Agent 镜像提交为 `b7d0beceed3f5bd057ad15490cb5b0f2ac0a01d3`。
- 新镜像在生产宿主完成断网、只读 smoke test，运行包与官方 SDK 精确版本断言通过；官方 QQ 明确保持关闭，模型记忆候选保持 off。
- Agent 只重建后完成 schema v3 物化迁移。十二个运行数据库全部完整，既有六条记忆未增未减；startup 备份包含十二库、逐库 quick check 通过且不含秘密。
- 宿主只读状态 service/timer 已部署并 active，白名单 JSON、权限、原子写入和只读挂载验证通过。
- NapCat 已按固定 digest 重建，应用 `on-failure:5` 和共享健康标记。管理 Token 仅在获准后直接提交到本机安全隧道中的 WebUI，没有写入聊天、项目文件或临时磁盘文件。
- 2026-08-26 21:17（Asia/Shanghai）匿名实时基线为 NapCat/Agent healthy、OneBot 可达、QQ 权威在线、账号匹配、健康与 action 回执成功，`transport.sqlite` 已记录正常恢复。从该时刻开始至少 48 小时观察；初始恢复不等于长期稳定性验收。

## 节点 7：KickedOffLine、人工恢复与本地归拢

- 观察在 2026-08-26 23:38 捕获明确 `KickedOffLine`；初次恢复后约 2 小时 21 分即失效。NapCat 容器和 OneBot 端口仍可达，但 QQ 权威状态离线、Agent unhealthy，证明个人 QQ 长期在线问题没有因可观测性部署而消失。
- 失效会话持续约 11 小时 54 分，WebUI 同时报告登录态失效与无法重复登录，属于 QQ 进程残留的假登录状态。Agent 没有读取、保存或使用主人在页面中尝试的密码。
- 主人要求继续处理登录后，只执行一次受控 NapCat 重启清除残留进程，没有自动或循环重启；随后由主人扫码。2026-08-27 11:34 匿名复核重新满足 QQ 在线、账号匹配、OneBot/action/health 成功以及 NapCat/Agent healthy，恢复事件已持久化。
- 本地文件统一归拢到 `D:\丘山\R\_Higgs`：`source` 为主仓库，`worktrees` 为阶段工作树，`archives` 为私有归档，`artifacts` 为发布包。八个链接工作树使用 `git worktree move`，主仓库移动后执行 repair；九个 D 盘工作树逐一验证干净、路径和提交保持不变。
- 九份旧 `.venv` 因内部启动脚本保留旧绝对路径而不可直接复用，已完整移动到 `archives/replaced-venvs/20260827-114344`，没有删除。当前 PR 工作树按锁文件重建后，Ruff、格式和完整 pytest（`251 passed, 4 skipped`）再次通过。
- 四个既有 C 盘工作树未移动；其中旧 Memory V2.1 工作树存在八项未提交内容，必须保留并等待单独审计。

## 节点 8：第二次快速踢线与官方 QQ fail-closed 硬化

- 上午扫码恢复只维持约 1 小时 54 分；2026-08-27 13:28 再次捕获明确 `KickedOffLine`。NapCat 容器与 OneBot 仍可达，但 QQ 权威状态离线、Agent unhealthy。主人再次明确授权后只执行一次受控重启并人工扫码，没有自动或循环登录；16:00 匿名复核重新在线并关闭临时 WebUI 隧道。两次快速失效已使本轮 48 小时稳定性验收确定失败。
- 新建独立工作树 `Higgs-wt-official-qq` 和分支 `codex/higgs-official-qq-mvp-20260827`，严格基于 GitHub `main` 的 `d255f41`；唯一既有 dirty 的 Memory V2.1 工作树保持未触碰。
- 官方 Gateway Resume 不再使用 SDK 默认 JSON 存储，改用 Higgs 自有的原子私有存储：限制大小与结构、拒绝符号链接、POSIX 强制 `0600`、异常内容不回显；持久化 READY bot 身份，使进程重启 Resume 不以 AppID 冒充 bot account。
- 官方通道只有在 READY/RESUMED 且 bot 身份可信后才报告认证在线；断线、心跳超时、Invalid Session 清理和停止都会 fail-closed。过期或不完整的 Resume 会清理旧 bot 身份，fresh Identify 必须等待新的 READY；异常非布尔 Invalid Session 会终止 SDK 读取循环并主动关闭 WebSocket。`transport.sqlite` 的 `qq_online` 只在 connected 且 authenticated 时为真，离线不再残留账号匹配。
- 官方事件只放行主人 C2C 与白名单 `GROUP_AT_MESSAGE_CREATE`；未知类型、scope 不匹配和 READY 前事件直接丢弃。官方关闭时，已保留在私有配置中的主人/群身份不会进入 OneBot 权限、风险或回复策略。
- 针对固定 SDK 1.2.2，运行时重新断言精确版本；Identify intents 收窄为群/C2C 公共消息，SDK 内部重连预算由近似无限限制为 5 次，异常非布尔 Invalid Session 被终止；SDK 自身可能包含会话 ID、OpenID 或 API path 的日志被整体压制，只保留 Higgs 的匿名状态与错误类型。
- 官方被动发送增加同进程串行幂等：并发相同请求只发送一次；相同 key 但目标、正文或回复 ID 不同会拒绝；conversation target 必须匹配 `channel + kind + READY account + target` 的规范形式。跨进程回执持久化仍留给后续独立切片。
- 本地完整 pytest 为 `267 passed, 4 skipped`，Ruff、格式检查、发布包校验、秘密扫描和 Shell LF 门禁通过。PR #21 的 push、pull request 与合并后 `main` 三组 Ubuntu CI 均通过，合并提交为 `aa877df`；没有进行生产部署或凭据处理。真实官方应用仍不存在，官方通道仍关闭；下一步由主人在开放平台创建沙箱应用，凭据只进入服务器 `0600` 私有配置。

## 节点 9：群聊非主人风控误判与成员级隔离

- 匿名只读审计确认某获准自然触发群的配置已正确热更新；普通成员曾有成功回复，但随后多个成员的入站被旧实现共用群 conversation key，集体达到高频来源阈值与会话熔断阈值。主人绕过非主人风控，因而呈现只回答主人的假象；没有记录群号、成员身份或聊天正文。
- 经主人明确授权，先对 `risk_ledger.sqlite` 与 `conversation_guard.sqlite` 创建私有一致性备份，再仅清除目标群的一条误判来源冷却、一条熔断状态和八条临时熔断计数。验证三类状态均归零；没有发送测试消息、修改白名单、重启容器或重新登录。
- 新分支 `codex/higgs-group-sender-guard-20260827` 将群聊来源检测与非主人熔断绑定到盐化的 `conversation + sender` 作用域；成员身份不以明文进入风控库。原有群级每分钟预算、全局分钟/小时/每日预算、单成员高频冷却和主人权限均保持不变。
- `risk_events` 通过可重复的在线加列迁移新增 `source_hash`；旧私聊作用域保持兼容，旧群级误判状态不会继续套用到成员级 key。本地完整 pytest 为 `271 passed, 4 skipped`，Ruff、格式与发布门禁通过；尚需 PR/CI 和单独生产部署确认。

## 节点 10：关机前远端检查点

- 本地提交 `7a58188` 已固化全部群聊成员级风控修复；GitHub Git Data API 生成的等价远端提交为 `23898fc`。两者 tree SHA 完全一致，工作树干净。
- 远端分支 `codex/higgs-group-sender-guard-20260827` 已创建 PR #23；分支 push CI 与 PR CI 均通过。应主人要求在关机前暂停，PR 尚未合并，生产环境也未部署。
- 下一次恢复顺序固定为：复核 PR #23 状态并合并 → 等待合并后主线 CI → 更新权威交接记录 → 另行向主人申请 Agent-only 生产部署确认。未经确认不得部署、发送测试消息或改变 live 配置。

## 节点 11：PR #23 合并与掉线报告待核

- PR #23 的分支与 pull request 两组 Ubuntu CI 均通过，随后合并为 GitHub `main` 的 `38a5ddc`；合并后主线 CI 通过。源码中的群成员级风控修复已完成，但生产 Agent 仍运行旧版本。
- 主人恢复项目后报告 Higgs 再次无响应；关机已使本地 SSH 隧道失效，当前浏览器只保留无法实时请求的缓存登录页，因此尚不能把本次报告确认为 `KickedOffLine`、网络故障或 Agent 故障。
- 下一步先恢复此前获准的 SSH 只读上下文并做匿名六维检查；不得把未核实报告写成权威掉线事件。确认风控或踢线后只报告并等待人工判断，不自动重启或重复登录。
- 仅文档交接 PR #24 的首轮 CI 在晚间暴露两个 `today` 计划测试读取真实墙钟，导致当天剩余时间不足时失败；这不是群聊修复回归。测试已固定上海上午时间及对应 epoch，本地针对文件 10 项、Ruff、格式和完整 pytest（`271 passed, 4 skipped`）均通过，等待远端重跑。

## 节点 12：官方机器人创建与凭据私有落盘

- 2026-08-28 主人完成 QQ 开放平台实名认证并亲自选定机器人昵称与头像；官方机器人创建成功。项目记忆不记录 AppID、机器人账号、OpenID、截图内容或平台登录状态。
- 平台不保留旧 AppSecret 明文；经主人在动作时明确确认后生成新 AppSecret。凭据只在受控浏览器会话中读取，没有回显到聊天、终端输出、日志、Git 或本地临时文件。
- 经主人再次明确确认敏感传输后，将 AppID 与新 AppSecret 原子写入服务器 `/srv/secrets/higgs/higgs.env` 的既定环境变量；临时文件继承原所有者，最终权限为 `0600`。
- 服务器匿名验证确认两个凭据变量各恰好一份、文件权限正确，且 `R_AGENT_OFFICIAL_QQ_ENABLED` 未处于 true/1/yes/on。此次没有部署代码、重建或重启容器、打开官方通道、发送测试消息或修改 live 配置。
- 主人在动作时明确授权后，只从服务器私有配置读取主人 QQ 并直接登记为官方机器人测试用户；该标识未回显、未写入项目文件或临时文件。平台页面已显示一条可删除的测试用户记录。
- 平台开发设置确认 IP 白名单为空时不限制请求来源，该可选项不构成当前沙箱联调阻断。为本轮匿名校验生成的两个零字节标记均经宝塔明确的回收站确认流程移入文件回收站，原目录复核均不存在；未删除其他文件。
- 下一步仍需取得单独确认后才可部署已合并的官方适配器、私有绑定主人 OpenID 和开始主人沙箱私聊。72 小时在线与进程重启 Resume 验收尚未开始。

## 节点 13：官方部署预检与关机暂停

- 主人确认继续官方 QQ 沙箱后，本地再次通过完整 pytest（`271 passed, 4 skipped`）、Ruff、格式、秘密扫描、Shell LF 和发布包校验；提交 `d2d40a7e47618022e258d3a534f62aab68b04833` 的完整发布包与运行时补丁已生成在本地统一 `artifacts` 目录，均不含私有数据。
- 主人完成腾讯云 OrcaTerm MFA；只读 shell 探针成功。匿名基线仍为既有生产发布、NapCat healthy、Agent 因既有 QQ 离线状态 unhealthy。没有上传文件、激活发布、构建镜像、修改配置、重启容器或发送消息。
- OrcaTerm 网页文件管理器没有正确触发本地文件选择器；腾讯云实例文件管理已确认有独立上传入口，但在主人要求关机时尚未选择文件，因此服务器不存在本轮新发布包或补丁。
- 关键设计阻断已经明确：官方配置启用前强制要求主人 OpenID；平台测试用户列表不显示 OpenID，现有代码也没有安全自举机制。后续不得临时取消门控。应在禁用态发布后新增受治理的一次性捕获切片：仅在平台测试用户恰为主人一人的前提下、由运维显式启动、只接受首个 C2C 身份、绝不记录消息正文、原子写入 `0600` 私有配置、成功后立即退出并保持官方通道关闭；完成测试、PR/CI 和人工复核后方可运行。
- 关机续接点：重新登录腾讯云（必要时重做 MFA），从实例文件管理上传完整发布包并校验哈希；完成不可变激活、官方关闭态验证、Agent-only 构建/重建及 NapCat 不变性检查。之后再实现并审核一次性 OpenID 捕获，完成私有绑定后才进入主人沙箱 C2C 和 72 小时 Resume 观察。

## 节点 14：禁用态官方适配器生产发布

- 关机后恢复腾讯云会话，匿名基线确认生产仍为旧发布；NapCat healthy 且连续运行约 19 小时，Agent 因个人 QQ 权威离线 unhealthy。服务器到 GitHub 的只读查询无响应，有限等待后中止，没有后台任务或下载残留。
- 通过腾讯云实例文件管理上传本地完整 Git 归档，页面确认一项任务完成；服务器端 SHA-256 与本地发布记录完全一致。私有配置仍为 `0600`，AppID/AppSecret 各恰好一条，主人 OpenID 不存在，官方启用保持关闭；全程不回显标识或凭据。
- 原子激活不可变源码 `d2d40a7e47618022e258d3a534f62aab68b04833`，旧链接进入 `/srv/trash`；新 Agent 镜像以相同提交标签构建成功。主机没有 Python，直接脚本调用未产生配置变化；随后以新镜像临时运行既有原子配置脚本，私有环境备份进入 `/srv/trash`，镜像标签更新成功且未输出秘密。
- 只重建 Agent，命令显式使用 `--no-deps --no-build`。匿名前后比较确认 NapCat 容器身份与启动时间完全不变；未重启 NapCat、未重新登录、未发送任何测试消息。
- 部署后 12 个 SQLite 文件存在，Agent 使用新不可变镜像并正常运行；官方状态行数为零、近 10 分钟 fatal 与秘密标记均为零。个人 QQ 仍表现为 NapCat 容器健康、OneBot 可达、QQ 权威离线、账号匹配未知，因此 Agent 健康检查按设计为 unhealthy。
- 官方适配器与群成员级风控修复均已进入生产代码，但官方通道继续关闭。下一步必须先完成受治理的一次性主人 OpenID 捕获切片及本地测试、独立 PR/CI；捕获并私有绑定后，才可另行确认开启主人沙箱 C2C。

## 节点 15：一次性主人 OpenID 捕获代码完成

- 独立工作树与分支 `codex/higgs-official-owner-capture-20260828` 已建立，严格保持现有官方主通道关闭。新增独立 CLI 与服务器包装脚本，只有输入固定单测试用户确认短语后才能开始；包装脚本使用独占锁和 `docker compose run --rm --no-deps agent`，不重启常驻 Agent 或 NapCat。
- 捕获路径只接收 READY/RESUMED 后首个合法 C2C sender，群聊、未就绪、未知类型、scope 不匹配与后续身份全部丢弃。捕获过程不创建 `InboundEvent`、不记录消息 ID/正文、不发送回复，成功后立即停止 Gateway。
- 私有环境写入拒绝 symlink、非普通文件、超大文件、权限偏离、重复键、主人已存在、官方已启用和非沙箱状态；先创建 `0600` 私有备份，再以 fsync 和同目录 `os.replace` 原子绑定。任何失败临时文件只移入私有备份目录，不直接删除；最终再次证明官方仍关闭。
- 本地完整 pytest 为 `282 passed, 5 skipped`，Ruff、格式、Git Bash 语法、发布门和新增文件 `detect-secrets==1.5.0` 扫描通过。功能提交经 rebase 后为 `187a959`，已推送独立分支并创建 PR #25；该提交的两组 Ubuntu `Higgs CI / test` 均通过，合并状态为 clean，Windows 跳过的 POSIX 合约已由 CI 覆盖。
- 文档检查点提交 `36e936d` 后的两组 PR CI 均通过；PR #25 经人工验收合并为主线提交 `9cfbc69363008330d6b9bcbd9002c0aaa7bf2290`，合并后主线 CI 与 Dependency Graph 均通过。

## 节点 16：一次性主人捕获禁用态生产部署

- 从主线合并提交生成只含 Git 跟踪文件的发布包，本地与服务器端 SHA-256 完全一致；腾讯云文件管理确认一项上传任务完成，包内不含私有配置、登录状态或账号数据。
- 部署前匿名门控为 AppID 一条、ClientSecret 一条、主人 OpenID 零条、官方启用 false。原子激活不可变发布 `9cfbc69363008330d6b9bcbd9002c0aaa7bf2290`，旧 `current` 移入 `/srv/trash`；同提交标签的 Agent 镜像构建成功。
- 以新镜像离线运行既有原子配置脚本，私有环境先备份再更新不可变镜像标签且未打印秘密。只对 Agent 执行 `--no-deps --no-build` 重建；NapCat 容器身份与启动时间均未变化。
- 匿名验收确认 Agent running、发布与镜像匹配、捕获脚本可执行、主人 OpenID 仍为零条、官方启用仍为 false。真实捕获 Gateway 尚未启动，未读取或写入主人 OpenID，也未发送 QQ 消息；下一步需在动作时确认平台仍只有主人一个测试用户，再开启五分钟捕获窗口。

## 节点 17：官方捕获 Resume 现场诊断与修复中

- 主人在正确官方入口发送后，一次性捕获仍超时；三轮均没有身份写入、正文/消息 ID 日志或回复，官方通道保持关闭。平台在诊断会话早期显示在线，说明凭据、Gateway URL、READY 与基础 WebSocket 并非阻断点。
- 匿名 75 秒时序探针显示：2、10、25 秒 READY/authenticated 正常；首个 ACK 后的 45、75 秒 connected 与 ACK 仍存在，但 authenticated 已被清空且 event_seen 始终为 false。固定 SDK 1.2.2 在 op 9 清 session 后 graceful close，读取 loop 正常返回而没有进入异常重连；旧适配器也未立即清 connected，形成假连接。一次性捕获无 supervisor，因此无法像常驻进程一样纠正。
- 独立修复分支将捕获会话与生产 Resume 分离：每次捕获只清理独立私有存储中的本 App 记录并 fresh Identify，绝不触碰生产 Resume。有效 op 7/op 9 先发布 disconnected；session invalidation 同步清理 connected、authenticated、bot 身份和连接时间，匿名原因固定为 `session_invalidated`。
- 定向回归为 `29 passed, 1 skipped`，完整 pytest 为 `285 passed, 5 skipped`，Ruff、格式与发布门通过。当前 Windows 环境没有可用 Bash/WSL 发行版，发布脚本语法由 Ubuntu CI 复核。下一步执行 PR/CI、Agent-only 发布，再只进行一次正确官方入口捕获；未完成前不得开启正式官方通道。

## 节点 18：捕获 Resume 修复上线与有限重连监督

- Resume 隔离修复经 PR #27 全部 CI 及合并后主线 CI 通过，合并提交为 `fa62bebadadac727a9fd743feb290f2482dab676`；不可变发布仅切换 Agent，NapCat 匿名身份与启动时间保持不变。部署后官方仍关闭，主人绑定仍为空。
- 主人随后从官方入口发送，但捕获窗口结束后匿名权威配置仍为主人零条、官方关闭、私有权限正确；未保存消息正文、身份、消息 ID，也未发送回复。
- 根因进一步收敛为一次性捕获器没有运行适配器监督循环。SDK 在干净关闭读取后不会自行恢复；既有监督又只限制连续失败，短暂 READY 会重置预算，无法为五分钟临时登录提供绝对上限。
- 新分支 `codex/higgs-official-capture-supervisor-20260828` 为监督接口增加可选总重启预算；连续预算可在健康时重置，总预算永不重置。退避后先重新检查健康，已恢复则不执行多余重启。捕获器固定最多五次总重启，监督终止或异常均匿名 fail-closed，退出时取消监督并停止 Gateway。
- 回归覆盖总预算、健康竞态、非法预算与捕获任务生命周期。定向测试为 `33 passed, 1 skipped`，完整 pytest 为 `289 passed, 5 skipped`，Ruff、格式和发布门通过。当前仍只在本地，下一步是提交、PR/CI、Agent-only 发布与匿名不变性验收；完成前不再要求主人发送。

## 节点 19：官方 WebSocket 零事件结论与 Node 双传输转向

- 总重启预算修复经 PR #28 合并为主线 `b647b00db665a76d7ef6df7d85e88358b161061a`，并完成禁用态 Agent-only 生产发布。源码、栈与容器镜像一致；NapCat 未重启，官方开关仍关闭，主人 OpenID 仍为空。
- 平台在临时 Gateway 期间显示在线。匿名基础探针连续确认 Token、Gateway、READY、connected 与 authenticated 均成功；匿名事件探针保持 120 秒 `ready`，但 `on_message_event` 从未被调用。探针不记录身份、消息 ID、正文或登录状态，不发送任何回复。
- 兼容性探针把订阅从单一 `GROUP_MESSAGES` 扩展为 `GROUP_MESSAGES | DIRECT_MESSAGES` 后再次等待 120 秒，仍无事件。主人绑定没有发生，私有配置没有变化，官方通道始终保持关闭。这一结果把失败边界收敛到平台到 Python SDK 1.2.2 的事件投递，不再让主人重复试发同一路径。
- 平台页面确认接收方式为 WebSocket、测试用户仍存在、IP 白名单为空不限制调用、通知中心无异常；好友公开服务范围关闭时仍允许管理员和开发体验成员使用，因此不扩大公开范围或跳过沙箱治理。
- 腾讯官方现行 Node SDK 同时支持 WebSocket 和 Webhook，而旧 BotGo 已声明旧 WebSocket 路径进入淘汰。新建 `codex/higgs-official-node-transport-20260828`，转向最小、fail-closed 的官方 Node 协议边界；Python 继续拥有业务、owner/群门控、记忆、审计与发送决策。任何真实 sidecar 部署、Webhook 回调配置或官方启用仍走独立 PR、CI 和单独确认。

## 节点 20：官方 Node capture-only sidecar 离线实现

- 锁定官方 npm `@tencent-connect/qqbot-nodejs==1.0.4` 与完整 integrity，registry signature 验证通过，不跟随 `main`、不安装可选音频依赖。公开仓库快照为 `ca55d9c395b582b7fcfad0ec27209c35dd04e0b3`，但 npm 包 `gitHead=589597a6cb5a24dce8230ba53bfba5390e13c073` 在公开历史中不可达且包元数据与快照不同；已直接纳入 MIT 全文，在溯源差异解决或显式接受前维持诊断-only。使用精确 `1 << 25` 意图，避免 SDK 默认宽权限。
- sidecar 默认关闭且隔离运行：专用 `0600` Unix Socket、专用 `official-qq.env`、仅 egress、非 root、只读根、无 Docker Socket、无 Agent/NapCat 数据。Node 只负责协议；Python 仍是 owner/群门控、身份、记忆、模型、审计与最终发送决策的唯一权威。
- READY 身份不合法立即停止；READY 前事件/发送拒绝；仅接收 C2C 与群 `@`。默认 capture-only 队列只保留事件类型、私聊/群聊类别、接收时间与游标，不保留或返回任何身份、消息 ID、正文或附件元数据，且完全禁用发送。未来业务接入仍须严格 schema、请求指纹和幂等冲突拒绝，缺少平台消息 ID 为 `unknown`。
- 当前 SDK 无 heartbeat ACK 公共回调，内部重连也不满足生产总预算；所以第一切片只允许 1 到 300 秒有界匿名捕获，不持久化 Resume、不与 Python Gateway 并发、不直接开启正式官方通道。真实部署仍需单独确认。
- 本地 Node `14 passed`、Python `290 passed, 5 skipped`，Ruff/格式、发布门、npm registry signature 与 staged 秘密扫描通过。功能 `02826e0` 和文档 `ca5efd6` 经 PR #29 的 push/PR 两套 Python、Node/镜像/Compose CI 全绿后合并为主线 `0ec1b5b53c1ff14313147308e0cbf49623fa4524`，合并后主线两项 CI 再次通过。未部署、未真实捕获、未改变平台或生产开关。

## 节点 21：关机暂停与 Node 诊断恢复点

- 主人已在知晓 npm 1.0.4 公开溯源差异后允许一次 120 秒 capture-only 生产诊断。PR #30 已把前一合并状态写回权威记忆并合并为主线 `0ad270549f332edb99e58ea9f132b29bdea44c56`，主线 Python 与 Node/镜像/Compose CI 全绿。
- 腾讯云远程 Shell 当前断开并停在 MFA 微信扫码；主人要求关机，故本轮未完成验证、未执行服务器命令、未生成/上传新发布包、未创建私有配置、未构建或启动 sidecar，也未改变官方平台、Python 官方开关或 NapCat。
- 恢复后先完成 MFA 与匿名只读生产门控，再从 `0ad2705` 生成/校验发布包、锁定 Node 镜像 digest、私下建立 `0600 official-qq.env`。只允许 Node 单实例 capture-only READY 后让主人发送一次，匿名计数 120 秒后立即停止；成功才进入 Python UDS 正式接入新阶段，失败则回到平台授权和测试范围。
- NapCat 48 小时观察未达到稳定标准，过期观察自动化已删除；停止继续执行该观察任务。

## 节点 22：Node 官方 Gateway 真实捕获成功

- 已从主线 `358d9681f5539b6fbb204af28929500b06ea1a40` 生成并双端校验只含跟踪文件的发布包。生产只增加独立不可变 release、固定 digest 的 Node 镜像和 `0600` sidecar 私有配置；没有切换 Agent release，没有让 App 凭据进入聊天或发布包，也没有重建 NapCat。
- capture-only sidecar 真实达到 configured、connected、authenticated 与健康。主人从官方入口发送后，匿名 120 秒窗口返回 `event_seen=true`、数量 2、原因 `ready`；未保留身份、消息 ID、正文或附件，未调用发送接口。
- 捕获退出后 sidecar 自动停止。匿名复核为 Node running false、旧 Python 官方 enabled false、NapCat running true 且 healthy，满足同 AppID 不并发和个人 QQ 通道不受影响的门控。
- 该证据确认官方平台会向 Node SDK 1.0.4 投递真实事件；先前阻断限于旧 Python SDK 路径，不再继续让主人重复发送同类探针。新阶段在 `codex/higgs-official-uds-runtime-20260828` 实现 Python UDS 客户端、事件/身份/群白名单门控、被动回复和 UNKNOWN 回执；完成代码、测试、PR/CI 与默认关闭部署前不得开放正式回复。

## 节点 23：UDS 双进程正式运行时完成本地收束

- Node sidecar 现独占官方凭据、Gateway、心跳监督和私有 Resume；Agent 只通过只读挂载的 `0600` UDS 使用严格版本协议。Agent sidecar 模式无条件拒绝 App 凭据，官方摄取与回复由两个独立开关控制，回复默认关闭。
- 发送前必须确认固定 SDK 的当前 WebSocket、可观测且新鲜的心跳 ACK；provider 调用最多等待 10 秒。无平台消息 ID、异常或超时均为 `UNKNOWN`。协议错误直接 fail-closed，幂等冲突只拒绝该请求而不误杀整个通道。
- 重复投递不能重置已领取或过期的回复授权；Node 在入队前独立丢弃非主人私聊与未获准群事件，Python 再执行同一策略。SDK 精确版本在运行时断言，Node 基础镜像以完整 digest 固定。
- 新增完整 overlay systemd unit；启动前强制执行 UDS 与私有 session 目录的所有者和权限预检，重启后不会退回缺少 sidecar 的基础 Compose。生产切换审计发现旧 unit 是会停止整栈的 `RemainAfterExit` 服务，因此官方 unit 不得声明 `Conflicts=`；迁移只禁用而不停止旧 unit，再启用官方 unit，并以 NapCat 容器身份和启动时间前后不变作为硬验收。
- 本地 Node `25 passed, 2 skipped`，Python `304 passed, 5 skipped`，Ruff、格式和语法检查通过；真实 Linux UDS/session、镜像构建与 Compose 由 PR 的 Ubuntu CI 验证。
- 架构复核确认内存事件队列和回执与 SDK 先保存 sequence 后回调之间仍有崩溃丢事件窗口。因此下一步只允许回复关闭的 shadow：先走 PR/CI，再单独确认部署，验证 systemd 重启和 Resume。正式回复开关继续保持 false，直到协调持久化与崩溃恢复完成。
- 功能提交 `d7e71dd` 已进入 PR #32；分支 push 与 PR 的 Python、Node/镜像/Compose CI 全绿，Linux UDS/session 测试已执行。文档检查点尚待同一 PR 的最终 CI；生产未部署，官方回复保持关闭。
- 文档检查点 `ca72bbb` 的两套 CI 通过后，PR #32 已合并为主线 `fd60229b80878cacf0e516967cd02b9a1e1594fb`，合并后主线 CI 成功。生产环境没有随合并自动变化；下一门仍是需单独确认的回复关闭 shadow 部署。

## 节点 24：shadow 门控收敛与一次性 Node 主人绑定器

- 官方 systemd unit 原有 `Conflicts=higgs-existing.service` 会在迁移时触发旧整栈 unit 的 `ExecStop`，可能中断 NapCat。PR #34 已去除该关系并把迁移固定为仅 disable 旧 unit、不 stop；合并提交 `0a930e2fbf2bd2256430ce92ecdf04f196b06cdd` 及主线 CI 均通过。
- 生产端已构建该提交的不可变 release、Agent 与官方 sidecar 镜像。两次 shadow 尝试均因门控不满足而无损退出或回滚：旧 release、官方关闭态、sidecar 停止态和 NapCat 健康状态均保持不变，没有发送测试消息或触发 NapCat 重启。
- 匿名诊断将剩余阻断唯一收敛为主人官方 OpenID 缺失；其他私有配置、权限、App 凭据格式、Compose 与 runtime preflight 均通过。既有匿名 Node 捕获严格丢弃身份，因此不能事后恢复绑定值；禁止用 QQ 号或 AppID 替代，也禁止暂时取消 owner 门控。
- 新的一次性 Node 绑定器只在“平台测试用户恰为主人一人”的显式确认下运行，只接收 READY 后首个 C2C sender，并以 create-once、fsync、`0600` 文件直接落入私有挂载；不输出或记录身份、正文、消息 ID、附件与凭据，成功即停止 Gateway。
- 包装脚本保证无并发官方 Gateway、Python 官方关闭、目录权限/UID 正确；更新两份私有环境前创建 `0600` 备份，任一更新或后验检查失败即恢复，成功后把中间身份文件移入 `/srv/trash`，官方摄取仍保持关闭。
- 当前本地验证为 Node `29 passed, 2 skipped`、Python `305 passed, 5 skipped`，Ruff、格式、发布门、秘密边界、Shell LF 与 diff 检查通过。功能提交 `24296a1` 已进入 PR #35；push 与 pull request 两套 Python、Node/镜像/Compose CI 全绿，Ubuntu 已覆盖 Bash 语法和 Linux 零跳过测试。待文档检查点 CI 后合并，再部署绑定器并只请主人从官方入口发送一次；绑定成功后才进入回复关闭的 shadow 部署。

## 节点 25：主人私有绑定完成与官方 shadow 上线暂停

- PR #35 已在全部 CI 通过后合并为主线 `635045d30cf6f02970ddbbb464afd165f220459e`，合并后主线 Python 与 Node/镜像/Compose CI 继续全绿。
- 前一晚的绑定尝试安全超时；恢复会话并由主人扫码后，受控 Node 绑定器从首个合法官方 C2C 事件完成主人 OpenID 私有绑定。两份 `0600` 配置事务式更新，中间身份文件移入 `/srv/trash`；没有回显或记录身份、正文、消息 ID、附件或凭据，官方回复仍关闭。
- 同一主线提交的不可变 release、Agent 镜像与 official sidecar 镜像完成双端校验和生产切换。匿名部署回执确认 NapCat 未改变且 healthy、Agent running、sidecar healthy、官方摄取 enabled、回复 disabled、旧基础 unit disabled、官方 unit enabled。
- 这代表官方 Bot 已达到“平台在线、摄取开启、回复关闭”的 shadow 状态，不代表正式对话上线。协调持久化、崩溃恢复、systemd 重启 Resume、72 小时在线和真实回复均尚未验收。
- 主人要求关机时，进一步的匿名运行时核验命令仅停留在未执行输入行，随后已安全取消。续接先只读核验 release/镜像、唯一 Gateway、重启次数、sidecar health、`qq_official` transport 状态、reply=false 与 NapCat 不变性；再决定 Resume 测试，不得直接打开回复。

## 节点 26：shadow 重连竞态收敛与首 ACK 认证修复

- 匿名现场核验确认 release/镜像精确、唯一 official sidecar 当前在线且 ACK 新鲜，NapCat healthy、Agent running、reply=false；但 `qq_official` transport 已持续 `rejected/protocol_error`，业务摄取没有随 sidecar 恢复。官方 unit enabled/inactive，旧基础 unit disabled/active，systemd Resume 门尚未执行。
- 脱敏时序为 `pending/startup → verified/ready → pending/gateway_reconnecting（约 2.5 秒）→ rejected/protocol_error`。sidecar 自动恢复后保持健康数小时，Agent terminal failure 不会自愈。诊断未读取日志、聊天正文、身份、消息 ID 或凭据。
- 根因是 READY/RESUMED 与首个新 heartbeat ACK 之间的合法窗口被错误表达为 authenticated。修复新增 `heartbeat_pending`：身份校验与 session bot id 可先完成，但直到 ACK 可观测、session touch 成功后才公开 authenticated 和 `ready/resumed`；期间事件与发送拒绝，90 秒无 ACK 仍以 `heartbeat_ack_timeout` fail-closed。
- 独立工作树 `Higgs-wt-official-heartbeat-auth`、分支 `codex/higgs-official-heartbeat-auth-20260829` 已完成本地代码与回归。Node `30 passed, 2 skipped`，Python 定向 `11 passed`、完整 `306 passed, 5 skipped`，Ruff、格式、Node 语法与 diff 检查通过。下一步是发布门、秘密扫描、提交、PR/Ubuntu CI；全绿前不部署、不重启生产，也不打开回复。

## 节点 27：首 ACK 修复合并、生产发布与真实 Resume 验收

- 首 ACK 修复连同回归和匿名记忆由 PR #36 合并为主线 `f18ff1b8b4a86845316f960fdb7b8a350e5a2eec`。PR 的两组 Python 与两组 Node/镜像/Compose CI 全绿，合并后主线 Python 与 Node CI 再次通过；没有直接推送 `main`。
- 只含 Git 跟踪文件的发布包为 448270 字节、263 个归档成员，本地与服务器 SHA-256 完全一致。首次直接执行激活脚本因归档内脚本非 executable 以 126 安全退出，未产生版本、配置或容器变化；随后显式经 `bash` 调用同一脚本，成功原子激活不可变主线 release，旧 `current` 进入 `/srv/trash`。
- 新 Agent 与 official sidecar 镜像使用同一 40 位主线标签构建成功。私有 `stack.env` 在 `/srv/trash` 创建 `0600` 备份后原子更新；仅依次重建 official sidecar 与 Agent。匿名前后比较确认 NapCat 容器身份、启动时间和 health 完全不变，未重启、未重新登录、未发送测试消息。
- 现场切换脚本曾因在循环/条件上下文依赖 `set -e`，没有按预期把一次旧的 `rejected/protocol_error` 读取当作失败；该次回执不能作为成功证据，后续运维脚本不得用隐式 `errexit` 代替显式返回码。独立后验核验最终确认新 sidecar healthy、零重启、connected/authenticated、ACK 新鲜，原子 session 真实以 `resumed` 恢复；Agent 将持续约十小时的旧 `protocol_error` 区间关闭并进入 `verified/resumed`，身份匹配为真。
- 官方回复保持 false，且同 AppID 只有一个 Node Gateway。个人 QQ 当前为 `rejected/get_status_offline`、权威在线 false、身份匹配未知、无新的 kick reason；因此 Agent 综合 Docker health 仍 unhealthy，不能据此否定已独立验证的官方 transport。
- systemd 尚未执行 `restart`：官方 unit enabled/inactive，旧基础 unit disabled/active；官方 unit 的 `ExecStop` 会停止整栈，`ExecStart --wait` 又会受个人 QQ 离线的 Agent health 牵连。下一步先用独立 PR/CI 建立不影响 NapCat 的官方 Resume 生命周期入口，并实现事件/回执协调持久化；两者完成前不得开启正式回复。

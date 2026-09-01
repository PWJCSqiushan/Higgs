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

## 节点 28：sidecar 入站与发送状态协调持久化完成本地收束

- 新建独立分支 `codex/higgs-official-durable-delivery-20260829`。full-mode Node sidecar 新增专用私有 `delivery-state.json`，以临时文件、fsync、原子 rename、目录 fsync 和 `0600/0700` 权限门保存未确认事件、被动回复授权领取及发送回执；结构、owner、symlink、大小、权限、容量任一异常均匿名 fail-closed。capture-only 仍不保留身份或正文。
- UDS hello 增加匿名事件基准游标，新增 generation 绑定的逐条 ACK。Python 只有在 handler 正常返回后 ACK 并推进游标；异常时保留事件，Agent 重启从 ACK 游标续读，sidecar 重启则只重放尚未确认事件。
- 授权领取现在同时绑定完整请求指纹。首次领取先落盘再调用平台；若 sidecar 在平台调用边界崩溃且没有最终回执，重启后返回 `UNKNOWN` 而不是再次发送。已落盘回执跨进程复用，冲突请求继续拒绝。
- 本地验证为 Node `31 passed, 5 skipped`、Python 定向 `12 passed`、完整 `307 passed, 5 skipped`，Ruff、格式、Node 语法、release gate 与 `git diff --check` 通过。功能提交已进入 PR #38；push 与 pull request 两组 Python、Node/镜像/Compose CI 全绿，Ubuntu 零跳过验证了权限、symlink、原子重载、镜像与 Compose。尚未合并或部署，生产 reply=false。
- sidecar 层完成不代表端到端 exactly-once。Agent 当前 debouncer 和业务处理仍是内存态；下一步必须建立 Agent 持久状态机与故障注入，之后才能申请真实被动回复验收。

## 节点 29：协调持久化合并并完成 reply=false 生产发布

- PR #38 已合并为主线 `e02bbc85d04683af7e8854521117c9152ef47d96`，合并后主线 CI run `33254680991` 的 Python 与 Node/镜像/Compose 任务均通过；没有直接推送 `main`。
- 发布包仅含 Git 跟踪文件，共 455927 字节，SHA-256 为 `99202cf6add2d6e9939315c14e14bf6d28b99dac18bbdffb9f1a23081262e62c`。上传后服务器端再次核对大小与摘要，未携带任何凭据、QQ/OpenID、聊天正文或登录状态。
- 第一次尝试在 Compose build 缺少 official profile 时于容器变更前停止；第二次在 profile 外执行 `compose ps` 后触发受控回滚，旧 release、私有镜像标签和运行容器均恢复。修正为所有 Compose 命令统一携带 profile 后，复用已构建镜像完成最终切换。
- 最终匿名回执为：release 与 Agent/sidecar 镜像精确匹配；sidecar healthy、零重启、单 Gateway；Agent running；官方 transport `verified/resumed`、authenticated、身份匹配、心跳新鲜；reply=false。NapCat 容器身份、启动时间和 health 未改变，全程没有自动重登、重启 NapCat 或发送测试消息。
- 私有持久化目录的 owner/mode 门控通过。当前没有待持久化状态，因此 `delivery-state.json` 尚未物化并记为 armed；首个入站事件、授权领取或回执会以 `0600` 原子创建。不得用文件暂不存在误判为部署失败。
- 官方 shadow 连续观察从 2026-08-29 21:53（Asia/Shanghai）重新开始。Agent 端 quiet-window、模型生成和业务副作用仍未持久化，正式回复必须继续关闭；下一切片是 Agent 持久处理状态机、重启故障注入和跨进程 UNKNOWN/幂等验收。

## 节点 30：Agent 官方消息持久状态机完成本地收束

- 新分支 `codex/higgs-agent-durable-processing-20260829` 增加第 13 个运行时库 `official_processing.sqlite`。官方事件只有在 Journal 与 Agent durable queue 均提交后才允许 sidecar ACK；源事件重复投递不重复建批，Journal 已写但 queue 未写的崩溃窗口可由重投补齐。
- 持久 quiet-window 按会话与发送者隔离，状态为 `pending/preparing/prepared/sending/finalizing/complete`。模型生成的准确文本在发送前落盘；发送边界崩溃后只用同一文本、同一 reply message 和同一幂等键恢复，不重新生成。UNKNOWN 仍为失败审计，绝不伪报 SENT。
- 风险账本与非主人会话熔断用哈希化幂等键复用活跃 reservation/来源计数，避免 prepare 崩溃造成永久重复占额或误触发冷却。审计与会话记录的原有唯一键支持 finalizing 重放；完成项按 journal retention 清理并纳入一致性备份。
- reply=true 现在强制要求 durable Node sidecar，直连 Python SDK fail-closed。sidecar ACK 提交后 HTTP 响应若丢失，Agent 会重新读取权威 ACK cursor 后续跑，避免 `invalid_cursor` 终止摄取。
- 官方 MVP 明确只开放普通对话和主人 `/higgs status`；日计划、提醒及其他 owner 命令在副作用前拒绝。输出在持久化前收敛到 2000 字符协议上限。
- 本地 Python `320 passed, 5 skipped`，Node `31 passed, 5 skipped`；Ruff、格式、Node 语法、registry signature、发布门、秘密边界、Shell LF 与 diff 检查通过。尚未提交、PR、CI 或部署，生产继续 reply=false；下一步是独立 PR/Ubuntu 零跳过，再申请 reply=false 部署和重启恢复验收，最后另行确认真实回复开关。

## 节点 31：PR #40 首轮全绿与故障审计补强

- Agent 持久处理功能以本地提交 `33b34eb`、等价远端提交进入 PR #40；首轮 push 与 pull request 两套 Python、Node/镜像/Compose CI 全绿，分支可合并。生产尚未改变，reply 仍为 false。
- 上线前独立故障审计发现并修复两项 P1：不可恢复的 sidecar 发送拒绝现在收敛为终态 `FAILED`，不会让过期被动授权无限重试并永久占用风险预留；完成批次清理时为每个源消息留下内容无关的 SHA-256 tombstone，长停机后上游重投不能产生第二次回复。
- 新增真实风险账本与最终落库测试，证明 provider `UNKNOWN` 后处理状态完成、风险结果为 unknown、审计与会话均为 send_failed 且不再发送；prepare 在 reservation 后崩溃允许重新生成模型文本，但只复用一条 reservation，平台发送边界仍保持单次。
- 新增 SQLite enqueue 故障注入和监督循环 ACK 响应丢失恢复测试；新增 Linux `SecureDeliveryStore` 真 claim/receipt 进程替换测试，分别要求预领取无回执时 provider 调用为零、已有回执时跨实例总调用为一。Windows 本地按平台约束跳过，必须由 PR Ubuntu CI 零跳过解除。
- adapter 纵深门控补齐：公开发送接口自身检查 reply 开关；直接构造 sidecar 配置也拒绝 Agent 内 App 凭据和缺失 owner。当前本地 Python `330 passed, 5 skipped`、Node `31 passed, 7 skipped`，Ruff、格式、Node 语法与发布门通过；修正尚待提交并更新 PR #40。
- 用户已明确允许上传和部署。本轮授权只用于 PR 合并后的 reply=false 不可变生产发布与匿名恢复验收；不得据此直接打开真实回复。reply=true 仍需 Linux CI、reply=false 生产验收及跨语言发送边界证据后再单独确认。

## 节点 32：Agent 持久处理发布与双通道 healthcheck 修复中

- PR #40 已合并为主线 `9e55b8293a45feac3d89c8b5f32f1d94c9077185`；合并后 CI run `33259705508` 两项任务通过，Linux 对权限、UDS 和真实进程替换测试零跳过。发布包为 470185 字节、267 个成员，双端 SHA-256 一致，不含凭据、身份、聊天正文或登录状态。
- 首次执行因归档刻意不保留 executable 位，在调用激活脚本前安全退出；显式用 Bash 调用后完成不可变 release 与两镜像切换，只重建 official sidecar 和 Agent。匿名后验确认 sidecar healthy、零重启、单 Gateway，Agent durable 库已创建，reply=false；NapCat 容器仍 running/healthy、零重启且未参与重建。
- Agent Docker health 未通过不是官方 Gateway 故障，而是基础探针强制要求个人 QQ 权威在线。现场只有 `get_status_offline`、OneBot 可达、账号匹配未知，没有账号不匹配证据；禁止自动重启或反复登录 NapCat。
- 新分支 `codex/higgs-dual-channel-health-20260830` 让 official overlay 覆盖 Agent healthcheck，移除 `--require-qq-online`，仍检查新鲜心跳、OneBot 可达和 NapCat 容器 marker。定向测试 `6 passed`，Ruff/格式通过；完整 Python `330 passed, 5 skipped`，Node `31 passed, 7 skipped`。待 PR/Ubuntu CI、合并与只重建 Agent 的生产验收后，再单独申请开启真实回复。

## 节点 33：双通道健康修复合并并通过 reply=false 生产门

- PR #41 的 push 与 pull request 两组 CI 全绿后合并为主线 `a0f32c49db88318c696f22b4b9d345312557f465`；合并 tree 与本地 `330 passed, 5 skipped`、Node `31 passed, 7 skipped`、Ruff、格式、秘密扫描、Shell LF 和发布门所验收 tree 一致。
- 完整 Git 发布包在本地生成并通过门禁，但 OrcaTerm 文件选择器不可用且完整分块传输超过平台等待上限，未完成的归档没有被执行。生产改为克隆上一已验收不可变 release，只替换本次唯一运行时差异 `compose.official-qq.yml`；overlay 在本地和服务器以同一 SHA-256 校验，新目录继续不可变。GitHub 合并提交是测试和文档权威，该最小运行目录不冒充完整 Git 归档。
- 部署只强制重建 Agent。受控脚本要求 Agent 90 秒内达到 healthy、reply=false、NapCat 与 official sidecar 的容器身份/启动时间/重启计数前后一致，否则恢复旧 `current`。本次部署与独立验收均成功；没有重启 sidecar、重启或重登 NapCat，也没有发送测试消息。
- 最终匿名状态：Agent healthy、official sidecar healthy、官方 Gateway 单实例、`qq_official` 为 `verified` 且连接/认证/身份匹配/新鲜健康回执均通过、reply=false；NapCat 容器自身运行健康但个人 QQ 在线状态仍与官方通道独立。
- 下一门是主人单独批准官方被动回复 true。批准前不得修改私有回复开关；批准后只重建 Agent，并只让主人从官方入口发送一条测试消息，验收真实回复及 durable processing/UNKNOWN/幂等审计。提醒仍留在 NapCat，禁止跨通道透明故障切换。

## 节点 34：官方被动回复已开启，真实消息验收待执行

- 主人单独明确批准开启官方被动回复并只重建 Agent。切换前确认官方 transport verified、单 Gateway、Agent/sidecar/NapCat 容器健康，且 `official_processing.sqlite` 的非完成批次为零，避免 shadow 历史消息在开关打开后被恢复发送。
- 私有 `higgs.env` 先以 `0600` 备份到 `/srv/trash` 的 `0700` 目录，再以 fsync 和原子 replace 把回复开关从 false 更新为 true；没有回显凭据、身份或聊天数据。部署脚本带显式回滚，后验任一失败会恢复配置并重建旧 Agent。
- 生产只重建 Agent。最终匿名状态为 Agent healthy、`R_AGENT_OFFICIAL_QQ_REPLY_ENABLED=true`、官方 transport verified、Gateway 单实例；official sidecar 与 NapCat 的容器身份、启动时间和重启计数未变，全程没有重启/重登 NapCat，也没有运维侧测试消息。
- 当前正式状态是“被动回复已开启、首条真实消息尚未验收”。下一动作仅由主人从官方入口发送一条“测试”；随后匿名核对 durable batch 终态、发送结果类别、风险/审计收敛和 provider 调用不重复。UNKNOWN 不得自动重发，提醒仍由 NapCat 承担。

## 节点 35：超长官方消息标识根因确认与修复待 PR

- 主人连续两次从官方入口发送测试消息。两条消息均被唯一 Gateway 接收并由 durable processor 收敛为 `complete/model_failed`；平台发送接口没有被调用，活动批次为零，因此不存在 UNKNOWN、重复发送或旧批次重放风险。Agent、official sidecar、NapCat 均保持 healthy，官方 transport 持续 verified，reply=true。
- 匿名固定模型探针确认生产模型配置、鉴权、网络和基础生成正常。进一步的内容无关结构检查显示，测试正文仅 2 个字符，但官方平台消息标识较长，使旧 `channel:account_id:message_id` 召回审计键达到 150 字符，超过 `RecallLedger` 的 128 字符上限；召回审计未落库，请求也从未到达模型服务。这是两次 `model_failed` 的确定根因。
- 独立分支 `codex/higgs-official-recall-id-fix-20260830` 将召回 `turn_id` 改为带版本前缀的 SHA-256 固定长度键。它仍绑定 channel、account 和 message，保持去重与冲突检测语义，同时不再泄露平台标识，也不会受不同平台 ID 长度影响。新增 160 字符平台消息 ID 回归，证明键长固定为 77、原标识不出现在审计键且 owner recall 可读取。
- 本地 release gate、秘密边界、Shell LF/语法、Ruff、格式均通过；Python 完整 `331 passed, 5 skipped`，Node `31 passed, 7 skipped`（Windows 既有 Linux 专用跳过）。下一步是提交独立 PR、等待 Ubuntu CI 零跳过，合并后生成不可变发布并只重建 Agent；旧失败批次保持终态，不得重放。生产修复部署后再请主人发送一条新测试完成真实 SENT 验收。

## 节点 36：官方 QQ Bot 首次真实回复通过并进入稳定观察

- 固定长度 recall turn ID 修复经 PR #44 的四项检查全绿后合并为主线 `6a95312bc3bf935295f9d9ff199c577baa7ae31d`，没有直接推送 `main`。完整 Git 发布包为 475980 字节、267 个成员，SHA-256 为 `58723a985a1f3775669126395e0efe39b0cd093069b24fd4d6f8a6f8a2ac0551`。
- 生产以不可变 release 激活该主线，只构建和重建 Agent。后验确认 reply=true、官方 transport verified、单 Gateway、活动批次为零；Agent、official sidecar 和 NapCat 均 healthy，sidecar 与 NapCat 未被重建或重启。
- 主人在部署后发送一条新的官方 C2C 消息。匿名验收显示 batch 终态为 `complete`，处理生命周期完成预期的三个转换节点，发送结果和最终审计均为 `sent`，活动批次回归零。整个过程未读取、输出或记录任何身份、消息正文、平台消息 ID 或回执 ID。
- 旧的两个 `complete/model_failed` 批次保持终态且未重放。这次成功证明了官方入站、持久队列、模型生成、平台发送、幂等回执和审计收敛的真实端到端链路；official owner C2C 被动回复 MVP 现已上线。
- 后续保持双通道边界：提醒继续由 NapCat 发送，不进行跨通道自动转发或透明故障切换。先完成 72 小时官方通道稳定性观察，再以一个测试群、仅 `@` 触发的策略扩大灰度；不将本次成功等同于 72 小时稳定性验收。

## 节点 37：72 小时官方通道观察开始

- 窗口为 2026-08-30 08:09:26 至 2026-09-02 08:09:26（Asia/Shanghai）。当前任务已创建 `higgs-72` 心跳观察，每 6 小时只读检查一次，截止后产生最终结论、通过 72 小时文档 PR 收敛并暂停自动化。
- 72 小时脚本仅读取匿名容器状态/重启计数、Gateway 数量、reply 开关、`transport.sqlite` 匿名状态/转换和活动 durable 批次；SQLite 强制 `mode=ro` 和 `query_only`。禁止日志、身份、正文、平台消息/回执 ID、凭据、测试消息、容器变更或登录动作。
- 启动基线完整通过：三容器 healthy/零重启，单 Gateway，reply=true，官方 transport verified 且连接、认证、身份匹配和健康新鲜度通过，活动批次为零。启动后数分钟内出现一次短暂重连并以 `ready` 恢复；容器未重启，没有 rejected 或致命转换。该转换不重置窗口，将纳入最终证据。
- 本窗口结束前不修改生产群白名单。观察期内先离线完成一次性测试群 OpenID 绑定、owner 触发确认、双层白名单与群用户身份隔离回归；全绿后也只是代码就绪，生产启用必须等待 72 小时结论和新的人工验收。
- 观察脚本已在生产环境以只读方式真实执行并通过；本地 release gate、秘密边界、Shell LF、Ruff 与格式通过，Python `332 passed, 5 skipped`，Node `31 passed, 7 skipped`。本分支只提交脚本、CI 语法门、静态只读边界回归和观察起点文档，不修改生产状态。

## 节点 38：测试群双阶段绑定与激活代码完成

- 一次性 Node 群绑定器只在两个显式确认（唯一测试群、72 小时观察通过）后运行。它只接受认证后的 owner `GROUP_AT_MESSAGE_CREATE` 与固定短语，直接把候选群 OpenID 写入私有 `0600` create-once 文件；不输出身份、正文、平台消息/回执 ID、附件或凭据。
- 绑定阶段暂时用唯一 capture-only Gateway 替换 sidecar，完成后恢复原 sidecar并等待 transport verified；Agent 与 NapCat 不重建。候选不会自动进入生产白名单，失败文件只移入 `/srv/trash`。
- 独立激活脚本再次要求 72 小时确认，把两份私有配置备份到 `/srv/trash` 后原子写入 Agent/sidecar 双层 allowlist，仅重建 sidecar 与 Agent；运行时值、单 Gateway、reply、transport、活动批次和 NapCat 不变性任一失败都会回滚。
- 协议和业务仍只接收群 `@` 事件，普通群消息不进入业务与记忆。官方群成员按通道和 member OpenID 隔离，不自动跨到个人 QQ、owner 或其他成员 principal。
- 本地 Python `335 passed, 5 skipped`，Node `36 passed, 7 skipped`；Ruff、格式、Node/远端 Bash 语法通过。release gate 以 249 个跟踪文件、272 个归档成员通过，秘密边界与 Shell LF 干净。PR #47 首轮四项 CI 全绿，增强后尚待重新推送复验。代码未部署；生产群白名单保持为空，必须等待固定 72 小时窗口完成后再决定绑定与灰度。

## 节点 39：主人命令与官方主动提醒关机检查点

- 测试群 PR #47 最终合并为主线 `b72ad8a4fab1f1ad8d261287105e6797a910b9bf`，合并后主线 CI 通过；生产群仍受 72 小时门禁约束，没有激活。
- 新分支 `codex/higgs-official-owner-reminders-20260830` 开始离线迁移主人功能。提醒目标从隐式 origin 改为确认哈希覆盖的显式 channel、surface、Bot account 与 target；官方群仅允许主人 C2C 创建并回投同一 owner OpenID。
- Node sidecar 与 Agent 增加默认关闭的独立 proactive 能力。主动请求不携带 reply message ID，只允许 owner C2C；sidecar 在 provider 边界前持久写入请求指纹与 UNKNOWN claim，崩溃后不得重发。该实现依据腾讯官方 `openclaw-qqbot` 主动发送和提醒代码，但尚未真实启用或发送。
- 主人私聊命令先开放严格 allowlist 的只读状态/记忆查询及提醒管理；群内主人命令与其他变更性运维命令继续拒绝。日计划仍未迁移。
- 暂停前定向门禁为 Python `67 passed`、Node `37 passed, 8 skipped`，Ruff 与 Node 语法通过。尚需完整测试、Linux 零跳过、release gate、秘密扫描、PR/CI；生产 proactive 配置仍为 false，没有部署或容器变化。

## 节点 40：主动提醒本地实现与迁移边界收束

- 旧提醒迁移改为版本化绑定：升级前已确认的 OneBot version 1 记录继续使用原审批哈希且只能投递到 `qq`；任何 version 1 官方目标都会失败关闭。新记录统一为 version 2，审批哈希覆盖通道、会话面、Bot account 与 target，避免升级静默取消既有提醒，也禁止旧审批跨到 OpenID。
- 官方主动发送保持 Agent/sidecar 双开关默认 false，只允许 owner C2C。Sidecar 在平台调用前持久 claim 为 UNKNOWN；崩溃或响应不确定时同一幂等键不得再次调用 provider。被动 reply authorization 与 proactive claim 分离，群主动发送仍禁止。
- 官方 owner C2C 已离线开放 help/status/server status/risk、提醒管理和只读记忆 allowlist；官方群命令和其他变更性运维能力继续拒绝。日计划、跨通道主动迁移和完整主人功能仍属后续阶段。
- 新增受 72 小时门禁约束的主动发送激活脚本：双私有配置原子变更、`/srv/trash` 可恢复备份、只重建 sidecar/Agent、单 Gateway/transport/批次/schema 后验和 NapCat 不变性验证，失败时双配置与双服务一并回滚。
- 本地完整 Python 为 `342 passed, 5 skipped`，格式修正后定向 `35 passed`，Ruff 检查通过；Node `37 passed, 8 skipped` 且语法通过。Windows 没有 Bash，POSIX 与新 Shell 语法必须由 PR Ubuntu CI 零跳过/`bash -n` 收口。生产未改变、未发送消息，proactive 双门与测试群白名单继续关闭。
- 功能提交已进入 PR #48；首轮 push/PR 两套 Python 与 Node/镜像/Compose CI 四项全绿，Ubuntu 验证 Shell 语法、Python 零跳过和 Node 真实 POSIX 持久化。当前仅追加 CI 证据并等待复验；即使合并也不扩大生产授权。

## 节点 41：主动提醒合并与官方主人日计划离线完成

- PR #48 复验全绿后合并为主线 `2f22dd54f32ee41f76d193d77076d01cd47ded9f`，合并后主线 CI run `33292488279` 成功；生产没有部署，proactive 与群白名单保持关闭。
- 新分支 `codex/higgs-official-daily-plan-20260830` 将今日计划开放给官方 owner C2C：命令和自然语言草案沿用版本化计划、确定性求解、地图单次授权与任务状态机；官方群和非主人拒绝。
- `shadow` 可在主动发送关闭时使用；官方 `live` 确认必须由 Agent proactive 门放行，否则计划不激活、提醒不创建。启用后的总览/T-10/T0 节点全部是显式 version 2 官方 owner 私聊绑定，不会转到 OneBot。
- 提醒创建进一步校验官方 canonical origin 与 delivery Bot/owner 完全一致，防止跨 Bot OpenID 复用。OneBot 既有 `create_scheduled` 调用继续兼容。
- 本地 Python `345 passed, 5 skipped`，Ruff 通过；Node `37 passed, 8 skipped`。尚待 release gate、提交 PR 与 Ubuntu 零跳过；生产状态未改变。
- 功能提交 `5e1b8ed` 已进入 PR #49，首轮 push/PR 四项 CI 全绿，Ubuntu Python 与 Node POSIX 项零跳过，镜像/Compose 通过。仅追加 CI 证据后复验，生产仍未改变。

## 节点 42：日计划与提醒 prepare 崩溃重放阻断已修复

- PR #49 已复验全绿并合并为主线 `4827add4edc0a6847b66290d69420be243e9a083`，合并后主线 CI run `33293097006` 成功；生产没有部署该功能，proactive 与群白名单仍关闭。
- 上线前审计确认 `OfficialDurableProcessor` 会把中断的 `preparing` 批次恢复后重新执行 reply prepare，而日计划/提醒在 prepare 内含数据库副作用。若进程恰在业务库提交后、prepared reply 提交前中断，旧实现可能产生重复草案、版本或节点提醒。该风险在生产暴露前被阻断，后续变更性主人命令迁移暂停到本修复完成。
- 计划草案新增内容无关的 64 位 SHA-256 请求键与 partial unique index；旧库在线补列，新建与每日限额在单一 `BEGIN IMMEDIATE` 中执行。同事件同参数返回既有计划，参数漂移失败关闭。自然计划和提醒的相对时间以事件发生时间为锚，不再依赖重放时墙钟。
- 地图授权、精确版本确认、任务终态、计划取消和替换改为幂等转换。自然提醒按原会话与 source message 复用；日计划总览/T-10/T0 使用稳定内部来源键，创建、确认和 reminder link 可在部分成功后重放修复而不重复记录。
- 故障注入覆盖“计划已确认且第一个提醒已创建后中断”：恢复后既有 job ID 保留、其余节点补齐、来源键无重复、`plan_confirmed` 事件仍只有一条。另覆盖草案/提醒请求键冲突、同事件双准备、确认与任务转换双执行。
- 当前本地完整 Python `349 passed, 5 skipped`，Ruff 格式/检查、release gate、秘密边界和 Shell LF 通过；Node 语法及 `37 passed, 8 skipped` 通过。
- 修复提交 `bb965cf` 已进入 PR #50；首轮 push/PR 四项 Ubuntu CI 全绿，Python 零跳过、Node POSIX/进程替换、Shell 语法、npm 签名、镜像与 Compose 均通过。只追加本 CI 证据并等待复验，尚未合并或部署；固定 72 小时生产观察和既有生产配置均未改变。

## 节点 43：主人低风险变更接入事件级持久治理

- PR #50 已复验全绿并合并为主线 `9f2c2f42277fb5de0dc6a59c537765e55a1efddd`，合并后主线 CI run `33294165462` 成功；生产未部署，72 小时观察与现有开关均未改变。
- 新分支 `codex/higgs-official-owner-mutations-20260830` 复用 `tool_audit.sqlite` 为官方 owner C2C 变更建立执行前持久领取、参数指纹、冲突拒绝和结果回放边界。同一平台事件只能执行一次；领取后崩溃保持 `UNKNOWN`，不会自动再次执行。
- 当前只迁移普通回复开关、关键词、频率、连续消息等待、记忆自动审核/观察重试/候选回填/状态审核、备份和提醒状态操作。白名单与自然触发群涉及个人 QQ 数字身份，继续从官方命令边界拒绝；官方群仍须经过独立绑定与 72 小时门禁。
- 持久回执只保存固定、无内容结果摘要，不保存命令参数、提醒正文、记忆内容、身份或平台消息标识。旧路由的“操作未执行”明确落为失败，不再伪报成功。
- 本地故障覆盖成功回放、参数冲突、预领取崩溃、真实配置与记忆状态重复执行以及失败终态；Python `368 passed, 5 skipped`，Node `37 passed, 8 skipped`，Ruff、格式、发布门、秘密边界、Shell LF 和 diff 检查通过。
- 功能提交 `34a7039` 已进入 PR #51；push run `33294949353` 与 pull request run `33294958839` 四项 CI 全绿，Ubuntu Python 零跳过并通过 Node POSIX/UDS/进程替换、Shell 语法、npm 签名、镜像和 Compose。当前仅追加 CI 证据并复验，尚未合并或部署。

## 节点 44：官方热配置与双通道状态语义对齐

- PR #51 已复验全绿并合并为主线 `ec7929705627d363f59dd79f9b01005174a6bec0`，合并后主线 CI run `33295067908` 成功；生产未部署，72 小时观察与既有开关未改变。
- 新分支 `codex/higgs-official-parity-20260830` 修复 `/higgs debounce` 的官方运行时差距：官方 durable quiet-window 改从加锁的 live control 读取，启动时保持 private/group 各自配置，热更新后与 OneBot 同步立即生效。
- `/higgs status` 现在匿名分列 OneBot 与官方 transport；官方群只展示 Gateway、鉴权在线、Bot 身份匹配、健康回执和时长，不复用 NapCat 标签，也不输出身份或平台标识。官方未启用时不初始化仅供展示的状态行。
- README、聊天命令和双通道路线已更新为真实现状：主人 C2C 被动回复已验收，测试群与 proactive 仍需 72 小时和单独生产确认；Node sidecar 独占生产 Gateway，Python SDK 仅为隔离兼容路径。
- 本地 Python `369 passed, 5 skipped`，Node `37 passed, 8 skipped`，Ruff、格式、staged release gate、秘密边界、Shell LF 和 diff 检查通过；生产无变化。
- 功能提交 `bf93a7d` 已进入 PR #52；push run `33295771506` 与 pull request run `33295778538` 四项 CI 全绿，Ubuntu Python 零跳过并通过 Node POSIX/UDS/进程替换、Shell 语法、npm 签名、镜像和 Compose。当前仅追加 CI 证据并复验，尚未合并或部署。

## 节点 45：Persona V2 代码完成并保持生产关闭

- 以远端 `main` 的 `56b85adf1d844f545152cdce31dbcb8ef4f40f3d` 为基座建立 `codex/higgs-persona-v2-20260830`。版本化 Persona Bundle 把雪豹 Higgs 的不可变身份与价值、自然沉浸风格和摄影/技术/长追问范例分离，并以 manifest、逐文件 hash、聚合 hash、链接和大小校验防止静默漂移。
- V2 加载顺序为 `R_AGENT_PERSONA_DIR`、旧 `R_AGENT_PERSONA_FILE`、旧内联人格和打包 bundle；只有 owner 官方私聊且 `R_AGENT_PERSONA_V2_ENABLED=true` 时启用。安全与权限规则在系统上下文中先于人格，聊天不得改变身份、主人关系、权限或核心价值。
- PersonaGuard 只处理身份矛盾、AI/客服腔等高信号出戏问题，技术回答不因角色化被改写。违规最多一次有界模型修复，失败后确定性降级；没有递归生成或未界定的额外模型调用。
- 50 条自动回归覆盖身份、追问、技术、摄影、长跑、天体物理、情绪、角色诱导和提示注入。人工四维评分模板保持 unscored，真实 `>=4/5` 仍是后续 owner 20 轮验收门，不把样例自评分当验收证据。
- 当前本地完整 Python `389 passed, 5 skipped`，Node `37 passed, 8 skipped`，Ruff、格式、release gate 和 diff 检查通过。生产开关、服务器配置、容器、NapCat 和消息流均未改变；下一步提交接线检查点、推送阶段分支、创建 PR 并等待 Ubuntu CI。

## 节点 46：Higgs 自我记忆 v4 完成离线接线

- 自我观点与用户个人事实已拆分：`persona:higgs` 只承载 `self_stance` 和去标识化 `adopted_idea`，使用现有 `memory.sqlite` 的 v4 伴随表，数据库仍为 13 个。代码部署默认不迁移；schema v4、shadow、摄影观点导入和 autonomous-low-risk 分别需要独立生产确认。
- 只有最终 `SENT` 且含平台消息标识的回复进入自我观察。off 模式不记录新观察；shadow 禁止自动激活；自主模式也仅允许置信度至少 0.94 的低风险、非敏感、无需核验、无核心影响且无冲突观点自动生效。
- 候选提取采用严格 JSON 与固定 lane，不接受身份、主人、权限、系统规则、敏感或注入内容。真正冲突只形成 supersedes 提案，不覆盖 active 观点。观察、演进、激活后恢复和证据均有幂等/冲突测试。
- 召回严格按 Higgs 自我、当前用户、近期历史排列。外部来源不进入共享提示；只有有保存原句证据的 Higgs 自我观点才可自称曾经说过。摄影观点已通过历史超过八轮与重启后自然召回的自动测试，但生产尚未导入。
- 新增主人查看来源、解释、采纳、拒绝、撤回和恢复命令，以及仅预览默认的摄影种子 CLI。生产数据库、配置、容器、消息与 NapCat 均未改变。

## 节点 47：Persona 与自我记忆合并，官方普通用户及群双层记忆完成本地集成

- Persona V2 PR #53 与 self-memory v4 PR #54 已依次合并，main 分别到 `3182fcb3d6a1b9e03420946ce0b238477b24206b` 和 `f06ffbbb1bcf676fa99873bcbb7bf1a255b9dcb9`；两次合并后的主线 CI 均全绿，生产开关、数据库、容器和消息流未改变。
- 普通测试用户采用有截止时间的 capture-only Gateway，候选只保存 Bot 绑定 OpenID；关闭后按主人确认的精确数量原子冻结为 `0600` 文件并同步两端私有环境。冻结文件、Node 环境和 Agent 环境任一漂移均拒绝启动，捕获状态不能进入正式发布。
- 普通 C2C 与官方群开关、频率和熔断均相互独立且默认 false；owner C2C 保持独立可用。未知 C2C 在进入 durable queue、Journal、模型或记忆前丢弃，普通用户仍不能调用主人命令、工具、计划、提醒、主动发送或治理接口。
- 群公共记忆与 member principal 私有记忆分层。公共候选不保存 raw 成员/消息标识、原句、个人事实或私聊；单人重复不形成 quorum，只有主人批准或两位不同成员独立佐证才 active。召回顺序是 self、当前 group、当前 principal、近期历史，C2C 与其他群无法读取该 group scope。
- 只有官方群获准 @ 事件且回复最终 SENT 后才运行公共候选提取；失败、UNKNOWN、未 @、OneBot 和 C2C 均不学习。组合本地回归 Python `430 passed, 5 skipped`、Node `47 passed, 9 skipped`，Ruff/格式/Node 语法通过；尚待阶段 PR、Ubuntu 零跳过和 release gate，生产完全未变化。
- PR #55 的 push/PR runs `33302169174`、`33302181366` 全绿并合并为主线 `81876e14f8af61789ce66e520c59f9467054e1b1`；合并后 main run `33302221595` 亦成功，Linux Python 零跳过并完成 Node POSIX、Shell、镜像和 Compose 验收。72 小时观察仍在固定窗口内，故未部署、迁移、捕获、冻结或开启任何新通道/记忆开关。

## 节点 48：最新功能以全关闭门部署并进入 24 小时观察

- 文档收束后的目标主线为 `e60afd6b0347ed79e2308b64a26d8bb476f21049`，tree `7496deb84f075fcb79ebbee473f1e8ddfcac952f`。593709 字节、302 成员的 Git-only 发布包通过摘要 `e001694cf5334b3dfd9abef90e68ad8640cb8f218b732a8a977f0b3e50c72294`、秘密边界和 LF 校验。
- 旧观察在约 9.44 小时检查点仍健康，19 次 reconnect/ready 均恢复，rejected、致命转换和活动批次均为零。主人选择不等待固定 72 小时并继续发布；因此旧窗口只作为部分稳定性证据，不能标记为完整通过。
- 首次发布暴露一次性包装器缺陷：私有 env 备份、原子更新和恢复错误地统一写成 `root:root/0600`，而 Agent 会以 `10001:10001` 再读 `higgs.env`，导致 PermissionError 重启。无参数回滚又选中缺少官方 overlay 的旧 release；显式恢复已知健康版本并纠正 `higgs.env` 属主后，Agent/sidecar/NapCat 全部 healthy，NapCat 未重启。
- 包装器随后改为保存每个私有 env 的原数字属主、显式健康回滚和不可变 release 幂等校验。已存在 release 必须与签名归档逐文件一致才能重新激活。一次已有目标安全拒绝并 healthy 回滚后，最终发布成功；所有新功能开关仍 false，只有既有 owner 官方被动回复保持 true。
- 最终门控为 release/两镜像匹配、三容器 healthy、单 Gateway、official transport verified、零活动批次、NapCat 容器不变。未发送消息、读取身份或正文、重登或重启 NapCat。十个临时发布/回滚文件已移入服务器回收区。
- `higgs-72` 已复用为部署后 24 小时观察：2026-08-30 19:00:18 至 2026-08-31 19:00:18，每 3 小时只读检查。代码开发继续；生产下一步只允许单独确认 owner Persona V2，20 轮真实对话验收之后再推进自我记忆 shadow 与其他用户/群灰度。

## 节点 49：owner Persona V2 完成受控生产灰度

- 主人明确授权只开启 owner Persona V2 并只重建 Agent。生产只将 `R_AGENT_PERSONA_V2_ENABLED=false` 原子改为 `true`；Agent 使用既有 `e60afd6b0347ed79e2308b64a26d8bb476f21049` 镜像重建一次，official sidecar 与 NapCat 的容器指纹保持不变。
- 前置门要求三容器 healthy、Agent 镜像和 release 精确匹配、单 Gateway、官方 transport verified 且健康回执新鲜、零活动批次、reply=true，并逐项确认 self-memory schema/mode、group memory、ordinary C2C、官方群和 proactive 为 false。任何失败只恢复 `higgs.env` 并只重建 Agent。
- `higgs.env` 的可恢复备份保存在 `/srv/trash`，备份与原子替换均保持 `0600`、`10001:10001`，避免再次触发 Agent 私有配置读取权限事故。控制台最初拒绝启动过长命令，未发生服务器变更；压缩传输后先验证脚本摘要和 `bash -n`，再完成切换并把脚本移入服务器回收区。
- 独立匿名后验在上线约四分钟时仍为 Agent/sidecar/NapCat healthy 且重启计数为零、Gateway=1、reply=true、Persona V2=true、其他新功能全部关闭、transport verified/connected/authenticated/account-match/ok，回执新鲜，pending/rejected/fatal/reconnect/active batches 均为零。未发送测试消息、读取身份或正文、迁移数据库、导入观点、重登或重启 NapCat。
- 观察自动化重置到 2026-08-30 20:03:42 至 2026-08-31 20:03:42。下一验收是主人至少 20 轮真实官方私聊，记录去敏的四维评分与典型出戏/守卫样本；通过前不开放 self-memory shadow、摄影种子、普通用户或官方群。
- 生产记录已通过 PR #58 合并为主线 `f55e927d9cfbe96564e8a7dd7973b4c56aad1620`。PR 四项检查与合并后的 main CI run `33310807439` 全绿，Linux Python 零跳过并通过 Node、Shell、发布包、秘密边界、镜像和 Compose；记录合并未触发任何生产重建。

## 节点 50：Persona 2.1 阻断角色自我抹除

- 主人真实灰度反馈确认 Persona V2 的主要残余缺陷：Higgs 会记得“雪豹”标签，却借诚实边界转入数字承载、无实体、无实际经历、长期智能体和系统配置等解释，等价于主动抹除角色生活。项目记忆仅记录匿名失败类型，不保存聊天正文。
- Persona Bundle 升级为 `2.1.0`，把角色履历与当前外部操作明确分层。身体、实验室、长跑、摄影以及城市高处、远郊山地和高海拔经历为既定角色事实；缺少具体地名、设备或履历证据时只能承认记不确切，不能说没有任何经历。只有主人主动询问技术承载时才允许短暂说明实现层。
- 风格与示例新增身份追问、摄影经历、自我介绍、长期关系和自然疲惫交流的对照样例。守卫增加 `IMMERSION_BREAK`，对真实高信号出戏句式执行一次改写，仍失败则使用角色一致的固定降级；普通技术系统讨论保持不受影响。
- 自动人格集扩展至 55 条。Windows 本地 Python `439 passed, 5 skipped`，Node `47 passed, 9 skipped`；Ruff、格式、发布门、秘密边界、Shell LF 和 diff 检查通过。本机无 Bash，Linux 零跳过和 Shell 语法由 PR CI 收口。
- 本节点未部署、改生产开关、重建容器或发送消息，当前 Persona V2 生产灰度与 24 小时观察均保持原状。Persona 2.1 合并后仍需主人单独确认才可只重建 Agent。
- Persona 2.1 已进入 PR #60；push run `33312732031` 与 pull_request run `33312743071` 四项 CI 全绿，Ubuntu 补齐 Python 零跳过、Shell 语法、Node POSIX/UDS/进程替换、npm 签名、镜像与 Compose。仅追加本证据后复验同一 PR，生产仍未改变。

## 节点 51：Persona 2.1 部署准备暂停

- PR #60 已合并为主线 `f8354699fb84f61e1d30a64ca229d03232ded1a4`，main CI run `33312844875` 全绿；主人已授权部署并只重建 Agent。
- 匿名前置门为三容器 healthy/零重启、单 Gateway、reply=true、官方 transport verified 且健康回执新鲜，零 rejected/fatal/active batches。服务器直连 GitHub 的首次非切换准备因网络中断安全退出，staging 移入 `/srv/trash`，生产未改变。
- 本机经 GitHub API取得同一提交并生成 604685 字节、303 成员、SHA-256 `558e9b17f3e20ff85e03be35aee57869a1d6321bb0bf56d6a4fbb73d61158d74` 的 Persona 2.1 发布包，已上传 `/root`。关机时云端只在校验、构建新 Agent 镜像和安装待激活 immutable release，超时 600 秒；它不会切 current、改私有 env 或调用 Compose。
- 恢复时先查云任务终态和当前生产匿名基线。只有确认准备成功与生产仍健康后，才允许原子切换 current/Agent 镜像并只重建 Agent；任一后验失败回滚。Sidecar、NapCat、其他开关和数据库均不得改变。

## 节点 52：Persona 2.1 生产激活与新观察基线

- 恢复后的准备态复核确认旧生产仍健康，待激活 `f8354699fb84f61e1d30a64ca229d03232ded1a4` Agent 镜像与 release 完整存在，镜像内 Persona Bundle 为 `2.1.0`。因为 PR #60 不含依赖、锁文件或 Dockerfile 变化，新镜像基于既有已验收 Agent 镜像并精确覆盖 CI 通过的 `r_agent` 包。
- 原子激活前把 `stack.env` 按原数字属主/模式备份到 `/srv/trash`，并保留旧 `current` 目标；失败路径只恢复这两项并只重建旧 Agent。本次规范 release 安装、`current`/镜像标签切换和 Agent 强制重建成功，未触发回滚。
- official sidecar 与 NapCat 没有重建：两者容器标识、启动时间和重启计数与前置指纹完全一致。Agent 以精确新镜像启动并 healthy，Persona Bundle 从运行容器内再次验证为 `2.1.0`。
- 上线后匿名门禁为三容器 healthy/零重启、单 Gateway、reply=true、transport verified/connected/authenticated/account-match/ok、健康回执新鲜、零 rejected/fatal/active batches；私有配置元数据未漂移。
- self-memory schema/mode、群记忆、普通用户、官方群和 proactive 继续关闭；没有迁移数据库、导入观点、发送消息、读取身份/正文、重新登录或重启 NapCat。生产能力只从 owner Persona V2 的 `2.0.0` 更新到 `2.1.0`。
- `higgs-72` 观察重置为 2026-08-30 23:26:02 至 2026-08-31 23:26:02，每 3 小时只读检查 Persona 版本、开关、三容器、单 Gateway、官方 transport 和活动批次。截止后生成结论并暂停；真实对话沉浸度仍由主人继续验收。
- 生产记录进入 PR #61。首轮 CI 在上海深夜暴露日计划测试夹具仍用真实事件时间的问题；固定事件与业务模块时钟统一后，本地 Python `439 passed, 5 skipped`、Node `47 passed, 9 skipped`、Ruff/格式/release gate 通过，修正后的 push/PR runs `33320282139`、`33320283690` 四项全绿且 Linux Python 零跳过。修正仅涉及测试，不改变生产代码、配置或容器。

## 节点 53：Persona 2.2 自然 furry 语气、短答优先与漏问恢复

- 真实 owner 对话暴露的匿名缺陷为：日常回答仍有接待/通用助手腔，雪豹身份没有自然进入感知与措辞，普通问题过度展开，以及生成失败后的上一问未被后续催答识别。聊天正文、身份和平台标识未写入项目记忆。
- Persona Bundle 升级为 `2.2.0`：雪豹感从身体尺度、环境感知、高处与山地经验、个人偏好自然流出，日常/自我/情绪每次最多点到一处；专业技术不强塞兽类词。堆叠抖耳、甩尾、舔爪、呼噜、嗷呜或“本豹”等表演被禁止。
- 运行时增加确定性答复模式。普通对话固定 `compact`（240 tokens、通常二至六句/一至三小段）；明确详细/展开/系统分析，或具体参数、代码、报错、推导、排查、训练/拍摄方案请求进入 `detailed`（800 tokens）。用户明确要求简短时始终回到 compact。
- PersonaGuard 新增 `OVERLONG_DEFAULT` 和 `PERFORMATIVE_FURRY`；普通模式超过约 300 个可见字符、三项列表/标题或堆叠动作时只允许一次保真改写。详答的必要结构保持允许。
- 同主体、同会话、同通道最近十分钟内至多两条 `model_failed` 用户问题会以无 assistant 的短期上下文补回；催答时先补原问，不再误称对方没问。该恢复不扩大长期记忆或跨用户范围。
- 回归与人工评阅清单从 55/50 扩展为统一 67 条。定向 50 项、完整 Python `451 passed, 5 skipped`、Node `47 passed, 9 skipped`、Ruff、格式、release gate、秘密模式、Shell LF 与 diff 检查均通过；Ubuntu 零跳过与 Shell/Node POSIX 仍待 PR CI。
- 本节点未改变生产 Persona 2.1、配置、数据库、容器或消息流，也未干扰正在进行的 24 小时观察。下一步同步远端主线、独立 PR/CI；生产部署仍需单独确认并只重建 Agent。
- PR #62 已从最新 main `30f615e6c7bff1489405171bc298cc8f437240c4` 建立。`github.com` Git smart HTTP 暂时不可达时改用 GitHub Git Data API，远端 tree `45d1b25ceebe04c3be2840f309c958604aa5d862` 与本地逐字节一致；仍是普通阶段分支，没有直接推送 main。
- push/pull_request runs `33323748799`、`33323762741` 四项任务全绿；Ubuntu Python 零跳过，并通过 Shell、秘密/发布包、Node POSIX/UDS/进程替换、npm 签名、镜像和 Compose。当前只追加 CI 证据并复验 PR，生产不变。
- 复验 runs `33323840063`、`33323841589` 再次全绿，PR #62 合并为 main `6682be3c33c78b1e486286fb224af986419cb922`；合并后 main run `33323897339` 两项任务成功。Persona 2.2 源码阶段完成，尚未部署；生产仍运行 Persona 2.1，Agent-only 更新必须另行确认。

## 节点 54：Persona 2.2 完成 Agent-only 生产激活

- 主人授权测试通过后直接部署。目标 main 为 `6682be3c33c78b1e486286fb224af986419cb922`，远端与本地 tree `b51fb97520e6667b14a94c00d572ae320b61074d` 一致；617609 字节、302 成员的 Git-only 归档通过 SHA-256、release gate、秘密模式和 Shell LF 校验，Bundle 为 `2.2.0`。
- 前置匿名门确认 Persona 2.1 生产三容器 healthy/零重启、单 Gateway、reply/owner Persona 为 true，官方 transport verified 且回执新鲜，零 rejected/fatal/active batches；所有尚未获准的新记忆、普通用户、群和 proactive 开关仍关闭。
- 新镜像基于已验收旧 Agent 镜像，仅覆盖 CI 通过的 `r_agent` 包；先离线验证 Persona `2.2.0` 及聚合哈希，再安装不可变 release。原 `stack.env` 按原数字属主与 `0600` 备份到 `/srv/trash`，失败路径会恢复 current/镜像标签并只重建旧 Agent。
- 本次仅强制重建 Agent，未触发回滚。独立后验确认新 release/镜像/Bundle 精确匹配、三容器 healthy/零重启、Gateway=1、transport verified/connected/authenticated/account-match/ok 且回执新鲜，零 active/rejected/fatal/Resume/reconnect。除 Agent 镜像标签外私有配置无变化，official sidecar 与 NapCat 指纹保持不变。
- 没有迁移数据库、导入观点、发送测试消息、读取身份/正文、重新登录或重启 NapCat。`higgs-72` 已重置到 2026-08-31 01:11:51 至 2026-09-01 01:11:51 的 Persona 2.2 只读观察；真实沉浸度继续由主人对话验收，其他能力的生产开启仍需独立确认。
- 生产记录 PR #63 的首轮 runs `33324831703`、`33324845285` 与复验 runs `33324963637`、`33324966549` 均全绿，并合并为 main `d944306da48b15f29e1d3d1745c013dfb7e1b698`；合并后 main run `33325020959` 再次通过且 Linux Python 零跳过。记录提交本身未触发任何生产动作。

## 节点 55：完整聊天助手能力盘点与阶段 0 开工

- 全量只读审计覆盖 GitHub 从 `8e4656a85d` 到当前 `5f6f2a6599` 的 195 个提交、PR
  #1–#64、09–28 阶段记忆、当前源码、测试和生产交接。能力状态改用五态账本：
  `implemented / deployed-off / active / accepted / deferred`，避免再次把默认关闭代码写成
  已上线能力。
- 新账本固定当前生产 Agent `6682be3c33c78b1e486286fb224af986419cb922`、Persona
  `2.2.0` 和 corlinman `v1.56.5` / `27bdf9c8`。corlinman 只作为架构、记忆、审批、
  搜索隔离和运维参考，不整体复制，也不采用其尚未实现 Resume 的官方 QQ Adapter。
- 当前已验收核心是官方 owner C2C、durable transport/reply 与 owner Persona 2.2。普通
  C2C、官方群 `@`、群双层记忆、自我记忆、摄影种子、官方 proactive 和 live 计划均有
  不同程度的代码基础，但生产仍关闭或未迁移。
- 产品决定为官方群只接受任何获准成员的 `@Higgs`；普通白名单用户默认拥有自己的长期
  记忆，只通过自然对话纠正；安全搜索、资料理解和本人提醒/计划以后向普通用户开放，
  服务器、配置、审批和跨用户治理仍只限主人。
- 本节点仅整理公开文档和下一阶段边界，不连接生产、不修改私有状态、不发送消息、不重建
  任何容器。阶段 0 通过独立分支、PR/CI 后，立即进入版本化捕获、Persona 全用户覆盖和
  principal 隔离强化。

## 节点 56：官方普通用户与官方群 V2 完成离线闭环

- 阶段 1 以远端主线 `8c2c4982e5ff2785ff8a21089548ba1a215145df` 为基线，私聊和群
  都升级为 Bot 绑定的可重复 CaptureEpoch 与不可变 AllowlistVersion。每个版本保存内容无关
  的来源 epoch、前序版本和规范指纹；双端身份、版本、指纹、App 或 Bot 任一漂移都失败关闭。
- account-scoped principal 迁移保持显式默认关闭；普通 C2C、官方群以及两类 Persona 2.2
  覆盖也各自默认关闭。未知身份、未知群、未 `@` 群消息与错误 Bot 在任何业务持久化前拒绝，
  普通用户不会获得 owner 命令、工具、配置、审批或跨用户治理权限。
- 私聊和群捕获/冻结形成一致的部署链：重复捕获从已冻结基线增量合并，旧版本和失败产物
  只进入 `/srv/trash`；冻结保持所有受众、Persona 和 schema 门不变。精确确认的激活器在线
  备份 identity 数据库，只重建 Sidecar 与 Agent，任何后验失败都回滚，NapCat 必须保持原状。
- 激活器支持两个受众按任意顺序逐个打开，不会为了第二个受众关闭第一个；已有受众的三重
  门、identity schema 或名单 provenance 不一致时拒绝执行。旧固定 72 小时群激活入口已在
  有效路径上禁用，固定观察不再阻塞离线开发，但每次真实受众扩大仍须单独确认。
- Windows 完整门禁为 Python `482 passed, 5 skipped`、Node `59 passed, 9 skipped`；Ruff、
  格式、Node 语法、Shell `bash -n`、release gate、秘密边界、Shell LF 和 diff 检查通过。
  当前尚未部署、迁移、捕获、冻结、激活、发送消息或重建任何生产容器，下一步为阶段 PR 与
  Ubuntu 零跳过 CI。
- 独立上线脚本审计发现并修复了 `100644` wrapper 直接执行、校验失败误重建、备份残留、
  回滚不等健康、只看旧 transport 回执与首群数量未锁定等风险；最终入口显式 `exec sh`，
  只读预检通过后才备份和改配置。激活与捕获/冻结共享锁，Sidecar 停止后排空批次，再停
  Agent 并备份 identity；名单 Bot 还要与 session 中已认证身份一致。真实激活仍需主人另行
  确认。

## 节点 57：官方受众 V2 合并并转入普通用户自然记忆

- PR #66 已合并为 main `d210fb52e652715d48a153d1edcc73c03cd6e387`。两套 PR CI 与
  合并后 main run `33363558396` 全绿；Ubuntu Python 零跳过，Node 的 POSIX、UDS 与进程
  替换覆盖均实际执行。主线记录不等于生产上线。
- 生产普通 C2C、群、Persona 表面、identity schema v2、群记忆、自我记忆与 proactive
  继续关闭；没有部署、捕获、冻结、迁移、重建、发送消息或更改 NapCat。
- 新阶段从该主线建立 `codex/higgs-natural-memory-v2-20260831`，只实现普通用户本人作用域
  的明确记住、重复观察、自然纠正与遗忘请求。跨用户、权限、身份、敏感信息和提示注入仍
  必须隔离，生产迁移和开关继续单独确认。

## 节点 58：普通用户 Personal Memory V5 离线完成

- 新能力仍使用 `memory.sqlite`，schema v5 与 self-memory v4 相互独立且显式 opt-in；发布
  默认 `schema=false / mode=off`。off 不创建表，shadow 只写内容无关的意图决定，active
  才可在单事务中激活或失效本人记忆。
- 明确记住低风险本人事实或偏好可一次生效；普通表达需 `>=0.94` 与两个不同消息。纠正需
  精确旧内容，建立 successor 并关闭 predecessor；只有“我现在更喜欢……”而没有旧内容时
  会要求澄清，不以同类唯一项猜测。遗忘不物理删除，owner 仍走原治理命令。
- identity、channel 与 Bot account 都参与查找和证据边界；跨用户、跨 Bot、blocked、敏感、
  权限和注入均失败关闭。重复 observation 和 durable 重放不重复写，幂等键冲突拒绝。
- 最终审计补齐更广的指令注入词、普通 principal 的单 Bot/account 绑定，以及多级 successor
  的递归恢复门；合法 restore 会清空旧的 `valid_to_ms`，不会形成“active 但不可召回”。
- 明确动作的确认文字仍经过原 reply policy、风险预算、输出安全与 durable 投递；shadow
  不伪称已记住。当前本地 Python `515 passed, 5 skipped`，Node `59 passed, 9 skipped`，
  其余发布门通过；生产未部署、迁移、启用、发消息或重建，下一步为独立 PR 与 Ubuntu CI。

## 节点 59：Personal Memory V5 合并并转入 self-memory 真实 shadow

- PR #67 已合并为 main `a693013cf2d4edfda6e8f87c0ec0a108b40ac84d`。push run
  `33368455489`、pull_request run `33368523783` 与合并后 main run `33368598779` 全绿，
  Ubuntu Python 零跳过，官方 Sidecar、Shell、发布包、秘密边界、镜像和 Compose 均通过。
- 合并只更新 GitHub 主线。生产 Personal Memory v5 的 schema/mode、普通 C2C、群、
  self-memory v4、摄影种子和 proactive 均未启用，没有部署、迁移、捕获、发送消息、重建
  容器或修改 NapCat。
- 阶段 3 从该主线建立 `codex/higgs-self-memory-shadow-20260831`。目标是把既有 SENT-only
  严格 JSON 管线补成有匿名持久收据、失败重放和质量门的真实模型 shadow，并强化摄影种子
  备份/确认；代码完成不等于获准迁移、运行 shadow 或导入观点。

## 节点 60：self-memory shadow、评测与摄影种子安全门离线完成

- self-memory v4 新增内容无关的持久 shadow run：输入与运行键只存 SHA-256，记录 lane、
  pending/complete/failed、attempt、候选/拒绝/隔离计数、错误类型和耗时。失败不伪成功，
  pending 可重放，complete 跳过，服务级 shadow 硬门无视误传的自动激活参数。
- 构造 `SelfMemoryService` 不再隐式迁移；显式 schema v4 是唯一入口。相同观点复用 item 并
  追加证据，真实原句必须能在 SENT 回复中验证。成功提取后清空 observation 全文，隔离候选
  的内容、来源 principal 和平台消息标识只留哈希；硬删除同时清理伴随表与孤立 observation。
- 新增 38 条中文 self/adopted 演进评测和聚合-only CLI，质量门锁定 precision `>=0.95`、
  recall `>=0.90`、处置准确率 `>=0.95`，误激活、污染与意外 parse failure 为 0。固定 fixture
  只验证管线；真实模型 outputs 仍须在单独获准的生产 shadow 中收集匿名指标。
- 摄影 seed CLI 改为 preview 零 DB 访问；正式导入必须精确确认、既有 v4/普通文件/大小/
  quick_check 全通过，并先生成同目录 SQLite 一致性备份、校验哈希与 `0600` best effort。
  失败保留备份，幂等重放不重复写，但每次确认仍先备份。
- 本地 Python `538 passed, 6 skipped`、Node `59 passed, 9 skipped`；Ruff、格式、发布包、
  秘密边界、Shell LF、Node 语法和 diff 检查全部通过。生产保持 schema=false/mode=off，未
  部署、迁移、跑 shadow、导入观点、开启自主成长、发送消息或重建任何容器。

## 节点 61：PR #68 审计阻断修复与重新验收

- PR #68 首轮 CI 虽全绿，独立复核仍发现：模型失败时完整 SENT 回复可能长期残留、post-SENT
  观察异常可能让 durable batch 回到发送重试、不同来源并发可能生成重复观点，以及聚合评测
  缺少可复核版本收据。阶段没有因 CI 绿色而提前合并。
- self observation 改为处理结束必释放正文、无 evidence 自动移除；新服务实例启动即清理
  所有旧的崩溃残留。重放使用瞬时文本时必须重新匹配既有 fingerprint，不接受伪造正文。已经确认
  SENT 后，记忆/risk 后处理异常只记录类型，不再改变最终发送决定。
- self-memory proposal 使用 persona、kind 与规范内容构成的语义幂等键；两个来源并发提交同一
  观点时共享同一 memory item，激活竞争也按已激活结果收敛。hard delete 仍清理已关联证据，
  空结果或隔离路径不再遗留包含正文的孤立 observation。
- 评测回执新增 run ID、时间、evaluator/model/prompt 版本、数据集 SHA-256 和 outputs 集合
  SHA-256。真实 outputs 缺精确版本标签时失败关闭；收据继续不含案例正文或候选内容。
- 修复后本地全量为 Python `544 passed, 6 skipped`、Node `59 passed, 9 skipped`，38 条评测
  precision/recall/处置准确率均为 `1.0` 且零误激活/污染；Ruff、格式、发布与秘密门通过。
  生产保持所有阶段 3 开关关闭，未部署、迁移、发送消息、重建或改动 NapCat。

## 节点 62：self-memory 合并并启动阶段 4

- PR #68 合并为 main `517bb23a8a58aec70b7751740a86e2dae1d7da49`；修复后的两套
  PR CI 与合并后 main run `33374862049` 全绿，Ubuntu Python 零跳过。首次绿色 CI 后仍先
  完成独立审计修复再合并，未用自动测试替代隐私与并发复核。
- 生产未随合并变化：self-memory v4/mode、摄影观点、普通 C2C、群、主动发送和自主成长
  继续关闭；没有数据库迁移、部署、消息发送、容器重建或 NapCat 改动。当前服务器浏览器
  会话未能形成新的匿名观察证据，因此本节点不声明生产即时健康或异常。
- 阶段 4 从新 main 建立独立集成分支，工具与普通用户任务在各自 worktree 隔离实现。工具
  只读且默认 shadow/disabled，必须限制 SSRF、重定向、DNS rebinding、大小、时限、文档
  路径和下载隔离；普通用户提醒/计划只绑定本人和当前官方 Bot，创建与主动投递分门控制，
  不向群投递、不跨 NapCat/官方切换。

## 节点 63：安全只读工具与普通用户个人任务离线集成

- 阶段 4 从 main `517bb23a8a58aec70b7751740a86e2dae1d7da49` 建立独立分支；工具和任务先在隔离 worktree 开发，再经主线程交叉审计合并。生产状态没有随源码开发改变。
- 安全工具新增 `web_search/read_url/document_read` 的 fail-closed 边界。默认无网络 transport，真实执行必须绑定 caller role、surface、principal、session、data scope、规范参数审批决定与预算；模型 shadow 不能执行 handler。公网请求逐跳防 SSRF、DNS rebinding、私网/保留地址、危险端口、userinfo、重定向、超时、超大响应和错误 content type。
- 附件只以事件中的 opaque handle 暴露；隔离相对路径只存在于受信 binding store，不进入 durable event。文档读取校验 Bot、sender、principal、session、事件、过期时间、symlink、路径穿越、大小、DOCX 外链/宏/压缩炸弹，并把文档内容标记为 untrusted。隔离文件清理只移动到 recycle。
- 个人提醒和计划引入严格 `DeliveryTarget`。普通用户仅可在获准官方 Bot 私聊操作自己的任务；list/show/confirm/ack/cancel/snooze、计划草案/确认/重排和节点提醒均按 principal+Bot+target 作用域。普通任务创建/草案与 ordinary proactive 分开，owner/ordinary proactive 也在 Agent 和 Sidecar 两端分开，群与跨通道投递失败关闭。
- 集成审计发现并修复两项阻断：attachment path 原本可能随事件持久化；普通 proactive 原本仍被 owner-only 目标函数拦截。进一步补上 owner proactive 关闭时不能借 ordinary proactive 通道投递的回归。
- 独立终审修复后的完整合并测试为 Python `590 passed, 7 skipped`、Node `59 passed, 9 skipped`，Ruff、格式、Node 语法和 release gate 通过。本机无 Bash，Shell 语法与 Windows 跳过项必须由 Ubuntu PR CI 收口；本节点不代表代码已部署或功能已对用户开放。
- PR #69 首轮 push run `33382686895` 与 pull_request run `33382728996` 均全绿；Ubuntu 已实际执行 Python 零跳过、Shell、Node POSIX/UDS/进程替换、发布包、镜像与 Compose。追加本证据后仍需新一轮 CI 复验再合并，生产开关与容器继续不变。

## 节点 64：Stage 4 合并主线，生产继续关闭

- PR #69 追加证据后的 push/pull_request runs `33382859370`、`33382862796` 再次全绿，合并为 main `4e13e2ec0014fe25fd6f322391a7455e9bd5f402`；合并后 main run `33382985494` 成功。
- Ubuntu 已收口 Windows 的七个 Python 与九个 Node 跳过项，并通过 Shell、秘密/发布包、POSIX/UDS、镜像与 Compose。Stage 4 的安全工具边界和普通用户本人任务现已进入主线。
- 主线能力不等于生产启用：真实搜索 provider、工具路由、附件 ingress、普通任务 mode/proactive、普通 C2C 与群均保持未部署或关闭。没有数据库迁移、受众扩大、消息发送、容器重建或 NapCat 改动。

## 节点 65：Persona 2.2 观察窗口截止但无法形成完整结论

- 约定窗口于 2026-09-01 01:11:51（Asia/Shanghai）截止。最后三个计划检查点因任务没有附加可用服务器终端而无法运行匿名只读观察脚本；因此没有连续覆盖到截止时间的容器、Gateway、transport、回执、批次和开关证据。
- 本窗口结论严格记为“证据不完整”，不是稳定性通过，也不是已确认故障。既有部署后健康基线不能替代缺失时段的现场检查，后续新检查也不能倒填本窗口。
- 观察期间未发送测试消息、重启、重登、改配置或读取/记录敏感状态。截止后已删除 `higgs-72` 自动化，不再继续检查；若仍需 24 小时验收，须在恢复安全只读终端后单独批准新窗口。

## 节点 66：最新主线完成生产部署，新增能力保持关闭

- 主人明确授权正式部署与继续推进。发布基线固定为 GitHub main
  `35c1fcd3e30e703f29b5c7874c5a840ae17e24a7`；对应 main CI run
  `33465241346` 成功。本地发布门确认 311 个跟踪文件、336 个归档成员、秘密边界和 Shell LF
  均通过，发布归档与部署脚本分别做了精确 SHA-256 校验。
- 部署前匿名门确认三容器健康且零重启、官方 Gateway 单实例、reply=true、transport
  verified/connected/authenticated/account-match/ok、健康回执新鲜、零 pending/rejected/fatal/
  reconnect 和 active durable batches。部署脚本先对 agenda/reminders SQLite 做一致性备份，
  再构建不可变 Agent 与官方 Sidecar 镜像，具备原子切换和自动回滚。
- 生产 release、Agent 与官方 Sidecar 已精确切换到 `35c1fcd3e30e703f29b5c7874c5a840ae17e24a7`。
  Agent、Sidecar、NapCat 后验均 healthy；官方 Gateway=1，transport verified 且身份匹配，
  active batches=0。NapCat 容器未重建，身份与启动基线未改变。
- owner 官方被动回复与 Persona 2.2 保持开启。identity v2、普通 C2C、官方群、普通/群 Persona、
  personal memory v5、自我记忆 v4、群记忆、摄影种子、owner/ordinary proactive、普通任务
  mode 以及 Stage 4 网络工具真实 provider/路由全部保持关闭；本次没有扩大受众、导入观点、
  发送测试消息或运行记忆迁移。
- 独立部署后匿名复核再次确认三容器健康、零重启、Gateway 单实例、官方 transport 健康且
  回执新鲜、零状态转换和零活动批次。该证据是即时部署验收，不倒填节点 65 缺失的历史观察。
- 下一生产边界按能力账本推进：先 identity v2 与普通 C2C CaptureEpoch，再冻结名单和单独
  激活；personal memory、单个官方群、self-memory shadow、摄影种子和工具/任务各自保持
  独立迁移、开关与验收，不因代码已经部署而自动开启。
- 生产记录 PR #72 的首轮两套 Node 检查通过，但两套 Python CI 同时在上海深夜暴露 Stage 4
  普通用户 live 计划测试仍依赖运行机墙钟：确认发生在当日任务之后时不会创建未来提醒，固定
  断言因而为空。修正仅将该测试的业务事件与服务时钟冻结到固定上午，不改变生产调度语义。
  修正后本地 Python `590 passed, 7 skipped`，Ruff 与格式检查通过；生产没有因该测试修正
  再次部署或重建。
- 修正后的 PR #72 push/pull_request runs `33528667178`、`33528673361` 四项检查全绿，
  Ubuntu Python 实际为零跳过，并再次通过 Node、Shell、发布包、秘密边界、镜像与 Compose。
  追加本证据后仍需最后一轮 CI 复验再合并；记录提交不会触发生产重建。

## 节点 67：生产记录 PR 合并并完成主线 CI 收口

- PR #72 的最后复验 runs `33528870584`、`33528874871` 四项检查全绿；随后合并为 main
  `0cd89e2fee1869b259d5d84d256e1fb7d2ddc508`，合并后 main run `33528978401`
  再次通过，Ubuntu Python 零跳过，Node、Shell、秘密/发布包、镜像和 Compose 均成功。
- PR 合并与本记录收口没有再次部署、迁移、扩大受众、发送消息或重建容器。生产功能 release
  仍精确为 `35c1fcd3e30e703f29b5c7874c5a840ae17e24a7`，节点 66 的匿名后验与关闭开关边界继续有效。

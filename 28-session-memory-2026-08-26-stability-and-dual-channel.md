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

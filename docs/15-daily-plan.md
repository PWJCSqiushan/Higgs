# Higgs 今日计划：设计、权限与使用

## 它解决什么问题

单项提醒只回答“什么时候提醒什么”，而今日计划需要同时回答“今天有哪些事、哪些时间不能动、先做什么、路上要花多久、计划变化后怎样安全重排”。因此 `daily_plan` 是独立技能，不会把多项任务直接批量写入提醒库。

## 完整数据流

```text
获准的私聊（OneBot 用户，或官方 Bot 主人 C2C）
  → 身份与白名单检查
  → 任务/日期/地点/时间条件提取
  → 本地结构校验
  → 确定性可行排程
  → draft / awaiting_map_consent
  → 用户单次地图授权（可选）
  → 路线计算与新草案
  → awaiting_confirmation
  → 精确版本确认
  → active + 节点提醒
```

模型只能返回受限 JSON 候选。未知字段、无效日期、超过 20 项任务、单项低于 5 分钟或高于 480 分钟、非法优先级和不存在的依赖都会被拒绝。模型失败时使用保守的本地解析器；模型永远不能绕过确认。

## 状态与版本

计划状态：

`draft → awaiting_map_consent → awaiting_confirmation → active → completed/cancelled/superseded/expired`

任务状态：

`draft → scheduled → in_progress → completed/skipped/cancelled`

每份草案有 UUID、8 位显示短 ID、版本号和规范化参数 SHA-256。确认只覆盖当时的计划 ID、版本、参数指纹和原始私聊会话；任何改变都会产生新草案，旧确认不能复用。重新规划先保留原计划，只有新草案确认后才把旧计划标为 `superseded` 并取消未发送节点。

## 地图隐私

1. 初次解析只在 Higgs 数据库中保存用户给出的地点文字。
2. 系统先展示识别到的地点，不调用地图。
3. 用户执行 `/higgs plan map-consent 计划短ID`，才对该计划版本授权。
4. 授权指纹和 10 分钟有效期写入审计；API Key 只存在服务器 secrets。
5. 地址出现多个候选时返回候选摘要并要求补充，不自动选择。
6. 路线结果只用于新草案；新草案仍需再次确认。

高德未配置、配额耗尽或无路线时，计划保持“路线未验证”，不会伪称已经计算。`route_cache` 只保留短期结果，默认设计上限为 24 小时；地点不会自动进入长期记忆。

## 提醒策略

普通提醒继续使用“到点、+5、+15、+30，收到后停止”。今日计划使用独立的 `agenda_once` 策略：

- 08:00 前确认：08:00 发送一次总览；
- 08:00 后确认：确认回复中立即给出完整计划；
- 每项任务开始前 10 分钟发送一次；
- 开始时再发送一次；
- 节点发送成功即完成，不要求 ACK，也不重复追发；
- 完成、跳过、取消或确认新版后，撤销尚未发送的旧节点。

发送使用唯一 occurrence key。服务器重启时会恢复未到期节点；绑定通道离线时不发送，过期节点标为 `missed`，不会在很久以后补发失去意义的消息。每个节点在确认时固定绑定 channel、private surface、Bot account 与目标，回复和节点不会透明切换到另一种 QQ 身份。

## QQ 命令

```text
/higgs plan today                    查看今天或最近待确认计划
/higgs plan add <内容>               创建待办草案
/higgs plan draft                    查看当前草案
/higgs plan map-consent <计划ID>     授权本版本地点调用地图
/higgs plan confirm <计划ID>         确认精确版本
/higgs plan show <计划ID>            查看计划和任务短 ID
/higgs plan done <任务ID>            标记完成并取消剩余节点
/higgs plan skip <任务ID>            跳过并取消剩余节点
/higgs plan replan <计划ID>          生成新版，不立即替换旧版
/higgs plan cancel <计划ID>          取消自己的计划
/higgs plan history                  查看最近 10 份计划
```

主人跨用户取消使用：

```text
/higgs plan admin cancel <计划ID> <原因>
```

跨用户操作必须带原因，事件只展示匿名来源摘要并写入审计。普通用户不能查看其他人的计划，也不能在群聊创建个人计划。

官方 QQ 当前只向显式绑定的主人开放上述私聊命令和自然语言草案。`shadow` 可在主动发送关闭时使用；`live` 确认会产生节点提醒，因此还要求 Agent 与 sidecar 的 proactive 双门已按 72 小时稳定性门禁单独启用。非主人、官方群聊和跨 Bot/OpenID 目标均失败关闭。

## 运行模式和配置

```dotenv
R_AGENT_DAILY_PLAN_MODE=shadow
R_AGENT_DAILY_PLAN_DRAFTS_PER_DAY=10
R_AGENT_DAILY_PLAN_MAP_OPTIMIZATIONS_PER_DAY=3
R_AGENT_AMAP_WEB_KEY=
```

- `off`：不识别今日计划；
- `shadow`：生成、验证、授权和展示草案，但确认不会激活或创建真实提醒；
- `live`：确认后写入正式计划并创建节点提醒；要求主回复链路也为 `live`。

现有 2GB 服务器采用受时间和任务数约束的确定性求解器，不常驻启动 OR-Tools 容器。未来服务器资源升级后，可以把同一输入 schema 交给独立、限时 2 秒的 OR-Tools 进程，失败时仍回退到当前可行调度，不放宽任何硬约束。

## 数据与备份

- `agenda.sqlite`：计划、任务、依赖、版本、地图授权摘要、审计和提醒关联；
- `skills.sqlite`：精确参数审批；
- `reminders.sqlite`：总览与节点 occurrence/effect。

这三个数据库与其他运行库一起进入当前 13 库一致性备份。API Key、OneBot token、NapCat 登录状态和地点正文不会写入备份清单或 Git 配置快照。

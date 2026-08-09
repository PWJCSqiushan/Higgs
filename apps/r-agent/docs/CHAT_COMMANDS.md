# Higgs 主人聊天命令

所有管理命令必须由 `.env` 中 `R_AGENT_OWNER_QQ` 精确绑定的主人账号发送。命令由本地确定性代码执行，不交给大模型判断。建议优先在与 Higgs 的私聊中使用。

```text
/higgs help
```

可随时查看当前版本支持的命令摘要。

## 状态、暂停与恢复

```text
/higgs status
/higgs disable
/higgs enable
/higgs risk
```

`disable` 只暂停普通回复；OneBot 监听、消息日志、提醒调度和主人命令仍保持运行，因此可以随时用 `enable` 恢复。`risk` 显示 24 小时发送、失败、限流、半小时峰值、疑似机器人来源和被踢次数，不显示聊天正文。

## 白名单

```text
/higgs whitelist
/higgs whitelist private add 目标QQ号
/higgs whitelist private remove 目标QQ号
/higgs whitelist group add 群号
/higgs whitelist group remove 群号
```

这些命令同时更新入站与回复白名单，并原子写回本地 `.env`。移除群白名单时，也会自动移除该群的自然触发权限。

## 自然触发群与关键词

```text
/higgs natural
/higgs natural add 群号
/higgs natural remove 群号
/higgs keyword
/higgs keyword add 希格斯
/higgs keyword remove 希格斯
```

自然触发群必须先进入群白名单。至少保留一个明确指向 Higgs 的关键词；不要加入“你”“在吗”等常见词，否则容易误回他人的对话。

## 回复频率与连续消息

```text
/higgs rate
/higgs rate 2 6
/higgs debounce
/higgs debounce 2.5
```

`rate 2 6` 表示普通单会话每分钟最多生成 2 次回复、所有会话合计每分钟最多 6 次。系统还有小时、每日硬上限和非主人会话熔断；聊天命令不能绕过这些保护。`debounce` 范围为 0.5–10 秒，用于合并同一会话、同一个人的连续短句。

## 记忆状态与短 ID

Higgs 的长期记忆有四种状态：

- `candidate`：等待审核，不参与长期召回；
- `quarantined`：高风险、敏感或疑似注入，默认隔离；
- `active`：已经审核，可在同一身份作用域的对话中召回；
- `invalidated`：已经作废，不参与召回，但保留版本与审计证据。

分页查看：

```text
/higgs memory list candidate 1
/higgs memory list quarantined 1
/higgs memory list active 1
/higgs memory list invalidated 1
/higgs memory list candidate 2
```

Higgs 每页返回 8 条，每行开头的 8 个字符就是短 ID：

```text
7f3a91c2 | candidate | 该用户偏好：清晨跑步
```

后续命令可以直接使用 `7f3a91c2`，不必输入完整 UUID。短 ID 至少输入 6 位；若前缀不唯一，Higgs 会要求增加字符，不会误操作另一条记忆。

## 人工审核记忆

先查看完整内容和元数据：

```text
/higgs memory show 7f3a91c2
/higgs memory audit 7f3a91c2
```

再按实际情况执行一个操作：

```text
/higgs memory activate 7f3a91c2 已确认是本人稳定偏好
/higgs memory quarantine 7f3a91c2 涉及隐私，暂不使用
/higgs memory invalidate 7f3a91c2 信息错误或已经过期
/higgs memory restore 7f3a91c2 重新核实后恢复
```

`audit` 包含动作、执行角色和时间戳，不在审计表中重复保存秘密正文。永久物理删除不会开放给聊天命令，仍需在本机 CLI 中输入完整记忆 UUID 二次确认。

## 自动审核

查看或修改策略：

```text
/higgs memory auto
/higgs memory auto on
/higgs memory auto off
/higgs memory auto threshold 0.90
/higgs memory auto evidence 2
```

推荐配置为开启、置信度至少 `0.90`、同一人通过不同消息重复表达至少 `2` 次。自动审核不是让大模型自由决定，只有同时满足以下条件才可能激活：

1. 发言者是部署配置中精确绑定的主人；
2. 内容是发言者自己的第一人称偏好；
3. 作用域严格绑定主人的内部 principal；
4. 内容由受限的记忆提取器产生；
5. 风险为低，置信度达到阈值；
6. 同一主体在不同消息中重复表达达到要求次数；
7. 不含敏感类别。

地址、电话、QQ/微信/邮箱、证件、账号密码、验证码、密钥、健康诊断、财务状况、政治宗教、管理员权限、主人关系、系统提示词等永远不能进入自动激活通道。非主人消息可以形成候选，但不能自动激活。

紧急情况下先执行：

```text
/higgs memory auto off
```

这只关闭后续自动审核，不会删除现有记忆；随后用 `list active`、`show`、`audit` 和 `invalidate` 逐条处理。

## Memory V2 状态、观察与召回

```text
/higgs memory
/higgs memory stats
/higgs memory observations
/higgs memory observations failed 10
/higgs memory observations retry 观察短ID
/higgs memory recall 10
/higgs memory source status
```

- `memory`：查看总数、向量和自动审核概要；
- `stats`：查看候选、激活、隔离、失效、向量、待处理观察和最近整理时间；
- `observations`：查看待处理、已处理、已排除和失败数量；
- `observations failed 10`：只显示错误类型、重试次数和错误摘要，不回显聊天正文；
- `observations retry`：把指定失败观察重新放回后台队列；
- `recall 10`：查看最近十次召回，`items=` 后面是实际用于回答的记忆短 ID；
- `source status`：只显示匿名化来源质量、冷却和疑似机器人来源统计。

后台默认每 15 分钟处理一批、每批最多 50 条。单条坏观察会标记为 `failed`，不会阻塞整批。

## 安全回填历史聊天

```text
/higgs memory backfill preview
/higgs memory backfill apply
```

先执行 `preview`：它只输出总数、合规数量和被高频来源排除的数量，不显示聊天正文，也不写入记忆。确认统计后才能执行 `apply`。

历史回填只把合规消息放进候选观察队列；即使历史消息来自主人，也会被降级为普通来源，永远不会在回填时自动激活。高频疑似机器人来源会被排除。

## 智能提醒

自然语言示例：

```text
20分钟后提醒我背单词
Higgs，今天18:20叫我下楼取快递
过30分钟给我发一条消息
```

Higgs 会先返回提醒时间、追发规则和 8 位任务 ID；主人回复“确认”后才生效。到点后回复“收到”“知道了”“完成了”或执行 ACK 命令会停止追发。

```text
/higgs remind list
/higgs remind show 任务短ID
/higgs remind confirm 任务短ID
/higgs remind ack 任务短ID
/higgs remind cancel 任务短ID
/higgs remind snooze 任务短ID 10m
```

追发时间为到点、`+5`、`+15`、`+30` 分钟，最多四次。任务绑定创建会话和任务 ID；在另一个群随口说“收到”不会误确认。QQ 离线期间暂停发送，恢复后只补发仍有效的提醒。

## 今日计划

第一版只允许主人和已验证的私聊白名单用户创建自己的计划，群聊不创建个人计划。

```text
/higgs plan today
/higgs plan add <待办内容>
/higgs plan draft
/higgs plan map-consent <计划短ID>
/higgs plan confirm <计划短ID>
/higgs plan show <计划短ID>
/higgs plan done <任务短ID>
/higgs plan skip <任务短ID>
/higgs plan replan <计划短ID>
/higgs plan cancel <计划短ID>
/higgs plan history
```

计划确认绑定计划 ID、版本、参数指纹和原始私聊。重新规划只生成草案，必须再次确认；完成、跳过或取消会撤销尚未发送的节点提醒。地图授权与计划确认是两次独立动作，执行 `map-consent` 前地点不会发给高德。

主人跨用户取消必须填写原因：

```text
/higgs plan admin cancel <计划短ID> <原因>
```

详细状态机、安全边界和配置见 [今日计划设计与使用](../../../docs/15-daily-plan.md)。

## 在线状态探针

健康检查必须区分“Higgs 能连接 OneBot”和“QQ 账号真实在线”：

```bash
python -m r_agent.health_probe --path /var/lib/higgs/health.json --require-qq-online
```

`transport_connected=true` 只代表 WebSocket 链路存在；`qq_online=true` 还需要账号身份探测和生命周期状态通过。若 NapCat WebUI、手机端状态和该字段互相矛盾，应再执行 OneBot `get_status` 主动探测，并用一条真实私聊完成最终验收，不能只相信 WebUI 的“已登录”页面。

## 备份

```text
/higgs backup
/higgs backup now
```

Higgs 默认每 6 小时创建一次一致性 SQLite 快照，保留最近 20 份；启动、主人修改配置和记忆状态变更后也会额外备份。备份清单只包含安全运行配置，不包含模型 API Key、OneBot token 或 QQ 登录态。

默认目录为 `data/backups`。若要防止整块磁盘损坏，建议把备份配置到另一物理磁盘或使用加密对象存储：

```dotenv
R_AGENT_BACKUP_INTERVAL_MINUTES=360
R_AGENT_BACKUP_RETENTION=20
```

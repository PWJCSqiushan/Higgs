# Higgs 主人聊天命令

所有管理命令必须由 `.env` 中 `R_AGENT_OWNER_QQ` 精确绑定的大号发送。命令由本地确定性代码执行，不交给大模型判断。建议在与 Higgs 的私聊中使用。

## 状态、暂停与恢复

```text
/higgs status
/higgs disable
/higgs enable
```

`disable` 只暂停普通回复；OneBot 监听、消息日志和主人命令保持在线，因此可以随时用 `enable` 恢复。

## 白名单

```text
/higgs whitelist
/higgs whitelist private add 目标QQ号
/higgs whitelist private remove 目标QQ号
/higgs whitelist group add 群号
/higgs whitelist group remove 群号
```

这些命令同时更新入站白名单和回复白名单，并原子写回本地 `.env`。移除群白名单时，也会自动移除该群的自然触发权限。

## 自然触发群与关键词

```text
/higgs natural
/higgs natural add 群号
/higgs natural remove 群号
/higgs keyword
/higgs keyword add 希格斯
/higgs keyword remove 希格斯
```

自然触发群必须先进入群白名单。至少保留一个明确关键词；不要加入“你”“在吗”等常见词。

## 回复频率与连续消息

```text
/higgs rate
/higgs rate 6 20
/higgs debounce
/higgs debounce 2.5
```

`rate 6 20` 表示单会话每分钟最多生成 6 次回复、所有会话合计每分钟最多 20 次。`debounce` 范围为 0.5–10 秒，用于合并同群同一人的连续短句。

## 记忆审核

```text
/higgs memory
/higgs memory list candidate
/higgs memory list quarantined
/higgs memory list active
/higgs memory show 记忆ID
/higgs memory activate 记忆ID 核实原因
/higgs memory quarantine 记忆ID 可疑原因
/higgs memory invalidate 记忆ID 作废原因
/higgs memory restore 记忆ID 恢复原因
```

列表每次最多返回 5 条。永久硬删除不会开放给聊天命令，仍需在本机 CLI 中重复输入记忆 ID 确认。

## 备份

```text
/higgs backup
/higgs backup now
```

Higgs 默认每 6 小时创建一次一致性 SQLite 快照，保留最近 20 份；启动、主人修改配置和记忆状态变更后也会额外备份。备份清单只包含安全运行配置，不包含模型 API Key、OneBot token 或 QQ 登录态。

默认目录为 `data/backups`。若要防止整个 D 盘损坏，建议在 `.env` 中配置到另一块物理磁盘：

```dotenv
R_AGENT_BACKUP_DIR=E:/Higgs-Backups
R_AGENT_BACKUP_INTERVAL_MINUTES=360
R_AGENT_BACKUP_RETENTION=20
```

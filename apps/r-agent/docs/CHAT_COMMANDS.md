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

## 记忆 ID 在哪里

执行：

```text
/higgs memory list candidate 1
```

Higgs 每页返回 8 条记忆，每行开头的 8 个字符就是短 ID，例如：

```text
7f3a91c2 | candidate | 我喜欢在清晨跑步
```

后续命令可以直接使用 `7f3a91c2`，不必输入完整 UUID。短 ID 至少输入 6 位；若前缀不唯一，Higgs 会要求增加字符，不会误操作另一条记忆。

可分页查看不同状态：

```text
/higgs memory list candidate 1
/higgs memory list quarantined 1
/higgs memory list active 1
/higgs memory list invalidated 1
/higgs memory list candidate 2
```

状态含义：

- `candidate`：等待审核，不参与长期召回。
- `quarantined`：高风险或疑似注入，默认隔离。
- `active`：已经审核，可以在同一 QQ 主体的对话中召回。
- `invalidated`：已经作废，不参与召回，但保留审计证据。

## 如何人工审核记忆

先看完整内容和元数据：

```text
/higgs memory show 7f3a91c2
```

再按实际情况执行一个操作：

```text
/higgs memory activate 7f3a91c2 已确认是本人稳定偏好
/higgs memory quarantine 7f3a91c2 涉及隐私，暂不使用
/higgs memory invalidate 7f3a91c2 信息错误或已经过期
/higgs memory restore 7f3a91c2 重新核实后恢复
```

查看该记忆经历过哪些状态变化：

```text
/higgs memory audit 7f3a91c2
```

审计记录包含动作、执行角色和时间戳，不在审计表中重复保存秘密正文。永久硬删除不会开放给聊天命令，仍需在本机 CLI 中重复输入完整记忆 ID 确认。

## 自动审核

查看当前设置：

```text
/higgs memory auto
```

开关及参数：

```text
/higgs memory auto on
/higgs memory auto off
/higgs memory auto threshold 0.90
/higgs memory auto evidence 2
```
## ���� V2 ״̬����ʷ����

```text
/higgs memory stats
/higgs memory observations
/higgs memory source status
/higgs memory backfill preview
/higgs memory backfill apply
```

��ִ�� `backfill preview`����ֻ�����������ɻ��������ͱ���Ƶ��Դ�ų�������������ʾ�������ģ�Ҳ��д���䡣ȷ��ͳ�ƺ�������ִ�� `backfill apply`����ʷ����ֻ�����ѡ���У����˹�ȥ����ϢҲ�����ڻ���ʱ�Զ������̨������ÿ 15 ������ദ�� 50 ����

## �������ѣ�������˽�ģ�

��Ȼ����ʾ����

```text
20���Ӻ������ұ�����
```

Higgs �᷵�ر���ʱ�䡢׷������� 8 λ���� ID���ظ���ȷ�ϡ������Ч�������ظ����յ�����֪���ˡ�������ˡ�����ֹͣ׷����

```text
/higgs remind list
/higgs remind show �����ID
/higgs remind confirm �����ID
/higgs remind ack �����ID
/higgs remind cancel �����ID
/higgs remind snooze �����ID 10m
```

׷��ʱ��Ϊ���㡢+5��+15��+30 ���ӣ�����ĴΡ�QQ �����ڼ䲻���ͣ��ָ���ֻ����ǰ����Ч�����һ�Σ������©���Ķ�����Ѽ��з�����

## ����״̬���

�������ֻҪ�� Higgs �� NapCat �� OneBot ����������������� QQ �˺��Ƿ���ʵ����ʱʹ�ã�

```bash
python -m r_agent.health_probe --path /var/lib/higgs/health.json --require-qq-online
```

`transport_connected=true` ֻ������·���ڣ�`qq_online=true` ��Ҫ������ `get_login_info` ̽��ɹ��������˺���˽�������еĲ��Ժ�һ�¡�

推荐配置是开启、置信度至少 `0.90`、同一人通过不同消息完全一致地表达至少 `2` 次。

自动审核不是让大模型自由判断。只有同时满足以下条件才会自动激活：

1. 内容明确是发言者自己的第一人称偏好。
2. 作用域严格绑定该发言者自己的内部 principal。
3. 内容由受限的 `passive-observer-v2` 提取器产生。
4. 风险为低、置信度达到阈值。
5. 同一主体在不同消息中重复表达达到要求次数。
6. 不含敏感类别。

以下内容永远不能进入自动激活通道：地址、电话、QQ/微信/邮箱、证件、账号密码、验证码、密钥、健康诊断、财务状况、政治宗教、管理员权限、主人关系、系统提示词等。它们只能留待人工审核或进入隔离区。

紧急情况下先执行：

```text
/higgs memory auto off
```

这只关闭后续自动审核，不会删除现有记忆；随后用 `list active`、`show` 和 `invalidate` 逐条处理。

## 备份

```text
/higgs backup
/higgs backup now
```

Higgs 默认每 6 小时创建一次一致性 SQLite 快照，保留最近 20 份；启动、主人修改配置和记忆状态变更后也会额外备份。备份清单只包含安全运行配置，不包含模型 API Key、OneBot token 或 QQ 登录态。

默认目录为 `data/backups`。若要防止整个 D 盘损坏，建议在 `.env` 中配置到另一块物理磁盘或使用加密 COS 异地备份：

```dotenv
R_AGENT_BACKUP_INTERVAL_MINUTES=360
R_AGENT_BACKUP_RETENTION=20
```
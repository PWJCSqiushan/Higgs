# Phase 3：结构化记忆底座

本阶段先建立可治理的 SQLite 记忆状态机，不自动读取聊天并写入长期记忆，也不把“向量相似”误当作“事实可信”。

## 数据边界

每条记忆必须携带：

- `scope_type + scope_id`：严格区分某个人、某个群、某个 persona 或全局范围；
- `kind`：用户事实、偏好、关系、承诺、事件摘要或群规则；
- 原始 QQ 消息来源：channel、机器人账号、message id、发送者内部主体；
- `created_by`：候选提取器版本；
- risk、confidence、status；
- 审核人、审核时间和失效原因；
- 为未来本地 embedding 预留的 BLOB 与维度字段。

`self_core`、主人身份和权限角色不属于自动记忆类型，不能通过聊天候选进入该表。

## 状态机

```text
普通候选：candidate ──owner──▶ active ──owner──▶ invalidated
                              │                    │
                              └──▶ quarantined ◀──┘

高风险候选：quarantined（永不自动 active）
```

- 只有 `active` 能被召回。
- 高风险候选初始进入 `quarantined`。
- 只有确定性权限层确认的 owner 能启用、隔离、失效、恢复或物理删除。
- 高风险记忆从失效状态恢复时仍回到隔离区，需要再次显式启用。
- 物理删除会移除正文，仅保留不可逆内容哈希和操作审计。

## 当前检索

当前使用参数化 SQLite 字面子串检索，并强制精确 scope；`%`、`_` 和 SQL 语句片段都只被当作普通文本。这样先固定用户/群隔离与治理语义。

后续加入 embedding 时，向量候选也必须先经过完全相同的 scope、status 和 risk 过滤，不能绕过本状态机。

## 尚未启用

- 没有从真实 QQ 聊天自动提取候选；
- 没有将记忆注入模型提示词；当前 recall ledger 仅提供注入前校验与审计底座；
- 没有后台 UI；
- 没有 embedding 生成和向量召回；
- 没有让模型自行审核或修改人格核心。

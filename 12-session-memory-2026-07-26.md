# R 智能体项目 Phase 3 进展

更新时间：2026-07-26（Asia/Shanghai）

## 本次完成

- 新增 `r_agent.memory.MemoryStore` 结构化 SQLite 记忆底座。
- 每条记忆保存 scope、类型、正文、QQ 来源、提取器、risk、confidence、status 和审核信息。
- 普通内容初始为 `candidate`，高风险内容初始为 `quarantined`。
- 只有确定性权限层中的 owner 可以启用、隔离、失效、恢复和物理删除。
- 只有 `active` 记忆可以被检索。
- 查询使用参数化字面检索；`%` 和 SQL 片段不能变成通配或注入。
- 物理删除会删除正文，仅留下不可逆内容哈希与操作审计。
- 状态更新使用当前状态比较，避免并发审核静默覆盖。
- 为未来 embedding 预留字段，但向量功能尚未启用。

## 验证

```text
pytest:             49 passed
ruff check:         All checks passed
ruff format check:  24 files already formatted
```

新增用例覆盖候选不可召回、高风险隔离、非主人拒绝、Alice/Bob 作用域隔离、失效/恢复、主人物理删除、查询注入、重复候选幂等和 `self_core` 禁止进入自动记忆通道。

## 安全状态

- 没有从真实聊天自动创建候选。
- 没有将记忆注入模型上下文。
- 没有调用 embedding 或真实模型。
- 没有启用 QQ 自动回复。
- 没有读取或提交本机秘密。

## 下一步

1. 为候选提取定义纯结构化接口与离线测试集，先不连接真实群聊。
2. 增加记忆管理 CLI/API：列表、查看来源、启用、隔离、失效、恢复、删除。
3. 增加 recall ledger，记录每轮究竟向模型注入了哪些记忆。
4. 完成主人后台前，不允许模型自行审核候选。
5. 后续再加入本地 embedding，并保持 scope/status/risk 过滤先于向量排名。

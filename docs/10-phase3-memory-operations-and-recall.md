# Phase 3：记忆管理与召回审计

本阶段补齐主人治理入口和 recall ledger。两者仍是离线安全底座：不会自动读取真实聊天、调用模型或向 QQ 发送消息。

## 运行位置

在 PowerShell 中进入应用目录：

```powershell
Set-Location '<Higgs仓库>\apps\r-agent'
```

所有管理命令都从当前 `.env` 读取 `R_AGENT_OWNER_QQ` 和 `R_AGENT_DATA_DIR`。没有配置主人 QQ 时命令失败闭锁；主人身份只来自部署配置，不接受聊天或模型声明。

## 查看和筛选

列出最近的记忆记录：

```powershell
uv run r-agent memory list
```

按状态和严格作用域筛选：

```powershell
uv run r-agent memory list --status candidate --scope principal --scope-id '<内部主体ID>' --limit 50
```

查看一条记忆的完整来源和内容哈希审计：

```powershell
uv run r-agent memory show '<item_id>'
```

列表、来源和审计读取同样要求确定性的 owner 角色，不为普通用户提供管理旁路。

## 审核状态

所有状态变更都必须填写人工理由：

```powershell
uv run r-agent memory activate '<item_id>' --reason '主人核对原始消息后确认'
uv run r-agent memory quarantine '<item_id>' --reason '来源或措辞可疑，等待复核'
uv run r-agent memory invalidate '<item_id>' --reason '用户已更正该信息'
uv run r-agent memory restore '<item_id>' --reason '先前更正有误，恢复有效状态'
```

高风险记忆恢复后仍返回隔离区，不会直接成为可召回记忆。

## 不可逆删除

物理删除需要在 `--confirm` 中重复完全相同的 `item_id`：

```powershell
uv run r-agent memory delete '<item_id>' --reason '隐私删除请求' --confirm '<item_id>'
```

正文会被删除，账本只保留内容哈希和操作元数据。输错确认 ID 时命令不会执行。

## Recall ledger

`RecallLedger.record(...)` 在未来每次构建模型上下文时登记实际选中的记忆。登记前会强制检查：

- 每条记忆必须已经是 `active`；
- 每条记忆必须属于本轮明确允许的 scope；
- 同一轮不能重复注入同一条记忆；
- 单轮上限 50 条；
- 同一个 `turn_id` 重试相同决定是幂等的，复用它写入不同决定会报冲突。

账本只保存 query 的 SHA-256、记忆 ID、scope key、策略版本和时间，不保存 query 原文或记忆正文。即使记忆后来因隐私请求被物理删除，历史注入事实仍可追溯，但无法从账本还原正文。

主人可按 turn ID 查看账本：

```powershell
uv run r-agent memory recall '<turn_id>'
```

当前还没有模型上下文构建器，因此正常情况下账本为空；该命令是为下一阶段的离线召回演练和未来故障审计预留。

## 当前安全结论

- 管理 CLI 不改变 QQ 回复开关；
- recall ledger 不会自行召回或注入任何内容；
- embedding 尚未启用；
- 模型不能审核、启用、删除记忆或修改主人身份；
- 所有真实模型、live 回复和自动候选提取仍需后续单独授权。

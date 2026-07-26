# R 智能体项目接续记录：记忆治理与召回审计

更新时间：2026-07-26（Asia/Shanghai）

## 恢复结果

- 重启前 Phase 3 文件仍完整处于暂存区，第二次提交当时并未成功。
- 重新执行测试与 Ruff 检查后，将结构化记忆底座提交为 `c06a5b5 feat: add auditable scoped memory foundation`。
- 没有重复提交或覆盖重启前工作。

## 本轮新增

- owner-only 记忆管理 CLI：列表、状态/scope 筛选、查看来源和审计。
- 主人可启用、隔离、失效、恢复记忆；每次操作都必须填写理由。
- 物理删除要求 `--confirm` 精确重复 item ID，避免误删。
- `MemoryStore` 增加受 owner 权限约束的管理读取和内容无关审计查询。
- 新增 `RecallLedger`：登记每个 turn 实际选择的记忆 ID、scope、策略版本和查询哈希。
- recall 登记只接受 `active` 且属于本轮允许 scope 的记忆；拒绝重复、越权或未审核候选。
- 同一 turn 的相同决定可安全重试，不同决定复用 turn ID 会失败闭锁。
- 记忆正文和 query 原文都不会写入 recall ledger。
- owner 可用 `uv run r-agent memory recall '<turn_id>'` 查看单轮审计。
- 新增详细使用文档 `docs/10-phase3-memory-operations-and-recall.md`。

## 验证

```text
pytest:             60 passed
ruff check:         All checks passed
ruff format check:  27 files already formatted
```

## 当前安全边界

- 没有从真实 QQ 聊天自动提取记忆。
- 没有调用真实模型或 embedding 服务。
- 没有把记忆注入模型上下文；recall ledger 目前只是安全底座。
- 没有启用 QQ 自动回复或发送。
- 没有读取、修改或提交 `.env`、token、QQ 登录态、真实聊天或其他秘密。
- 没有推送远端。

## 下一步建议

1. 定义纯结构化候选提取接口和离线、脱敏测试集，不先连接真实群聊。
2. 建立 prompt-injection 与记忆投毒评测：伪造主人、自我改名、关系胁迫、跨用户污染、重复灌输。
3. 实现离线 context builder：先 scope/status/risk 过滤，再排名，并在每轮写 recall ledger。
4. 为候选审核设计本机管理 API/UI；在身份认证完成前继续保留 CLI 为唯一治理入口。
5. 最后再评估本地 embedding；向量相似度不能绕过确定性权限和状态过滤。
6. 真实模型草稿测试需要主人另行选择供应商并在本机配置秘密；live QQ 回复仍需单独明确授权。

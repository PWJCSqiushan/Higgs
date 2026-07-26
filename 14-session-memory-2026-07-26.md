# R 智能体项目接续记录：QQ 多轮直接对话闭环

更新时间：2026-07-26（Asia/Shanghai）

## 上游同步

- 再次同步 `sweetcornna/corlinman`，当前最新仍为 v1.36.1 / `2d51c5a`。
- 重点参考其 OneBot 通道归一化、persona system message、SQLite 会话历史、action echo 回执和同毫秒稳定排序经验。
- 没有照搬其完整网关、后台 UI、插件和调度系统，继续保持当前项目的最短安全闭环。

## 本轮完成

- 新增 retention-bound `ConversationStore`，持久保存最近用户消息与模型回复。
- `drafted`、`sent`、`model_failed`、`send_failed` 严格区分。
- 草稿不会进入 live 历史，发送失败的幽灵回复也不会被智能体误认为已经说过。
- 会话历史按 channel、机器人账号、会话、内部主体和 outcome 严格隔离。
- 同一入站 message 幂等；复用同一消息写入不同结果会失败闭锁。
- 同毫秒会话使用 SQLite 插入序号稳定排序，并有专门回归测试。
- 新增 `ContextBuilder`：persona、短期多轮历史和 owner 已审核的 active 记忆统一构建模型上下文。
- 长期记忆只按精确 principal scope 读取；candidate、quarantined、invalidated 与其他主体记忆不会进入提示词。
- 每轮实际注入的记忆继续写 recall ledger，查询只保存哈希。
- OpenAI-compatible 客户端支持最多 42 条有界多轮 messages，并校验 role、单条大小与总大小。
- 新增 `persona.example.md`，本机使用 `persona.local.md`，后者已加入 Git 忽略。
- 新增 owner-only 草稿查看入口：

```powershell
uv run python -m r_agent.review_cli --outcome drafted --limit 20
```

- 新增完整草稿/live 操作文档 `docs/11-phase4-qq-direct-dialogue.md`。

## 验证

```text
pytest:             76 passed
ruff check:         All checks passed
ruff format check:  36 files already formatted
```

端到端测试已证明：owner 私聊可经过入站策略、身份解析、短期 Journal、persona/历史/记忆上下文和模型客户端形成连续草稿，且 draft 模式不会调用 QQ sender。

## 当前本机就绪度（仅检查布尔值）

- `.env` 存在。
- owner 已配置。
- OneBot token 已配置。
- shadow mode 已配置。
- 模型 API key 未配置。
- 模型 endpoint 未配置。
- persona file 未配置。
- reply mode 与 live gate 未配置。

因此代码已具备主人私聊闭环，但当前不能调用真实模型，也没有启用 QQ 自动发送。

## 下一步

1. 主人选择一个 OpenAI-compatible 模型供应商并在本机 `.env` 配置 endpoint、model、key。
2. 复制并按喜好修改 `persona.example.md` 为被忽略的 `persona.local.md`。
3. 先运行 draft，完成文档中的四轮连续性与攻击测试。
4. 查看本地草稿并调整人格、历史长度和回复频率。
5. 草稿通过后，再显式开启 live 三重开关；第一阶段群列表必须保持为空，只验收 owner 私聊。
6. 后续实现离线候选记忆提取器，不允许聊天直接写 active 记忆。

## 安全状态

- 没有读取或回显任何 QQ 号、OneBot token、模型 key 或 endpoint 内容。
- 没有修改现有 `.env`。
- 没有调用真实模型。
- 没有向 QQ 发送消息。
- 没有推送远端。

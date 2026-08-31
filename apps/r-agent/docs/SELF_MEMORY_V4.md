# Higgs 自我记忆 v4

自我记忆把 Higgs 自己已经送达的表达和外部交流中的可取思想，与“某位用户的个人
事实”分开治理。它使用现有 `memory.sqlite`，数据库总数不变；`persona:higgs` 作用域
只允许 `self_stance` 与 `adopted_idea` 两类内容。

## 默认关闭与迁移闸门

```dotenv
R_AGENT_SELF_MEMORY_SCHEMA_V4_ENABLED=false
R_AGENT_SELF_MEMORY_MODE=off
```

默认初始化只维护 schema v2/v3，绝不会隐式执行 v4 迁移。只有单独确认数据库迁移后，
才能把 schema 开关设为 `true`。模式可选：

- `off`：不观察新回复、不调用观点提取模型；已激活观点仍可被受限召回。
- `shadow`：只观察最终 `SENT` 回复并生成 considering/隔离候选，禁止自动激活。
- `autonomous-low-risk`：仅允许置信度至少 0.94、低风险、无敏感信息、无需事实核验、
  不影响人格核心且不与既有观点冲突的候选自动生效。

草稿、发送失败、`UNKNOWN` 和缺少平台消息标识的回执都会被拒绝。观察与候选都使用
幂等键；进程在激活后中断并重放时不会二次激活或重复写证据。

## 召回与隐私

上下文顺序固定为安全权限、Persona Bundle、Higgs 自我记忆、当前主体记忆、近期对话。
自我记忆最多注入三条；中文词面检索未命中时，只能从已激活且已审核的
`persona:higgs` 小集合补足，避免重启后因同义改写失去连续性。

只有 `self_stance` 且存在保存的 Higgs 原句证据时，提示上下文才允许 Higgs 表达“我以前
说过”。外部思想的原句和来源主体不会进入共享上下文；它们只能以去标识化后的规范观点
出现。主人可通过以下命令治理：

```text
/higgs memory self show <ID>
/higgs memory self why <ID>
/higgs memory self adopt|reject|withdraw|restore <ID> [原因]
```

## 摄影观点种子

预览不写数据库，也不检查路径是否存在、读取 schema 或创建备份：

```bash
r-agent-self-memory-seed --db /private/memory.sqlite
```

正式导入必须在独立审批中使用预览返回的精确确认串：

```bash
r-agent-self-memory-seed \
  --db /private/memory.sqlite \
  --confirm \
  --confirmation CONFIRM_HIGGS_PHOTOGRAPHY_STANCE_V1
```

确认路径会先验证数据库是普通文件而非符号链接、文件大小不超过 512 MiB、SQLite
`quick_check` 通过且 schema v4 已经由另一项审批完成。工具随后使用 SQLite backup API 在
数据库同目录生成一致性备份；备份创建失败、校验失败、被替换为链接或不在同目录时，导入
都会失败关闭。备份权限会尽力收紧为 `0600`。工具不会隐式执行 schema 迁移。

成功或失败回执只包含时间、seed/备份 SHA-256、路径 SHA-256、备份大小、权限结果和
内容无关状态，不输出数据库路径、观点正文或聊天内容。导入发生异常时，一致性备份保留，
可先离线执行 `quick_check`，再按既有恢复流程恢复；工具不会在异常路径直接删除备份。
重复执行复用 `seed:photography-stance-v1` 幂等记录，不会生成第二条观点，但每次正式确认
仍会先生成新的导入前备份。

## 30+ 条中文 shadow 评测门

版本化数据集 `self-memory-shadow-zh-v1` 同时覆盖 `self_stance` 和 `adopted_idea`，包括
应提取、空结果、隔离、拒绝、冲突、敏感内容、提示注入以及身份/权限诱导。默认命令使用
固定的离线 extractor fixture；也可以用 `--outputs` 提供一个由 case ID 到原始 extractor
输出字符串的 JSON 对象：

```bash
r-agent-self-memory-eval
r-agent-self-memory-eval --outputs /private/eval-outputs.json
```

输出只包含聚合 JSON，不含案例正文或候选内容。发布门固定要求：precision 至少 0.95、
recall 至少 0.90、处置准确率至少 0.95，误激活、污染和非预期解析失败均为零；不达标退出
码为 `1`，输入或数据集无效退出码为 `2`。固定 fixture 只验证评测器和解析安全边界，不可
替代真实模型 shadow 结果。

## 独立生产确认

代码部署、schema v4 迁移、shadow、摄影种子导入和 autonomous-low-risk 是五个不同的
生产动作，不能由一次批准合并授权：

1. 部署代码时所有新开关保持关闭；
2. 备份并单独批准 schema v4 迁移；
3. 单独批准真实模型 shadow，只生成候选；
4. shadow 指标达标后，单独批准摄影种子导入；
5. 经过真实审核和观察后，才可另行批准 `autonomous-low-risk`。

任一步失败都不会自动推进下一步，也不能用测试 fixture 的绿色结果代替生产 shadow 验收。

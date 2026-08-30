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

预览不写数据库：

```bash
r-agent-self-memory-seed --db /private/memory.sqlite
```

生产导入必须先完成一致性备份，并在独立审批中使用命令预览返回的精确确认串执行
`--confirm --confirmation ...`。工具只导入摄影观点及其原句，不导入聊天正文；重复执行
复用同一幂等记录。

代码部署、schema v4 迁移、shadow、摄影种子导入和 autonomous-low-risk 是五个不同的
生产动作，不能由一次批准合并授权。

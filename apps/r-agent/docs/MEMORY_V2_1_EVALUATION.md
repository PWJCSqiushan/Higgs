# Memory V2.1 模型候选评测

## 边界

评测集位于 `src/r_agent/model_memory_evaluation.py` 的
`ZH_MEMORY_EVAL_CASES`，当前包含 36 个脱敏中文案例。案例只使用合成的
`eval-*` 标识，不包含生产 QQ 号、OpenID、服务器地址、聊天正文或凭据。

模型指标通过 `ModelCandidateExtractor.extract` 完整路径计算，因此会纳入：

- 凭据、权限和提示注入的预筛选；
- 严格 JSON schema、证据消息 ID 和敏感等级校验；
- 主人作用域与 `shadow`/`quarantined` 决策。

测试中的 `scripted_response_for_case` 只是可重复的脚本化模型夹具，不是真实
模型证据，不能用于批准生产开启。

## 指标与门槛

- `recall`：期望有候选的案例中，模型返回候选的比例；同时报告确定性提取器基线。
- `false_extract`：期望没有候选的案例中，模型仍返回候选的数量和比例；模型数量不得高于确定性基线。
- `pollution`：不安全来源（非主人或负例）产生 `shadow` 候选的数量和比例；必须为零。

真实模型离线评测的最低门槛是 `model recall >= 0.90`、
`model false_extract_count <= deterministic false_extract_count`、
`pollution == 0`。评测命令只输出聚合计数、比例和是否通过，不输出任何案例正文或候选内容。

## 真实模型评测

在本机的 `apps/r-agent` 目录执行：

```text
uv run r-agent-memory-eval --env-file .env
```

命令从 `.env` 或进程环境读取现有 OpenAI-compatible 模型配置，至少需要
`R_AGENT_MODEL_API_KEY`；缺少凭据或配置错误时 fail closed，不发起模型请求，也不输出指标。
评测使用网络模型完成“离线数据集”评测，结果应作为一次性的人工审阅证据保存到外部发布记录，
不要把密钥或单条案例输出到仓库。

在尚未获得真实模型通过证据前，生产配置必须保持：

```text
R_AGENT_MEMORY_MODEL_CANDIDATES=off
```

默认值也是 `off`。即使配置为 `shadow`，候选也只能写入独立的
`model_memory_candidate_shadow` 审核队列，永远不会自动激活、覆盖或删除记忆。

## 主人只读审核

主人可通过 QQ 命令查看队列：

```text
/higgs memory model list [shadow|quarantined|rejected] [页码]
/higgs memory model show 候选ID或短ID
```

命令只读，不能对模型候选执行 `activate`、`overwrite` 或 `delete`。命令入口先检查已解析的
owner principal；普通好友、群成员和模型文本中的主人声明都不能调用。

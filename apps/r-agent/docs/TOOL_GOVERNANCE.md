# 阶段 3：受治理的只读工具

Higgs 的工具边界位于模型、业务层和宿主机之间。工具不会因为模型输出了
JSON、函数名或“请执行”文字而自动运行；必须由确定性代码创建请求、核对
权限、产生与参数绑定的审批哈希，并在所有限额和幂等检查通过后执行。

## 当前工具

当前唯一注册的工具是 `server_status`。它只接受空 JSON 对象，只允许主人在
私聊中显式发送 `/higgs server status`。模型侧请求的来源固定为
`model_shadow`，即使携带了看似正确的参数也会被拒绝，不能调用该工具。

宿主机上的 `higgs-server-status.timer` 每分钟运行一次
`collect_server_status.py`，原子地生成以下固定路径的非敏感快照：

```text
/srv/data/higgs/server-status/status.json
```

Agent 容器将目录以 `:ro` 挂载到 `/run/higgs-server-status`，读取器只接受
`/run/higgs-server-status/status.json`。读取器拒绝符号链接、路径穿越、未知
JSON 字段、非法数字、过大文件和超过 180 秒的旧快照。容器没有 Docker
Socket、宿主机 shell 或通用文件读取接口。

## 治理流程

```text
ToolRequest
  -> 参数 NFKC 规范化 + JSON schema
  -> actor / surface / source 权限检查
  -> 显式主人批准（默认拒绝）
  -> 参数审批 SHA-256
  -> SQLite 原子幂等预留 + 每工具每主体限频
  -> timeout 受控执行
  -> ToolReceipt（succeeded / failed / unknown 等）
```

审计 SQLite 仅保留工具名、角色哈希、参数哈希、原因、状态和时间，不保存
参数原文或执行结果（除非未来某个工具明确声明结果可持久化）。幂等键在
进程重启后仍然有效；已完成的键返回 `duplicate`，执行中或上次结果未知
的键返回 `unknown`，不会盲目重试。

未知回执永远不是成功。工具处理器可以返回 `ToolExecutionResult(UNKNOWN)`，
治理层会保留该状态，并要求操作者重新确认外部事实后再处理。

## 接入新工具的硬性要求

1. 新工具必须拥有封闭的 JSON 输入 schema，并在 `ToolSpec` 中显式声明角色、
   surface、超时、限频和是否允许持久化结果。
2. 默认保持 `enabled=False`、`requires_explicit_approval=True` 和
   `allow_model_execution=False`；模型只能留下 shadow 请求。
3. 处理器必须拒绝未声明的字段，不能调用 shell、Docker Socket 或读取请求
   指定的任意路径。
4. 先补充注入、越权、路径穿越、超时、限频、重启幂等和未知回执测试，CI
   通过后才能接入 owner 命令。
5. 每个工具的主人操作都必须返回 `ToolReceipt`，不能以异常吞掉、默认成功
   或把 `unknown` 转成 `succeeded`。

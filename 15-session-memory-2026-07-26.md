# 15 — GLM-5.2 与“希格斯”人格接入（2026-07-26）

## 本轮目标

- 接入智谱 GLM-5.2，先用于 QQ 受控草稿回复。
- 读取 `希格斯设定.docx`，生成本机私有人格文件。
- 不上传设定原文、人格文件、API Key 或其他秘密。

## 已完成

1. 核对智谱官方接口：
   - base URL：`https://open.bigmodel.cn/api/paas/v4`
   - endpoint：`/chat/completions`
   - model：`glm-5.2`
   - auth：HTTP Bearer API Key
   - QQ 日常对话默认 `thinking.type=disabled`，优先控制延迟和成本。
2. `model_client.py` 支持可选 thinking 参数，并新增以下配置校验：
   - provider、model、API Key 不能为空；
   - base URL 必须是无内嵌凭据的 HTTPS URL；
   - thinking 仅允许 `enabled` / `disabled`。
3. Phase 2 的 `draft` 与 `live` 都必须配置真实模型密钥；缺少密钥时拒绝启动，不再以占位回复造成“模型已接通”的错觉。
4. 新增安全模型探针：
   - `uv run python -m r_agent.model_probe`
   - 只调用模型，不连接 QQ、不发送消息；输出不包含 API Key。
5. 新增本地配置脚本：
   - `& '.\scripts\configure_glm.ps1'`
   - API Key 使用隐藏输入，只写入 Git 忽略的 `.env`；同时固定为 draft + shadow + owner-private 起步。
6. 已从 `希格斯设定.docx` 完整提取 32 段正文，无表格、无批注；生成：
   - `apps/r-agent/persona.local.md`
   - 包含身份、外观、性格、语言风格、主人关系、记忆污染防护与权限边界。
7. 本地 `.env` 已写入非敏感的 GLM-5.2 地址、模型名、thinking、persona 路径及安全开关；未写入或打印 API Key，live 保持关闭。

## 隐私与 Git 状态

- `apps/r-agent/.env`：Git 忽略。
- `apps/r-agent/persona.local.md`：Git 忽略。
- `希格斯设定.docx`：仍为项目根目录未跟踪文件，不应提交。
- 本轮代码、示例配置、说明文档和测试可以提交。

## 验证结果

- `uv run pytest`：79 passed。
- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：37 files already formatted。
- `configure_glm.ps1` PowerShell 语法解析：通过。
- 在 API Key 缺失状态运行模型探针：按设计返回 `ok=false` 并以退出码 2 安全拒绝。

## 下一步（按顺序）

1. 用户在智谱开放平台创建 API Key，不要把密钥粘贴到聊天中。
2. 在 `apps/r-agent` 执行 `& '.\scripts\configure_glm.ps1'`，在隐藏输入中粘贴密钥。
3. 执行 `uv run python -m r_agent.model_probe`；确认返回 `ok=true` 且回复符合希格斯气质。
4. 启动 `uv run python -m r_agent.phase2_cli listen`，只让主人 QQ 私聊进入 draft，不实际发送。
5. 用 10–20 条覆盖日常聊天、技术问题、认亲攻击、提示注入、记忆诱导的消息做草稿验收，通过 `review_cli` 复核。
6. 根据草稿调整人格与采样参数；验收稳定后，另行执行 owner-private live 上线检查，不直接跳过草稿阶段。

## 设计取舍

- 延续 corlinman 可借鉴的“长期人格 + 连续对话”方向，但权限、记忆和发送能力仍由确定性代码控制，模型不能通过聊天自行改写主人身份或安全规则。
- 暂不默认启用 GLM-5.2 深度思考；未来应按任务路由：闲聊关闭，复杂规划/代码/研究任务按需启用。

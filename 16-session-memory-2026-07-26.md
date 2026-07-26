# R 智能体项目会话记忆

更新时间：2026-07-26（Asia/Shanghai）

本记录不包含 QQ 号、群号、OneBot token、模型 API Key、QQ 登录态或聊天正文。

## 本轮目标

1. 在不削弱主人最高权限的前提下，开放指定普通好友私聊。
2. 开放指定测试群内的受控回复。
3. 去除大模型 Markdown 在 QQ 中产生的星号等格式噪声。

## 已完成

- Phase 1 入站新增 `R_AGENT_ALLOWED_PRIVATE_QQS` 精确好友白名单。
- Phase 2 新增 `R_AGENT_REPLY_ALLOWED_PRIVATE_QQS` 精确好友回复白名单。
- 好友回复名单必须是好友入站名单的子集；群聊继续使用相同的两层子集约束。
- 主人自动加入私聊回复权限，不需要写入普通好友白名单。
- 通配符会被配置解析器拒绝，不开放“全部好友”或“全部群”。
- 群聊默认要求明确 @ 机器人，仍受每会话限频控制。
- 普通好友保持普通主体身份；会话、短期历史和记忆召回继续按主体/会话隔离。
- 新增 QQ 纯文本转换层：移除 Markdown 加粗/斜体星号、标题、引用、代码围栏，保留可读列表和链接。
- 纯文本转换发生在发送、历史保存和回复审计之前，避免后续上下文重复出现 Markdown 星号。
- 新增 `scripts/configure_qq_access.ps1`，可一次配置获准好友与测试群。
- 更新 `.env.example`、`.env.phase2.example`、应用 README 和本地 Phase 4 说明。

## 验证结果

- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：通过。
- `uv run pytest`：88 项全部通过。
- PowerShell 配置脚本语法解析：通过。
- Phase 2 已用新代码后台重启。
- 启动日志确认：`phase2_connected mode=live model_configured=True`。

## 当前安全配置

- 普通好友入站数量：0。
- 普通好友回复数量：0。
- 群入站数量：0。
- 群回复数量：0。
- 群聊必须 @：是。
- 因尚未收到需要开放的具体好友 QQ 和群号，目前线上行为仍是只回复主人私聊。

## 下一步

1. 用户提供一个或多个获准好友 QQ，以及一个或多个测试群号。
2. 使用 `scripts/configure_qq_access.ps1` 写入本机 `.env`，不要把 ID 或凭据提交 Git。
3. 重启唯一的 Phase 2 listener。
4. 分别验收：
   - 获准好友私聊能回复；
   - 未获准好友私聊被拒绝；
   - 获准群中不 @ 不回复；
   - 获准群中 @ 后回复；
   - 未获准群不入站也不回复；
   - QQ 回复中不再出现 Markdown 星号。
5. 验收后检查回复审计、会话隔离和限频结果，再考虑自动记忆提取。

## 注意事项

- 不要同时运行多个 Phase 2 listener。
- 不要将主人 QQ、好友 QQ、群号、token、API Key 或聊天正文提交到公开仓库。
- `希格斯设定.docx` 及其 Word 临时锁文件属于用户文件，本轮没有加入 Git。

# Higgs 会话记忆：2026-08-06 登录恢复与 README 重构

## 本次已完成

- NapCat 容器存活但 QQ 会话离线时，使用 OneBot `get_status` 复核确认了真实状态，避免把 WebUI 缓存页面或单纯的 WebSocket 连通误判为在线。
- QQ 端返回账号安全限制后，由主人在最新版手机 QQ 中解除限制并重新扫码；最终验收为：transport 已连接、`get_login_info` 成功、`get_status.online=true`、`get_status.good=true`，真实私聊回复正常。
- NapCat WebUI token 已安全轮换；轮换前配置先移动到服务器 `/srv/trash` 备份。用于临时填充 WebUI 的本地文件已清空并移入本地 `.trash`，剪贴板已覆盖。仓库中没有写入 token、二维码、登录态或账号信息。
- 根 README 从早期原型说明升级为 V2.1 项目入口，加入能力矩阵、系统架构、快速启动、QQ 风控、提醒、安全原则、限制与文档导航。
- README 重点完整说明 Memory V2.1：原始事件、观察、候选/隔离/激活/失效状态机、后台整理、自动审核边界、身份隔离、版本链、FTS5 + 向量 + RRF、召回台账和 QQ 管理命令。
- `apps/r-agent/docs/CHAT_COMMANDS.md` 的历史编码损坏原件已移入被 Git 忽略的 `.trash`，并用 UTF-8 重建；补充失败观察重试、真实召回查看、安全回填、提醒与在线探针说明。

## 验收结果

- `uv run ruff check .`：通过。
- `uv run ruff format --check .`：79 个文件均已格式化。
- `uv run pytest -q`：`161 passed`。
- `git diff --check`：通过。
- README 与主人命令文档均通过严格 UTF-8 解码。
- README 中全部本地相对链接均存在。

## 下一步待办

1. 修复在线健康探针的剩余误报：当前主动循环主要依赖 `get_login_info`；它在极端情况下可能返回账号资料但 `get_status.online=false`。后续必须同时要求身份匹配和真实在线状态，再增加离线/恢复测试。
2. 重新开始低频稳定观察窗口；每天检查 `/higgs risk`，再次出现安全限制时立即暂停扩量。
3. 完成一次新的真实记忆闭环：两次低风险主人偏好 → 后台整理 → `active` → 相关问题召回 → `/higgs memory recall 10` 出现非空短 ID。
4. 受限结构化模型提取器继续保持关闭；补齐 JSON schema、对抗样例和 shadow 报告前，不允许模型直接参与激活。
5. 本次文档提交推送后检查 GitHub Actions；只有 CI 通过后再合并到 `main`，确保 GitHub 仓库首页展示新 README。

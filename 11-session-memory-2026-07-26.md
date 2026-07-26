# R 智能体项目接管进展

更新时间：2026-07-26（Asia/Shanghai）

## 一、本次完成

- 恢复并审查了关机前保存的 Phase 2 WIP，没有直接采用未经验证的文件。
- 在隔离副本补充安全回归测试，再将验证版本合并正式项目。
- 正式测试从 17 项增加到 40 项，全部通过。
- `ruff check .` 与 `ruff format --check .` 全部通过。
- 项目版本从 `0.1.0` 更新为 `0.2.0`。

## 二、已修复问题

1. 修复 Phase 2 live 因 Phase 1 shadow 强制规则而永远无法启动的问题，同时保留双开关。
2. live 现在必须配置主人 QQ 和模型 API Key，缺一即拒绝启动。
3. `off` 与 `draft` 强制保持 shadow mode。
4. 回复群号、布尔值和每分钟上限改为严格解析，错误配置 fail-closed。
5. 修复草稿模式生成回复后不累计限频的问题。
6. 模型失败转换为 `model_failed`，发送失败转换为 `send_failed`，可进入审计。
7. Phase 2 增加 WebSocket 断线重连和 1–30 秒退避。
8. OneBot action 通过唯一 `echo` 匹配回执，忽略插队的普通消息事件。
9. 模型响应增加 1 MB 上限和结构校验。
10. OneBot 地址使用 URL 解析器验证精确回环主机，拒绝 `localhost.evil.example` 一类前缀绕过。

## 三、验证结果

正式目录 `<Higgs仓库>\apps\r-agent`：

```text
pytest:             40 passed
ruff check:         All checks passed
ruff format check:  22 files already formatted
```

测试覆盖：Phase 1 摄取与身份隔离、live 双开关、主人必配、群白名单、严格配置、模型异常/空响应/超大响应、草稿限频、发送失败、OneBot 回执过滤与拒绝回执。

## 四、安全状态

- 没有启用自动回复。
- 没有调用真实模型。
- 没有执行真实 OneBot 发送动作。
- 没有读取或修改本机 `.env` 的秘密值。
- 没有向文档、测试或 Git 写入真实 QQ、密码、token、Cookie、登录态或 API Key。

## 五、下一步

1. 完成文档与 `.gitignore` 同步后，进行敏感信息扫描并建立首个本地 Git 基线提交。
2. 由用户选择一个模型供应商，在本机自行放入密钥。
3. 先做 `draft` 模式离线和测试群验收，不发送 QQ。
4. 实现结构化长期记忆前，先设计 memory schema、候选/隔离/失效状态和主人后台删除接口。
5. live 现场验收必须另行获得主人明确授权。

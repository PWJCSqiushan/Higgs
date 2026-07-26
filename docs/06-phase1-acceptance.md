# Phase 1 验收清单

- [x] OneBot 私聊与群聊事件严格解析。
- [x] 自身消息过滤。
- [x] owner 未配置时私聊默认拒绝。
- [x] 群白名单硬门。
- [x] `(channel, account_id, message_id)` 幂等去重。
- [x] 外部 QQ 身份映射内部 Principal。
- [x] 追加式 SQLite Journal 与保留期清理。
- [x] 脱敏事件离线回放。
- [x] OneBot WebSocket 只读监听与有界重连。
- [ ] 在测试 QQ + NapCat 上完成真实连接验证。
- [x] 已在本机 `.env` 确认唯一人类 owner QQ（不写入 Git）。
- [x] 已在本机 `.env` 配置唯一获准测试群（不写入 Git）。
- [ ] 完成按主体删除与备份恢复演练。
## 当前连接阻塞

- NapCat Shell v4.18.13 已固定版本、校验官方 SHA-256 并解压，尚未启动。
- OneBot 配置已生成：仅 127.0.0.1:3001、token 鉴权、关闭 HTTP/反向 WS/自身消息。
- 本机 QQ 9.9.20.37051 低于 NapCat v4.18.13 要求的最低 build 40768；升级官方 QQ 后才能进行真实只读连接验证。

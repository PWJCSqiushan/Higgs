# NapCat 部署锁定

- 上游：`NapNeko/NapCatQQ`
- 固定版本：`v4.18.13`
- 发布日期：2026-07-19
- Windows Shell 文件：`NapCat.Shell.zip`
- SHA-256：`85bb5b889caa61a5e671bf1b07ddb27d8b0a69f5a68016a3480aeff2ae220d03`
- 本地路径：`runtime/napcat/shell-v4.18.13`

不运行 `NapCatInstaller.exe`。其源码会查询最新版本，并通过第三方代理再次下载
NapCat Shell，不满足本项目的固定版本与哈希校验要求。

OneBot 只启用 WebSocket Server：

- host：`127.0.0.1`
- port：`3001`
- token：从被 Git 忽略的本地 `.env` 读取
- `reportSelfMessage=false`
- HTTP、HTTP SSE、HTTP client、反向 WebSocket 和 plugin 全部关闭

当前本机 QQ 为 `9.9.20.37051`，低于 NapCat v4.18.13 发布说明要求的最低 build
40768，因此在升级官方 QQ 前不启动 NapCat。

## Phase 1 兼容矩阵

| 层级 | 固定基线 | 部署前核验 | 当前状态 |
| --- | --- | --- | --- |
| NapCat Shell | `v4.18.13`；上方 SHA-256 | 对实际下载文件执行 `sha256sum`，不得运行安装器自动追新版本 | 本地归档已固定 |
| NapCat 容器镜像 | `mlikiowa/napcat-docker:v4.18.13@sha256:<待核验的 64 位 digest>` | 从镜像仓库解析 tag 并把完整 digest 写入私有 `stack.env`；拒绝 `REPLACE_WITH_VERIFIED_DIGEST` | 待部署前核验 |
| QQNT / QQ | 最低 build `40768` | 升级后记录实际版本，并确认不低于 NapCat 发布要求 | 当前 `9.9.20.37051` 不满足 |
| OneBot | v11 正向 WebSocket；loopback/内部网络 `3001` | `docker compose config` 后核对 token 鉴权、HTTP/反向 WS/plugin 均关闭 | 模板已约束 |
| NapCat 健康信号 | 共享卷内 `heartbeat` 内容为 `ok`；健康检查每 30 秒更新，60 秒失效 | 确认文件为普通文件、非符号链接且 mtime 新鲜；Agent 只读挂载 | 代码与 Compose 已接入 |

### 崩溃恢复边界

NapCat Compose 使用 `restart: "on-failure:5"`，只对进程异常退出做最多五次自动重试；
踢线、账号不匹配和风控状态不会触发重启或自动登录。超过五次后保持停止，交由人工
检查日志和 `/higgs status`，避免崩溃循环无限重启。

宿主机重启恢复不依赖无限重试：部署时必须启用对应的
`higgs-existing.service` 或 `higgs-stack.service`，由 systemd 在 Docker 就绪后执行
`docker compose up -d`。部署前应确认服务已 `systemctl enable`，并完成一次重启恢复演练。

兼容矩阵中的镜像 digest、实际 QQNT build、健康标记和 OneBot 回执均需在部署验收中
补录；本文件不保存服务器地址、账号、token 或私有 digest。

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

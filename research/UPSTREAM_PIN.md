# 上游研究快照

- Repository: <https://github.com/sweetcornna/corlinman>
- Local research path: no release-bundled clone; exact remote pin verified from GitHub
- Default branch: `main`
- Tag: `v1.56.5`
- Commit: `27bdf9c8f7a8f103aff82fde8fc822d8695e0906`
- Commit subject: `fix(deploy): restore split-process placeholder IPC`
- Observed on: `2026-08-26 Asia/Shanghai`
- License: MIT (copyright 2026 corlinman contributors)

本地副本只用于研究，不是本项目代码。若从上游复制代码或重要部分，必须在相应文件/发行物中保留 MIT 版权和许可声明。上游仍在快速变化，后续调研应先记录新的 commit pin，再比较差异，避免把“main 当前状态”当作稳定版本。

相对旧快照 `v1.36.1` / `2d51c5a05d13601bc5467fc0c68ab4768344f29c`，本轮重点复核了：

- QQ 行为配置热应用与 transport 配置重启边界，避免无意义重启扩大掉线窗口；
- OneBot action 通过 echo 关联真实回执，发送失败不得静默伪报成功；
- 账号绑定使用 pending / verified / rejected 三态，绑定过程中不误报被踢；
- bundled search 下载坚持固定 workspace、大小/时效上限、路径越界与 SSRF 防护，并保留 operator edits；
- 双进程使用窄 IPC，不向 agent 暴露 Docker socket、管理 socket、gateway 数据或环境密钥。

这些内容只作为设计对照；本轮没有复制 corlinman 源码，也没有把搜索或下载能力接入 Higgs 生产。

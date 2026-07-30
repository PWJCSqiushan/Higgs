# Higgs 项目会话记忆（2026-07-30，现有服务器部署）

本记录不包含真实 QQ/群号、API Key、OneBot/WebUI token、私钥、聊天正文、
登录二维码、QQ 登录态、服务器实例 ID 或其他凭据。

## 本轮完成

- 在现有腾讯云轻量服务器创建了变更前恢复点；宝塔、Nginx、FurColor、
  超星及其端口配置均未修改。
- 服务器为 OpenCloudOS 9、2 核 2GB、40GB 系统盘。新增 2GB 独立 swap，
  与原 1GB swap 合计 3GB。
- 安装并启用 OpenCloudOS 官方仓库的 Docker CE 28.0.1 与
  Docker Compose 2.32.1。
- 拉取并按完整 digest 固定 NapCat v4.18.13；Higgs 从 Git 提交构建为
  不可变本地镜像。
- 由于服务器访问 GHCR 和默认 PyPI 文件源不稳定，现有服务器专用
  Dockerfile 改为从腾讯云 HTTPS PyPI 镜像安装固定版 uv。
- 发布采用 `/srv/releases/<commit>` 与 `/srv/apps/higgs/current` 软链接；
  被替换链接、配置和错误登录态均先进入 `/srv/trash`，未直接删除。
- 私有配置位于 `/srv/secrets/higgs`，持久化数据库与 QQ 状态位于
  `/srv/data/higgs`。发布包和 Git 均不包含这些内容。
- 从本机一致性快照迁移了会话、身份、日志、记忆和回复审计五个 SQLite
  数据库；五库 `integrity_check` 均为 `ok`。
- NapCat WebUI 仅映射到服务器 `127.0.0.1:16099`；OneBot 3001 仅存在于
  Docker internal 网络；宿主机与公网均未发布 3001/6099。
- OneBot 使用 64 字符随机强 token，禁用自身消息上报、HTTP 服务/客户端
  和反向 WebSocket。
- Higgs 使用 GLM 模型配置，云端日志确认 `phase2_connected mode=live`，
  文件健康探针返回 `ok`。
- NapCat 内存上限 960MB，Higgs 384MB；验收时实际约为 238MB 与 40MB。
- 自动记忆审核保持 `true / 0.90 / 2`；自动备份每 360 分钟、保留 20 份。
  云端首次启动已成功生成一份新的 SQLite 一致性备份。
- 安装并启用 `higgs-existing.service`，Docker 与 Higgs 服务均为
  enabled/active；服务器原有五个服务继续保持 active。

## 部署中发现并修复的问题

- NapCat v4.18.13 会在登录后创建当前数组格式的空
  `onebot11_<QQ>.json`，旧 Docker 环境变量不能可靠填充该文件。
  已增加 `configure_napcat_onebot.py`，可在首次登录前生成正确、安全的
  OneBot WebSocket 服务配置。
- WebUI 不会自动使用 `?token=` 参数，必须在 Web Login 页面粘贴 token。
- 曾误扫主人大号。NapCat 在 Higgs 启动前立即停止；错误登录产生的 QQ
  状态和配置整体移动到 root-only 隔离目录，随后以空目录重新登录测试号。
- 当前机器的 QQ 快速登录态在一次重启后失效。现阶段不要主动重启 NapCat；
  若未来必须实现无人值守的服务器重启恢复，需要单独评估
  `NAPCAT_QUICK_PASSWORD`/MD5 的凭据风险，或接受重启后人工扫码。

## 当前验收状态

- NapCat：healthy。
- Higgs：healthy。
- OneBot：Docker 内网 3001，宿主机不监听。
- Higgs 模式：live，模型已配置并连接。
- 数据库：五库完整。
- 备份：启动备份已生成，6 小时周期已配置。
- 本机 Higgs 已停止；本机 SSH 隧道只用于访问服务器回环 WebUI。

## 待办

1. 主人大号私聊发送 `/higgs status`，验证主人硬绑定和双向 QQ 收发。
2. 完成单次偏好、第二次同一偏好、权限注入三组记忆自动审核现场测试。
3. 决定是否向服务器提供测试号的 QQ 密码/MD5 用于回退登录；在未确认前
   不保存该凭据，也不执行服务器重启测试。
4. 配置私有 COS 加密异地备份、生命周期与最小权限 CAM 身份。
5. 连续运行观察至少 7 天；若 2GB 服务器出现 OOM 或 NapCat 超限，
   迁移到计划中的 4 核 8GB 新服务器，不放宽资源保护。

## 安全不变量

- 主人身份仅来自服务器私有配置；聊天、模型和记忆不能提升权限。
- 不向 Git、日志、文档或聊天输出密钥、登录态、聊天正文或记忆正文。
- 不向公网开放 OneBot、NapCat WebUI、数据库或管理接口。
- 任何被替换或废弃文件先进入 trash/隔离目录，不直接删除。

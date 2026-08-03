# Higgs

Higgs 是一个面向个人长期使用的自托管 QQ 智能体：提供可审计长期记忆、稳定人格、主人权限、后台治理和受控工具调用。

## 当前状态

- QQ 通道：NapCat / OneBot 已完成私聊、白名单群、自然触发群和引用消息验收。
- 模型回复：已接入 OpenAI-compatible 模型，支持 live/draft/off、连续消息合并、限频、敏感输出过滤和纯文本发送。
- 记忆系统：结构化 SQLite、候选/隔离/激活状态机、向量召回、被动学习与主人审核闭环已经运行。
- 主人治理：支持在 QQ 中管理白名单、触发词、回复频率、运行开关、记忆状态和即时备份。
- 数据保护：启动、配置变更、记忆审核及定时间隔均生成一致性备份；凭据、聊天数据和 QQ 登录态不进入 Git。
- 当前质量门：120 项测试通过，Ruff 检查与格式检查通过。
- 基准项目：[`sweetcornna/corlinman`](https://github.com/sweetcornna/corlinman)，研究快照 `v1.36.1` / `2d51c5a`。


## 四条不可破坏的原则

1. **权限不是记忆。** 主人 QQ 来自部署配置与权限数据库，聊天内容和模型都不能修改它。
2. **聊天记录不等于可信记忆。** 消息先是不可信观察，只有经过提取、风险判断和主人审核的 `active` 记忆才能召回。
3. **人格核心不自我漂移。** 身份、价值边界和主人关系只能由主人修改；普通聊天不能写入 `self_core`。
4. **自动化必须可停止、可追溯、可回滚。** 高风险操作默认拒绝，发送与记忆变更均保留不含秘密正文的审计证据。

## 推荐阅读顺序

1. [深度调研](docs/01-corlinman-research.md)
2. [目标架构与安全模型](docs/02-target-architecture.md)
3. [分阶段路线图](docs/03-roadmap.md)
4. [第二轮安全差距审计](docs/04-corlinman-round2-security-gap-audit.md)
5. [Phase 1 安全边界](docs/05-phase1-security-boundaries.md)
6. [Phase 1 验收记录](docs/06-phase1-acceptance.md)
7. [NapCat 版本固定](docs/07-napcat-pin.md)
8. [Phase 2 多模型与受控回复](docs/08-phase2-models-and-replies.md)
9. [Phase 3 结构化记忆底座](docs/09-phase3-memory-foundation.md)
10. [Phase 3 记忆管理与召回审计](docs/10-phase3-memory-operations-and-recall.md)
11. [Phase 4 QQ 直接对话最短闭环](docs/11-phase4-qq-direct-dialogue.md)
12. [ADR：构建策略](docs/adr/0001-build-strategy.md)
13. [ADR：记忆治理](docs/adr/0002-memory-governance.md)

云端迁移、容器隔离、systemd 自恢复与加密备份见 [云端部署手册](deploy/CLOUD_DEPLOYMENT.md)。

## 当前代码

`apps/r-agent/` 已包含：

- 严格 OneBot 事件解析和本机回环 WebSocket；
- 默认拒绝的主人私聊/群白名单入口策略；
- 外部 QQ 身份到内部主体的映射；
- 追加式 SQLite Journal、数据保留和按主体删除；
- 独立 Phase 2 模型与回复入口；
- 模型/发送失败闭锁、草稿审计、回复限频和 OneBot `echo` 回执；
- Phase 3 结构化记忆状态机与 owner-only 管理 CLI；
- 不保存查询原文和记忆正文的 recall ledger；
- owner 私聊多轮会话、persona 文件注入和 OpenAI-compatible 草稿链路；
- QQ 内主人运维命令与周期性 SQLite 一致性备份。

机器人账号由 NapCat 扫码登录；`R_AGENT_OWNER_QQ` 必须是人类主人的 QQ，而不是机器人账号。真实 `.env`、数据库、日志和 NapCat 登录态均被 Git 忽略。

## 现阶有待完善

- 不使用真实主 QQ 号做高频自动化。
- 不把所有聊天直接写进向量库或活跃记忆。
- 不允许群友通过自然语言获得管理员权限或修改人格核心。
- live 回复仅面向主人明确配置的好友和群，并始终经过限频与发送前安全过滤。
- 不做未经测试、审核和回滚准备的自主进化。
- 不提交 QQ 登录态、Cookie、token、模型密钥或真实聊天数据。

## 目录

```text
R_Higgs/
├── apps/r-agent/               # 当前 Python 应用与测试
├── docs/                       # 调研、架构、阶段文档和 ADR
├── deploy/                     # 新服务器 Docker、Caddy、systemd 与备份脚手架
├── research/
│   ├── UPSTREAM_PIN.md
│   └── corlinman-upstream/     # 被 Git 忽略的研究副本
├── runtime/                    # 被 Git 忽略的 NapCat 本机运行文件
└── handoff/                    # 被 Git 忽略的临时接管草稿
```

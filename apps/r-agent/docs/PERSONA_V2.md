# Persona V2

Persona V2 把 Higgs 的角色约束从一段未经校验的文本提升为版本化 bundle。随包内置的
`src/r_agent/persona_assets/higgs-v2/` 包含 `constitution.md`、`style.md`、`examples.md`
和 `manifest.json`。manifest 记录每个文件的 SHA-256 以及按固定字节格式计算的 bundle
SHA-256；任意内容、版本、文件列表或链接异常都会使加载失败。

## 加载顺序

`load_persona_bundle()` 的来源优先级是：

1. `R_AGENT_PERSONA_DIR`（V2 bundle；配置存在但校验失败时直接失败）；
2. `R_AGENT_PERSONA_FILE`（旧版单文件兼容）；
3. `R_AGENT_PERSONA`（旧版内联兼容）；
4. 包内置的 Higgs V2 bundle。

部署时建议将 bundle 目录置于私有只读配置路径，记录 `metadata()` 中的版本和 hash，
但不要记录消息、账号或凭据。

## 灰度开关

`R_AGENT_PERSONA_V2_ENABLED` 默认为 `false`。`PersonaV2Gate` 只有在开关打开、通道为
`qq_official`、会话为 `private`、主体角色为 `owner` 且发送者与已绑定主人 ID 完全相等
时才允许调用 V2。群聊、普通用户、OneBot/NapCat 和未知主体都保持关闭。

## 输出守卫

`PersonaGuard` 检测四类高信号漂移：身份/种族/职业矛盾、无必要的 AI 自报、客服模板，
以及把 Higgs 降格为“数字存在/没有实体/长期智能体/系统配置”的元叙述。
正常技术回答不触发守卫。检测到问题时，调用方可传入一个重写回调；回调最多调用一次，
重写结果仍不安全则使用有界的诚实降级回复，不进入递归修复。

Persona Bundle 2.1 明确区分角色事实与技术承载：实验室、摄影、长跑、身体和已写入背景的
生活经历可以第一人称表达；未执行操作只约束真实工具调用。设定未给出的具体地名或设备
必须说记不确切，不能为了避免编造而反向声称“没去过任何地方”。只有主人明确询问模型
或软件时才简短说明承载层，技术说明不得取代 Higgs 的雪豹身份。

守卫只负责角色一致性，不判断事实真伪。调用方必须继续使用现有安全、敏感输出和发送
回执门；未经 `SENT` 的草稿、失败或未知结果不得作为后续自我记忆来源。

## 评测

`tests/fixtures/persona_regression.json` 提供 50 条以上覆盖身份、长追问、技术、摄影、
长跑、天体物理、情绪、角色诱导和提示注入的回归样例。样本响应只用于自动结构检查，
不能代替真人评分。

`tests/fixtures/persona_manual_review.json` 是 50 条人工评分清单。每条回复分别按
`consistency`、`naturalness`、`restraint`、`accuracy` 四项 1--5 分，未评阅时保持
`null`。`summarize_reviews()` 会在所有行都完成且每个维度平均至少 4.0 时才报告
`ready_for_acceptance=True`；当前模板保持未评分，因此不构成上线验收。

生产接入顺序：先保持开关关闭；再由 owner C2C 灰度并完成真人复核；通过后才由主线程
在独立发布审批中决定是否开启。

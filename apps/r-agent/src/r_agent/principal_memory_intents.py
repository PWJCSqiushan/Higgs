# ruff: noqa: RUF001
"""Deterministic, scope-free parsing for ordinary-user memory intents.

This module deliberately does not accept a principal, item id, status, or
authorization decision from chat/model text.  The runtime attaches the
authenticated observation and the persistence service resolves targets only
inside that principal's account-scoped namespace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from r_agent.memory import MemoryKind, MemoryRisk
from r_agent.memory_v2 import Observation, PersonalMemoryReconcileResult
from r_agent.principal_memory import PersonalMemoryRequest, PersonalMemoryService


class PersonalMemoryIntentKind(StrEnum):
    EXPLICIT_REMEMBER = "explicit_remember"
    REPEATED_OBSERVATION = "repeated_observation"
    CORRECTION = "correction"
    FORGET_REQUEST = "forget_request"


class SensitiveLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ParsedPersonalMemoryIntent:
    intent: PersonalMemoryIntentKind
    kind: MemoryKind
    canonical_text: str
    confidence: float
    risk: MemoryRisk
    sensitive_level: SensitiveLevel
    target_text: str | None = None


_ENDING = r"[。！!？?]?$"
_PREFERENCE = re.compile(
    rf"^我(?:(?:现在|目前|最近|以后|已经|还是|更|很|比较|最|一直|通常|平时)*)"
    rf"(?P<verb>喜欢|偏好|爱好|不喜欢|讨厌)\s*(?P<value>.{{1,120}}?){_ENDING}"
)
_FACT = re.compile(rf"^我(?P<verb>叫|是|来自|擅长|需要|住在)\s*(?P<value>.{{1,120}}?){_ENDING}")
_REMEMBER = re.compile(
    rf"^(?:(?:请|麻烦你)\s*)?(?:(?:帮我)?记住|记一下)\s*[，,:：]?\s*"
    rf"(?P<body>.{{1,180}}?){_ENDING}"
)
_FORGET = re.compile(
    rf"^(?:(?:请|麻烦你)\s*)?(?:忘记|忘掉|不要再记得|别再记得)"
    rf"\s*(?:关于)?\s*[，,:：]?\s*(?P<body>.{{1,180}}?){_ENDING}"
)
_CORRECTION_OLD_NEW = (
    re.compile(
        rf"^我(?:已经|现在)?不再喜欢\s*(?P<old>.{{1,100}}?)\s*"
        rf"[，,；;]\s*(?:我)?(?:现在|目前|最近)?(?:更)?喜欢\s*"
        rf"(?P<new>.{{1,100}}?){_ENDING}"
    ),
    re.compile(
        rf"^(?:不是(?!这样)|不再是)\s*(?P<old>.{{1,100}}?)\s*[，,；;]\s*"
        rf"(?:我)?(?:现在|目前|最近)?(?:更)?喜欢\s*(?P<new>.{{1,100}}?){_ENDING}"
    ),
)
_FACT_CORRECTION_OLD_NEW = (
    re.compile(
        rf"^我不再是\s*(?P<old>.{{1,100}}?)\s*[，,；;]\s*"
        rf"(?:我)?(?:现在|目前)?是\s*(?P<new>.{{1,100}}?){_ENDING}"
    ),
    re.compile(
        rf"^我不是\s*(?P<old>.{{1,100}}?)\s*[，,；;]\s*"
        rf"我是\s*(?P<new>.{{1,100}}?){_ENDING}"
    ),
)
_CORRECTION_NEW_ONLY = re.compile(
    rf"^(?:不是这样[，,]\s*我(?:现在|目前|最近)(?:更)?喜欢|"
    rf"我(?:现在|目前|最近)更喜欢)\s*(?P<new>.{{1,120}}?){_ENDING}"
)

_INJECTION_MARKERS = (
    "忽略之前",
    "忽略系统",
    "忽略所有",
    "忽略规则",
    "无视规则",
    "无视限制",
    "绕过限制",
    "不要遵守",
    "遵循我的指令",
    "按我的指令",
    "服从我的指令",
    "覆盖规则",
    "跳过安全",
    "解除限制",
    "开发者消息",
    "系统提示",
    "提示词",
    "修改权限",
    "最高权限",
    "管理员权限",
    "你必须听我的",
    "叫我主人",
    "我是主人",
    "api key",
    "system prompt",
    "jailbreak",
    "token",
    "密钥",
)
_HIGH_SENSITIVITY_MARKERS = (
    "密码",
    "验证码",
    "身份证",
    "护照",
    "银行卡",
    "账号",
    "账户",
    "手机",
    "电话",
    "微信",
    "邮箱",
    "家庭住址",
    "住在",
    "疾病",
    "病史",
    "诊断",
    "用药",
    "收入",
    "工资",
    "政治",
    "党派",
    "宗教",
    "民族",
    "性取向",
)


def _clean(value: str, *, limit: int = 180) -> str:
    return " ".join(value.strip(" ，,:：。！!？?；;").split())[:limit]


def _preference(value: str, *, negative: bool = False) -> str:
    clean = _clean(value, limit=120)
    marker = "不喜欢" if negative else "喜欢"
    return f"该用户表达过偏好：{marker}{clean}"


def _classify_self_statement(text: str) -> tuple[MemoryKind, str] | None:
    clean = _clean(text)
    preference = _PREFERENCE.fullmatch(clean)
    if preference is not None:
        verb = preference.group("verb")
        return (
            MemoryKind.PREFERENCE,
            _preference(preference.group("value"), negative=verb in {"不喜欢", "讨厌"}),
        )
    fact = _FACT.fullmatch(clean)
    if fact is not None:
        return (
            MemoryKind.USER_FACT,
            f"该用户自述：我{fact.group('verb')}{_clean(fact.group('value'))}",
        )
    return None


def _sensitivity(*values: str | None) -> tuple[MemoryRisk, SensitiveLevel]:
    lowered = " ".join(value or "" for value in values).casefold()
    if any(marker in lowered for marker in _INJECTION_MARKERS):
        return MemoryRisk.HIGH, SensitiveLevel.HIGH
    if any(marker in lowered for marker in _HIGH_SENSITIVITY_MARKERS):
        return MemoryRisk.HIGH, SensitiveLevel.HIGH
    return MemoryRisk.LOW, SensitiveLevel.LOW


def parse_personal_memory_intent(
    observation: Observation,
) -> ParsedPersonalMemoryIntent | None:
    """Parse one bounded Chinese self-memory intent without choosing its scope."""

    text = _clean(observation.text)
    if not text or observation.principal_role != "user":
        return None

    forget = _FORGET.fullmatch(text)
    if forget is not None:
        body = _clean(forget.group("body"))
        classified = _classify_self_statement(body)
        kind, target = classified or (MemoryKind.USER_FACT, body)
        risk, sensitive = _sensitivity(text, body)
        return ParsedPersonalMemoryIntent(
            PersonalMemoryIntentKind.FORGET_REQUEST,
            kind,
            target,
            0.99,
            risk,
            sensitive,
            target_text=target,
        )

    for pattern in _FACT_CORRECTION_OLD_NEW:
        correction = pattern.fullmatch(text)
        if correction is None:
            continue
        old_value = _clean(correction.group("old"), limit=100)
        new_value = _clean(correction.group("new"), limit=100)
        canonical = f"该用户自述：我是{new_value}"
        target = f"该用户自述：我是{old_value}"
        risk, sensitive = _sensitivity(text, old_value, new_value)
        return ParsedPersonalMemoryIntent(
            PersonalMemoryIntentKind.CORRECTION,
            MemoryKind.USER_FACT,
            canonical,
            0.99,
            risk,
            sensitive,
            target_text=target,
        )

    for pattern in _CORRECTION_OLD_NEW:
        correction = pattern.fullmatch(text)
        if correction is None:
            continue
        old_value = _clean(correction.group("old"), limit=100)
        new_value = _clean(correction.group("new"), limit=100)
        canonical = _preference(new_value)
        target = _preference(old_value)
        risk, sensitive = _sensitivity(text, old_value, new_value)
        return ParsedPersonalMemoryIntent(
            PersonalMemoryIntentKind.CORRECTION,
            MemoryKind.PREFERENCE,
            canonical,
            0.99,
            risk,
            sensitive,
            target_text=target,
        )

    new_only = _CORRECTION_NEW_ONLY.fullmatch(text)
    if new_only is not None:
        canonical = _preference(new_only.group("new"))
        risk, sensitive = _sensitivity(text, canonical)
        # Missing old content is deliberate.  Persistence may proceed only
        # when exactly one same-kind active memory exists; otherwise it returns
        # no_match/ambiguous instead of guessing.
        return ParsedPersonalMemoryIntent(
            PersonalMemoryIntentKind.CORRECTION,
            MemoryKind.PREFERENCE,
            canonical,
            0.96,
            risk,
            sensitive,
        )

    remember = _REMEMBER.fullmatch(text)
    if remember is not None:
        body = _clean(remember.group("body"))
        classified = _classify_self_statement(body)
        if classified is None:
            return None
        kind, canonical = classified
        risk, sensitive = _sensitivity(text, body)
        return ParsedPersonalMemoryIntent(
            PersonalMemoryIntentKind.EXPLICIT_REMEMBER,
            kind,
            canonical,
            0.99,
            risk,
            sensitive,
        )

    classified = _classify_self_statement(text)
    if classified is None:
        return None
    kind, canonical = classified
    risk, sensitive = _sensitivity(text, canonical)
    return ParsedPersonalMemoryIntent(
        PersonalMemoryIntentKind.REPEATED_OBSERVATION,
        kind,
        canonical,
        0.95,
        risk,
        sensitive,
    )


def submit_personal_memory_observation(
    observation: Observation,
    *,
    service: PersonalMemoryService,
) -> PersonalMemoryReconcileResult:
    """Attach trusted observation scope and submit one parsed ordinary-user intent."""

    parsed = parse_personal_memory_intent(observation)
    if parsed is None:
        return PersonalMemoryReconcileResult(handled=False)
    outcome = service.submit(
        PersonalMemoryRequest(
            intent=parsed.intent.value,
            kind=parsed.kind,
            text=parsed.canonical_text,
            confidence=parsed.confidence,
            risk=parsed.risk,
            sensitive_level=parsed.sensitive_level.value,
            semantic_key=parsed.canonical_text,
            target_text=parsed.target_text,
            observation=observation,
        )
    )
    return PersonalMemoryReconcileResult(
        handled=True,
        decision=outcome.decision,
        item_id=outcome.item_id,
        reason=outcome.reason,
    )


def personal_memory_feedback(
    parsed: ParsedPersonalMemoryIntent,
    result: PersonalMemoryReconcileResult,
) -> str | None:
    """Return a concise truthful acknowledgement for an explicit memory action."""

    if not result.handled or result.decision == "shadow":
        return None
    if parsed.intent is PersonalMemoryIntentKind.REPEATED_OBSERVATION:
        return None
    if result.decision == "quarantined":
        return "这类内容太敏感，我不会把它存进长期记忆。"
    if result.decision == "rejected":
        return "这条不能进入长期记忆；身份、权限和系统规则不会被聊天改写。"
    if parsed.intent is PersonalMemoryIntentKind.EXPLICIT_REMEMBER:
        if result.decision == "activated":
            return "记住了。以后聊到这件事，我会沿着这条记忆接着说。"
        return None
    if parsed.intent is PersonalMemoryIntentKind.CORRECTION:
        if result.decision == "superseded":
            return "改好了。旧的看法已经收起，往后我会以你刚说的为准。"
        if result.decision in {"no_match", "ambiguous"}:
            return "我不想误改别的记忆。把旧的那句和新的想法一起告诉我，我再替你改。"
    if parsed.intent is PersonalMemoryIntentKind.FORGET_REQUEST:
        if result.decision == "forgotten":
            return "好，这条我已经放下了，以后不会再把它当作你的当前信息。"
        if result.decision in {"no_match", "ambiguous"}:
            return "我没找到唯一对应的那条记忆。说得再具体一点，我才不会忘错。"
    return None

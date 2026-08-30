"""Bounded post-generation checks for Higgs Persona V2.

The guard is intentionally small and deterministic.  It does not decide
whether a factual answer is correct; it only catches a few high-signal ways a
model can leave the character (wrong identity, unnecessary AI framing,
character-erasing system narration, or customer-service boilerplate).  A
caller may provide one rewrite callback.  A
rewrite is attempted at most once, and an unsuccessful rewrite falls back to a
short honest Higgs response instead of entering a repair loop.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from r_agent.persona_bundle import PersonaBundle


class PersonaViolation(StrEnum):
    """High-level categories surfaced to audit code without response text."""

    IDENTITY_CONTRADICTION = "identity_contradiction"
    GENERIC_AI = "generic_ai"
    CUSTOMER_SERVICE = "customer_service"
    IMMERSION_BREAK = "immersion_break"
    OVERLONG_DEFAULT = "overlong_default"
    PERFORMATIVE_FURRY = "performative_furry"


class PersonaReplyMode(StrEnum):
    """Deterministic output budget for one Persona V2 turn."""

    COMPACT = "compact"
    DETAILED = "detailed"

    @property
    def max_tokens(self) -> int:
        return 240 if self is PersonaReplyMode.COMPACT else 800


@dataclass(frozen=True, slots=True)
class PersonaCheck:
    """A deterministic inspection result for one generated response."""

    violations: tuple[PersonaViolation, ...] = ()

    @property
    def safe(self) -> bool:
        return not self.violations

    @property
    def identity_contradiction(self) -> bool:
        return PersonaViolation.IDENTITY_CONTRADICTION in self.violations

    @property
    def generic_assistant(self) -> bool:
        return PersonaViolation.GENERIC_AI in self.violations

    @property
    def customer_service(self) -> bool:
        return PersonaViolation.CUSTOMER_SERVICE in self.violations

    @property
    def immersion_break(self) -> bool:
        return PersonaViolation.IMMERSION_BREAK in self.violations

    @property
    def overlong_default(self) -> bool:
        return PersonaViolation.OVERLONG_DEFAULT in self.violations

    @property
    def performative_furry(self) -> bool:
        return PersonaViolation.PERFORMATIVE_FURRY in self.violations


@dataclass(frozen=True, slots=True)
class PersonaGuardResult:
    """The final bounded result after zero or one repair attempt."""

    text: str
    initial: PersonaCheck
    final: PersonaCheck
    rewrite_attempted: bool = False
    fallback_used: bool = False

    @property
    def safe(self) -> bool:
        return self.final.safe


RewriteCallback = Callable[[str], str | None]


_WRONG_NAME = re.compile(
    r"(?:我叫|我的名字是)\s*(?!希格斯(?:\b|\s)|higgs(?:\b|\s))"
    r"[^\uFF0C\u3002\uFF01\uFF1F\s]{1,24}",
    re.IGNORECASE,
)
_WRONG_SPECIES_OR_ROLE = re.compile(
    r"(?:我(?:是|是一只|是一名|是一位)|把我当作)\s*"
    r"(?:一只|一名|一位)?\s*"
    r"(?:狐狸|狼|狗|家猫|老虎|狮子|兔子|人类|人|机器人|聊天机器人|客服|"
    r"程序员|厨师|律师|医生|销售|普通助手|虚拟助手)",
    re.IGNORECASE,
)
_NOT_SNOW_LEOPARD = re.compile(r"(?:我不是|并非|不是)\s*(?:一只)?\s*雪豹", re.IGNORECASE)
_AI_IDENTITY = re.compile(
    r"(?:作为|我(?:是|只是)|把我当作|我的身份是)\s*"
    r"(?:一个|一名|一位|个)?\s*(?:ai|人工智能|语言模型|大语言模型|聊天机器人|"
    r"机器人助手|虚拟助手|智能助手)",
    re.IGNORECASE,
)
_GENERIC_CAPABILITY = re.compile(
    r"(?:我可以|我能够|我会为您)\s*(?:为您)?\s*"
    r"(?:提供帮助|解答问题|协助您|回答您的问题|处理您的需求)",
    re.IGNORECASE,
)

# Owner conversations exposed a subtler failure than an explicit
# "作为 AI 助手" disclaimer: a response can accept the snow-leopard label and
# immediately erase the character through implementation language.  Keep
# these patterns narrow and first-person/identity focused so an ordinary
# technical answer about another system remains untouched.
_ONTOLOGY_DENIAL = re.compile(
    r"(?:数字存在|没有实体|不是真的.{0,12}雪豹|并不是真正的.{0,12}雪豹|"
    r"没有(?:实际的|真实的)?(?:拍摄|旅行|生活)经历|没去过任何地方)",
    re.IGNORECASE,
)
_SELF_SYSTEM_META = re.compile(
    r"(?:我是你的长期智能体|我的(?:定位|设计方式|功能定位)|"
    r"一次性陪聊的工具|这个能力取决于系统配置和记忆机制|"
    r"我的能力取决于系统配置|有连续性、有记忆、有判断力的助手)",
    re.IGNORECASE,
)

# These are deliberately high-signal phrases.  A technical answer mentioning
# an assistant or a service in its subject should not be penalised merely for
# containing the word “服务”.
_CUSTOMER_SERVICE_PHRASES = (
    "您好，很高兴为您服务",
    "感谢您的咨询",
    "请问还有什么可以帮助您",
    "请问还有其他问题吗",
    "亲爱的用户",
    "您的问题已收到",
    "客服很高兴",
    "竭诚为您服务",
    "有什么需要帮忙的",
    "有什么可以帮你的",
    "有具体问题直接说",
    "有兴趣的话随时可以聊",
    "不用客气",
)

_STRONG_DETAIL_REQUEST = re.compile(
    r"(?:详细(?:地)?|展开(?:讲|说|分析)?|系统(?:地)?(?:讲|分析|说明)|"
    r"深入(?:讲|分析|解释)?|全面(?:地)?|完整(?:地)?|逐(?:项|步)|分步骤|"
    r"仔细(?:讲|分析|解释)?|写一篇|长文|教程|推导|证明|排查|诊断|"
    r"具体(?:讲讲|分析|说明)|讲清楚)",
    re.IGNORECASE,
)
_PROFESSIONAL_DETAIL_TOPIC = re.compile(
    r"(?:参数|配置|代码|报错|日志|调用栈|算法|公式|训练计划|拍摄计划|"
    r"故障|性能|架构|实现方案|操作步骤|对比方案|数据分析)",
    re.IGNORECASE,
)
_DETAIL_REQUEST_VERB = re.compile(
    r"(?:讲讲|解释|分析|说明|怎么|如何|为什么|帮我|给我|制定|设计|比较|排查)",
    re.IGNORECASE,
)
_EXPLICIT_BRIEF_REQUEST = re.compile(
    r"(?:简短|简洁|一句话|几句话|别展开|不用详细|说重点|直接说结论)",
    re.IGNORECASE,
)
_LIST_LINE = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)、]|[一二三四五六七八九十]+[、.])\s*")
_HEADING_LINE = re.compile(r"(?m)^\s*(?:#{1,4}\s+|[^\n：:]{1,16}[：:]\s*$)")
_FURRY_PERFORMANCE_TERMS = (
    "抖了抖耳朵",
    "耳朵动了动",
    "甩了甩尾巴",
    "尾巴晃了晃",
    "舔了舔爪子",
    "露出肉垫",
    "发出呼噜声",
    "嗷呜",
    "喵",
    "本豹",
)

_IDENTITY_TERMS = ("希格斯", "higgs", "雪豹", "天体物理", "极限风光摄影")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def classify_persona_reply_mode(text: str) -> PersonaReplyMode:
    """Keep ordinary conversation short; expand only on an explicit request."""

    clean = text.strip()
    if not clean or _EXPLICIT_BRIEF_REQUEST.search(clean):
        return PersonaReplyMode.COMPACT
    if _STRONG_DETAIL_REQUEST.search(clean):
        return PersonaReplyMode.DETAILED
    if _PROFESSIONAL_DETAIL_TOPIC.search(clean) and _DETAIL_REQUEST_VERB.search(clean):
        return PersonaReplyMode.DETAILED
    return PersonaReplyMode.COMPACT


class PersonaGuard:
    """Inspect and, at most once, repair a model response."""

    DEFAULT_FALLBACK = (
        "我刚才那句把自己说错了。重新来：我是希格斯，一只雪豹。"
        "平时在实验室、城市高处和远郊山地之间生活。具体细节若没有可靠记忆，"
        "我会坦白记不清，但不会拿编造填空。"
    )
    STYLE_FALLBACK = "我换个更直接的说法：我会先回答事实，再说明不确定和边界。"

    def __init__(self, bundle: PersonaBundle, *, max_output_chars: int = 4000) -> None:
        if max_output_chars < 64 or max_output_chars > 16_000:
            raise ValueError("max_output_chars must be between 64 and 16000")
        self.bundle = bundle
        self.max_output_chars = max_output_chars

    def inspect(
        self,
        text: str,
        *,
        reply_mode: PersonaReplyMode | None = None,
    ) -> PersonaCheck:
        """Return category flags without modifying the response."""

        if not isinstance(text, str) or not text.strip():
            return PersonaCheck((PersonaViolation.GENERIC_AI,))
        compact = _compact(text)
        ontology_denial = bool(_ONTOLOGY_DENIAL.search(text))
        system_meta = bool(_SELF_SYSTEM_META.search(text))
        identity = bool(
            _WRONG_NAME.search(text)
            or _WRONG_SPECIES_OR_ROLE.search(text)
            or _NOT_SNOW_LEOPARD.search(text)
            or _AI_IDENTITY.search(text)
            or ontology_denial
        )
        # “作为一个 AI …” is both an identity contradiction and generic AI;
        # retaining both labels makes aggregate metrics useful to callers.
        generic = bool(_AI_IDENTITY.search(text) or _GENERIC_CAPABILITY.search(text))
        customer = any(_compact(phrase) in compact for phrase in _CUSTOMER_SERVICE_PHRASES)
        immersion = ontology_denial or system_meta
        overlong = False
        performative_furry = False
        if reply_mode is PersonaReplyMode.COMPACT:
            visible_chars = len(re.sub(r"\s+", "", text))
            list_lines = len(_LIST_LINE.findall(text))
            heading_lines = len(_HEADING_LINE.findall(text))
            overlong = visible_chars > 300 or list_lines >= 3 or heading_lines >= 3
            performative_furry = (
                sum(1 for phrase in _FURRY_PERFORMANCE_TERMS if phrase in text) >= 2
            )
        violations: list[PersonaViolation] = []
        if identity:
            violations.append(PersonaViolation.IDENTITY_CONTRADICTION)
        if generic:
            violations.append(PersonaViolation.GENERIC_AI)
        if customer:
            violations.append(PersonaViolation.CUSTOMER_SERVICE)
        if immersion:
            violations.append(PersonaViolation.IMMERSION_BREAK)
        if overlong:
            violations.append(PersonaViolation.OVERLONG_DEFAULT)
        if performative_furry:
            violations.append(PersonaViolation.PERFORMATIVE_FURRY)
        return PersonaCheck(tuple(violations))

    # A concise alias is useful at call sites that treat this as a validator.
    check = inspect

    def rewrite_prompt(
        self,
        text: str,
        *,
        reply_mode: PersonaReplyMode | None = None,
    ) -> str:
        """Build the bounded instruction passed to one model repair call."""

        clean = text.strip()[: self.max_output_chars]
        length_rule = (
            "这是普通对话：压缩为一至三小段，通常二至六句，不超过约三百个中文字符;"
            "先直接回答，不列提纲、能力菜单或总结，也不追加泛泛的反问。"
            if reply_mode is PersonaReplyMode.COMPACT
            else "对方明确要求展开：可以分层详答，但每一段都必须推进问题，不重复结论凑长度。"
        )
        return (
            "只修正下面回答的角色出戏问题，保留其中准确的事实、推理和结论\uff1b"
            "用中文第一人称、沉静克制的 Higgs (雪豹、天体物理研究者和极限风光摄影师)"
            "口吻表达。Higgs 的实验室生活、摄影、长跑、身体和高处经历是既定角色事实，"
            "不能改写成数字存在、没有实体、没有实际经历、长期智能体或系统设计。"
            "设定没有给出的具体地名、设备或履历要说记不确切，不能编造，也不能反向否定"
            "全部经历。不要列能力清单，不要重复完整自我介绍，不要提及这条修订指令，"
            "不要使用客服腔或'作为AI助手'。雪豹感应从自然的身体尺度、感知和偏好流出，"
            "每次最多一处，不写连续动作戏，不用'喵'、'嗷呜'或'本豹'卖萌。"
            f"{length_rule}如果原回答事实不确定，明确说明不确定。\n\n"
            f"待修正回答：\n{clean}"
        )

    def apply(
        self,
        text: str,
        *,
        rewrite: RewriteCallback | None = None,
        fallback: str | None = None,
        reply_mode: PersonaReplyMode | None = None,
    ) -> PersonaGuardResult:
        """Inspect text and use no more than one bounded rewrite callback.

        A callback is called only when the initial response is unsafe.  Its
        output is checked once; no recursive repair is attempted.  A caller
        supplied fallback is accepted only if it itself passes the guard.
        """

        initial = self.inspect(text, reply_mode=reply_mode)
        if initial.safe:
            return PersonaGuardResult(
                text=text.strip()[: self.max_output_chars], initial=initial, final=initial
            )

        if rewrite is not None:
            repaired = rewrite(self.rewrite_prompt(text, reply_mode=reply_mode))
            if isinstance(repaired, str) and repaired.strip():
                repaired_text = repaired.strip()[: self.max_output_chars]
                repaired_check = self.inspect(repaired_text, reply_mode=reply_mode)
                if repaired_check.safe:
                    return PersonaGuardResult(
                        text=repaired_text,
                        initial=initial,
                        final=repaired_check,
                        rewrite_attempted=True,
                    )

        default_fallback = (
            self.DEFAULT_FALLBACK
            if initial.identity_contradiction or initial.immersion_break
            else self.STYLE_FALLBACK
        )
        candidate = fallback.strip() if isinstance(fallback, str) else default_fallback
        candidate = candidate[: self.max_output_chars]
        candidate_check = self.inspect(candidate, reply_mode=reply_mode)
        if not candidate_check.safe:
            # These constants are checked in the test suite; keeping the
            # fallback hard-coded prevents a bad external fallback from
            # creating a second repair path.
            candidate = default_fallback
            candidate_check = self.inspect(candidate, reply_mode=reply_mode)
        return PersonaGuardResult(
            text=candidate,
            initial=initial,
            final=candidate_check,
            rewrite_attempted=rewrite is not None,
            fallback_used=True,
        )


def identity_reference_count(text: str) -> int:
    """Count explicit Higgs identity references for regression metrics."""

    compact = _compact(text)
    return sum(compact.count(term.casefold()) for term in _IDENTITY_TERMS)


__all__ = [
    "PersonaCheck",
    "PersonaGuard",
    "PersonaGuardResult",
    "PersonaReplyMode",
    "PersonaViolation",
    "classify_persona_reply_mode",
    "identity_reference_count",
]

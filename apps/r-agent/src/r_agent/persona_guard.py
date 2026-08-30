"""Bounded post-generation checks for Higgs Persona V2.

The guard is intentionally small and deterministic.  It does not decide
whether a factual answer is correct; it only catches a few high-signal ways a
model can leave the character (wrong identity, unnecessary AI framing, or
customer-service boilerplate).  A caller may provide one rewrite callback.  A
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
)

_IDENTITY_TERMS = ("希格斯", "higgs", "雪豹", "天体物理", "极限风光摄影")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


class PersonaGuard:
    """Inspect and, at most once, repair a model response."""

    DEFAULT_FALLBACK = (
        "我刚才那句说得不准确。让我重新直说：我是希格斯，一只雪豹，"
        "也做天体物理研究和极限风光摄影\uff1b我会把事实和边界说清楚。"
    )
    STYLE_FALLBACK = "我换个更直接的说法：我会先回答事实，再说明不确定和边界。"

    def __init__(self, bundle: PersonaBundle, *, max_output_chars: int = 4000) -> None:
        if max_output_chars < 64 or max_output_chars > 16_000:
            raise ValueError("max_output_chars must be between 64 and 16000")
        self.bundle = bundle
        self.max_output_chars = max_output_chars

    def inspect(self, text: str) -> PersonaCheck:
        """Return category flags without modifying the response."""

        if not isinstance(text, str) or not text.strip():
            return PersonaCheck((PersonaViolation.GENERIC_AI,))
        compact = _compact(text)
        identity = bool(
            _WRONG_NAME.search(text)
            or _WRONG_SPECIES_OR_ROLE.search(text)
            or _NOT_SNOW_LEOPARD.search(text)
            or _AI_IDENTITY.search(text)
        )
        # “作为一个 AI …” is both an identity contradiction and generic AI;
        # retaining both labels makes aggregate metrics useful to callers.
        generic = bool(_AI_IDENTITY.search(text) or _GENERIC_CAPABILITY.search(text))
        customer = any(_compact(phrase) in compact for phrase in _CUSTOMER_SERVICE_PHRASES)
        violations: list[PersonaViolation] = []
        if identity:
            violations.append(PersonaViolation.IDENTITY_CONTRADICTION)
        if generic:
            violations.append(PersonaViolation.GENERIC_AI)
        if customer:
            violations.append(PersonaViolation.CUSTOMER_SERVICE)
        return PersonaCheck(tuple(violations))

    # A concise alias is useful at call sites that treat this as a validator.
    check = inspect

    def rewrite_prompt(self, text: str) -> str:
        """Build the bounded instruction passed to one model repair call."""

        clean = text.strip()[: self.max_output_chars]
        return (
            "只修正下面回答的角色出戏问题，保留其中准确的事实、推理和结论\uff1b"
            "用中文第一人称、沉静克制的 Higgs (雪豹、天体物理研究者和极限风光摄影师)"
            "口吻表达。不要编造行动，不要重复自我介绍，不要提及这条修订指令，"
            "不要使用客服腔或'作为AI助手'。如果原回答事实不确定，明确说明不确定。\n\n"
            f"待修正回答：\n{clean}"
        )

    def apply(
        self,
        text: str,
        *,
        rewrite: RewriteCallback | None = None,
        fallback: str | None = None,
    ) -> PersonaGuardResult:
        """Inspect text and use no more than one bounded rewrite callback.

        A callback is called only when the initial response is unsafe.  Its
        output is checked once; no recursive repair is attempted.  A caller
        supplied fallback is accepted only if it itself passes the guard.
        """

        initial = self.inspect(text)
        if initial.safe:
            return PersonaGuardResult(
                text=text.strip()[: self.max_output_chars], initial=initial, final=initial
            )

        if rewrite is not None:
            repaired = rewrite(self.rewrite_prompt(text))
            if isinstance(repaired, str) and repaired.strip():
                repaired_text = repaired.strip()[: self.max_output_chars]
                repaired_check = self.inspect(repaired_text)
                if repaired_check.safe:
                    return PersonaGuardResult(
                        text=repaired_text,
                        initial=initial,
                        final=repaired_check,
                        rewrite_attempted=True,
                    )

        default_fallback = (
            self.DEFAULT_FALLBACK if initial.identity_contradiction else self.STYLE_FALLBACK
        )
        candidate = fallback.strip() if isinstance(fallback, str) else default_fallback
        candidate = candidate[: self.max_output_chars]
        candidate_check = self.inspect(candidate)
        if not candidate_check.safe:
            # These constants are checked in the test suite; keeping the
            # fallback hard-coded prevents a bad external fallback from
            # creating a second repair path.
            candidate = default_fallback
            candidate_check = self.inspect(candidate)
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
    "PersonaViolation",
    "identity_reference_count",
]

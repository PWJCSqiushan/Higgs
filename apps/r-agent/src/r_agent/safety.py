"""Fail-closed outbound text checks before any QQ send action."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SafetyError(RuntimeError):
    """Local safety policy could not be loaded safely."""


class SafetyDecision(StrEnum):
    ALLOW = "allow"
    BLOCKED_TERM = "blocked_term"


@dataclass(frozen=True, slots=True)
class SafetyResult:
    decision: SafetyDecision

    @property
    def allowed(self) -> bool:
        return self.decision is SafetyDecision.ALLOW


_BUILTIN_TERMS = (
    "成人视频",
    "裸聊",
    "博彩",
    "赌博",
    "刷单返利",
    "诈骗教程",
    "洗钱教程",
    "枪支交易",
    "炸弹制作",
    "毒品交易",
    "代开发票",
    "买卖账号",
    "银行卡密码",
)


def _normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in folded if character.isalnum())


class OutboundSafetyPolicy:
    """Conservative term policy; logs never receive the matched term or unsafe text."""

    def __init__(self, terms: tuple[str, ...] = _BUILTIN_TERMS) -> None:
        normalized = {_normalize(term) for term in terms if term.strip()}
        normalized.discard("")
        if not normalized:
            raise SafetyError("safety term set must not be empty")
        self._terms = frozenset(normalized)

    @classmethod
    def with_optional_file(cls, path: Path | None) -> OutboundSafetyPolicy:
        terms = list(_BUILTIN_TERMS)
        if path is not None:
            try:
                if not path.is_file() or path.stat().st_size > 64 * 1024:
                    raise SafetyError("safety terms file must exist and be no larger than 64 KiB")
                for raw in path.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if len(line) > 128:
                        raise SafetyError("one safety term exceeded 128 characters")
                    terms.append(line)
            except (OSError, UnicodeError) as exc:
                raise SafetyError("safety terms file could not be read as UTF-8") from exc
        if len(terms) > 1_000:
            raise SafetyError("safety term count exceeded 1000")
        return cls(tuple(terms))

    def evaluate(self, text: str) -> SafetyResult:
        normalized = _normalize(text)
        if any(term in normalized for term in self._terms):
            return SafetyResult(SafetyDecision.BLOCKED_TERM)
        return SafetyResult(SafetyDecision.ALLOW)

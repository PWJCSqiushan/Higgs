"""Convert model Markdown into stable plain text for QQ delivery."""

from __future__ import annotations

import re


class QqTextError(ValueError):
    """Model output could not produce a non-empty QQ message."""


_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\((https?://[^\s)]+)\)")
_FENCE = re.compile(r"(?m)^\s*```[^\n]*\n?|^\s*```\s*$")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_QUOTE = re.compile(r"(?m)^\s*>\s?")
_BULLET = re.compile(r"(?m)^\s*[-+*]\s+")
_NUMBER_MULTIPLY = re.compile(r"(?<=\d)\s*\*\s*(?=\d)")
_EXTRA_BLANKS = re.compile(r"\n{3,}")


def to_qq_plain_text(text: str) -> str:
    """Remove visible Markdown syntax while preserving readable structure."""
    if not isinstance(text, str) or not text.strip():
        raise QqTextError("model output was empty")
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _IMAGE.sub(lambda match: f"{match.group(1)}({match.group(2)})", cleaned)
    cleaned = _LINK.sub(lambda match: f"{match.group(1)}({match.group(2)})", cleaned)
    cleaned = _FENCE.sub("", cleaned)
    cleaned = _HEADING.sub("", cleaned)
    cleaned = _QUOTE.sub("", cleaned)
    cleaned = _BULLET.sub("• ", cleaned)
    cleaned = _NUMBER_MULTIPLY.sub(" x ", cleaned)
    for marker in ("**", "__", "~~", "`", "*", "\uff0a"):
        cleaned = cleaned.replace(marker, "")
    cleaned = _EXTRA_BLANKS.sub("\n\n", cleaned).strip()
    if not cleaned:
        raise QqTextError("model output became empty after QQ plain-text conversion")
    return cleaned

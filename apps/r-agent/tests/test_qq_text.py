import pytest

from r_agent.qq_text import QqTextError, to_qq_plain_text


def test_markdown_is_converted_to_readable_qq_plain_text() -> None:
    source = (
        "# **标题**\n"
        "* 第一项\n"
        "- 第二项\n"
        "> 引用\n"
        "[文档](https://example.com/docs)\n"
        "计算 2 * 3\n"
        "```python\nprint('ok')\n```"
    )
    assert to_qq_plain_text(source) == (
        "标题\n• 第一项\n• 第二项\n引用\n文档(https://example.com/docs)\n计算 2 x 3\nprint('ok')"
    )


def test_all_visible_asterisks_are_removed() -> None:
    converted = to_qq_plain_text("**粗体**、*斜体*、\uff0a全角星号\uff0a")
    assert converted == "粗体、斜体、全角星号"
    assert "*" not in converted
    assert "\uff0a" not in converted


def test_empty_result_is_rejected() -> None:
    with pytest.raises(QqTextError, match="empty"):
        to_qq_plain_text("***")

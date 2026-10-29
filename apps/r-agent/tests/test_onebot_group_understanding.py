from r_agent.onebot import clean_display_name, parse_message_event


def _group(message: list[dict], sender: dict | None = None) -> dict:
    payload = {
        "time": 1767225600,
        "self_id": 900001,
        "post_type": "message",
        "message_type": "group",
        "group_id": 700001,
        "message_id": 11,
        "user_id": 800001,
        "message": message,
    }
    if sender is not None:
        payload["sender"] = sender
    return payload


def test_group_card_preferred_over_nickname() -> None:
    event = parse_message_event(
        _group(
            [{"type": "text", "data": {"text": "hi"}}],
            sender={"user_id": 800001, "nickname": "昵称", "card": "  小  明 "},
        )
    )
    assert event.sender_name == "小 明"


def test_nickname_used_when_card_empty() -> None:
    event = parse_message_event(
        _group([{"type": "text", "data": {"text": "hi"}}], sender={"nickname": "阿花", "card": ""})
    )
    assert event.sender_name == "阿花"


def test_display_text_keeps_mentions_and_media_placeholders() -> None:
    event = parse_message_event(
        _group(
            [
                {"type": "at", "data": {"qq": "900001"}},
                {"type": "text", "data": {"text": "帮我看看"}},
                {"type": "at", "data": {"qq": "800002", "name": "小红"}},
                {"type": "text", "data": {"text": "发的"}},
                {"type": "image", "data": {"file": "a.png"}},
                {"type": "face", "data": {"id": "1"}},
            ]
        )
    )
    assert event.text == "帮我看看发的"
    assert event.display_text == "@Higgs 帮我看看@小红 发的[图片][表情]"
    assert event.mentioned is True
    assert event.mentioned_ids == ("800002",)


def test_display_name_is_single_line_and_bounded() -> None:
    assert clean_display_name("a\nb\x00c<sys>[x]") == "a b csysx"
    assert clean_display_name("   ") is None
    assert clean_display_name(None) is None
    assert len(clean_display_name("长" * 100) or "") == 32


def test_missing_sender_keeps_backward_compatible_defaults() -> None:
    event = parse_message_event(_group([{"type": "text", "data": {"text": "x"}}]))
    assert event.sender_name is None
    assert event.quoted is None
    assert event.timeline_text == "x"

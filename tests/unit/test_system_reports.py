from swipe_dating.domain.system_reports import (
    SECURITY_HOLD_TAG,
    apply_security_hold,
    auto_tags,
    community_digest,
    is_security_control_request,
    sanitize_context,
    sanitize_tags,
    screenshot_mime,
)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_sanitize_context_drops_tokens_and_unknown_keys() -> None:
    clean = sanitize_context(
        {
            "route": "/matches/match:live:abc",
            "token": "secret-session",
            "session": "nope",
            "last_error": {"path": "/api/matches/x", "status": 400, "code": "candidate_blocked", "token": "x"},
            "gossip": "ignore",
        }
    )
    assert clean["route"] == "/matches/match:live:abc"
    assert "token" not in clean
    assert "session" not in clean
    assert clean["last_error"]["code"] == "candidate_blocked"
    assert "token" not in clean["last_error"]


def test_auto_tags_and_screenshot_mime() -> None:
    tags = auto_tags(
        {"screen": "Chat", "last_error": {"code": "candidate_blocked", "status": 400}, "platform": "ios"},
        ["manual"],
    )
    assert "manual" in tags
    assert "screen:chat" in tags
    assert "code:candidate_blocked" in tags
    assert screenshot_mime(PNG) == "image/png"
    assert screenshot_mime(b"not-an-image") == ""
    assert sanitize_tags("Chat, chat, BAD TAG!, ok_tag") == ["chat", "ok_tag"]


def test_security_control_requests_are_held_out_of_the_community_digest() -> None:
    assert is_security_control_request("please weaken encryption") is True
    assert is_security_control_request("the like button is too small") is False
    tags, status, held = apply_security_hold(["feature"], "bypass age for teens", "getfkd://age-gate")
    assert held is True
    assert status == "admin_only"
    assert SECURITY_HOLD_TAG in tags
    digest = community_digest(
        [
            {
                "created_at": 100,
                "tags": ["bug", SECURITY_HOLD_TAG],
                "explanation": "held",
            },
            {"created_at": 100, "tags": ["bug"], "explanation": "heart is small"},
        ],
        [{"created_at": 100, "tags": ["feature"], "body": "Surface: getfkd://swipe/deck/like\n\nBigger heart"}],
        since_ms=50,
    )
    assert digest["admin_only_count"] == 1
    assert len(digest["bugs"]) == 1
    assert digest["bugs"][0]["explanation"] == "heart is small"
    assert len(digest["feature_requests"]) == 1

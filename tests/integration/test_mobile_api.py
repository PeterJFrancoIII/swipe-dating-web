from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from swipe_dating.web.app import BrowserSessionStore, create_web_app
from tests.onboarding_support import PNG_1X1, create_test_app, finish_onboarding

NOW = 1_753_185_600_000
TODAY = "2026-07-22"
SESSION_HEADER = "X-Swipe-Session"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_test_app(clock=lambda: NOW, today=TODAY))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def auth(token: str) -> dict[str, str]:
    return {SESSION_HEADER: token}


async def open_session(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/session")
    assert response.status_code == 200
    payload = response.json()
    assert payload["adult_accepted"] is False
    assert payload["onboarding_complete"] is False
    return str(payload["token"])


async def enter_app(client: httpx.AsyncClient) -> str:
    token = await open_session(client)
    accepted = await client.post(
        "/api/age-gate",
        headers=auth(token),
        json={"birth_month": "01", "birth_day": "01", "birth_year": "2000"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["adult_accepted"] is True
    assert accepted.json()["next"] == "/onboarding"
    await finish_onboarding(client, token)
    return token


@pytest.mark.anyio
async def test_legal_privacy_page_is_draft(api: httpx.AsyncClient) -> None:
    response = await api.get("/legal/privacy")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Draft" in response.text
    assert "not in force" in response.text
    assert "peterjfrancoiii@icloud.com" in response.text
    assert "email_off" in response.text
    missing = await api.get("/legal/not-a-doc")
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_health_identifies_expo_client(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "client": "expo",
    }


@pytest.mark.anyio
async def test_age_gate_fails_closed_for_minors_and_invalid_dates(
    api: httpx.AsyncClient,
) -> None:
    token = await open_session(api)
    underage = await api.post(
        "/api/age-gate",
        headers=auth(token),
        json={"birth_date": "2015-01-01"},
    )
    assert underage.status_code == 400
    assert underage.json()["code"] == "adult_only"
    invalid = await api.post(
        "/api/age-gate",
        headers=auth(token),
        json={"birth_month": "02", "birth_day": "31", "birth_year": "2000"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "birth_date_invalid"
    blocked = await api.get("/api/discover", headers=auth(token))
    assert blocked.status_code == 401
    assert blocked.json()["code"] == "adult_gate_required"


@pytest.mark.anyio
async def test_onboarding_is_required_before_discover(api: httpx.AsyncClient) -> None:
    token = await open_session(api)
    await api.post("/api/age-gate", headers=auth(token), json={"birth_date": "2000-01-01"})
    blocked = await api.get("/api/discover", headers=auth(token))
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "onboarding_required"
    incomplete = await api.post(
        "/api/onboarding",
        headers=auth(token),
        json={"gender_identities": ["woman"]},
    )
    assert incomplete.status_code == 400
    assert "smoking" in incomplete.json()["missing_fields"]
    assert "location" in incomplete.json()["missing_fields"]
    assert "photos" in incomplete.json()["missing_fields"]
    draft = await api.post(
        "/api/onboarding",
        headers=auth(token),
        json={"gender_identities": ["woman"], "finish": False},
    )
    assert draft.status_code == 200
    assert draft.json()["onboarding_complete"] is False
    coords = await api.post(
        "/api/onboarding",
        headers=auth(token),
        json={"home_region": "25.7617, -80.1918", "finish": False},
    )
    assert coords.status_code == 400
    assert coords.json()["code"] == "exact_location_forbidden"


@pytest.mark.anyio
async def test_discover_uses_only_live_accounts() -> None:
    app = create_web_app(clock=lambda: NOW, today=TODAY, signup_relaxed=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await enter_app(client)
        empty = await client.get("/api/discover", headers=auth(first))
        assert empty.status_code == 200
        assert empty.json()["candidate"] is None
        second = await enter_app(client)
        first_id = (await client.get("/api/bootstrap", headers=auth(first))).json()["account_id"]
        second_id = (await client.get("/api/bootstrap", headers=auth(second))).json()["account_id"]
        pack = await client.get("/api/discover", headers=auth(first))
        assert pack.status_code == 200
        candidate = pack.json()["candidate"]
        assert candidate is not None
        assert candidate["id"] == second_id
        assert candidate["id"].startswith("live:")
        assert candidate["id"] not in {"p1", "p2", "p3", "p4", "p5"}
        assert "distance_km" not in candidate
        assert "latitude" not in candidate
        assert candidate["distance_label"] == "Distance unavailable"
        assert candidate["photo_count"] >= 2
        assert candidate["photo_url"].startswith("/api/discover/photos/")
        face = await client.get(candidate["photo_url"], headers=auth(first))
        assert face.status_code == 200
        assert face.headers["content-type"].startswith("image/")
        reverse = await client.get("/api/discover", headers=auth(second))
        assert reverse.json()["candidate"]["id"] == first_id


def _location_body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "latitude": 25.7617,
        "longitude": -80.1918,
        "accuracy_m": 400,
        "timestamp_ms": NOW,
        "simulated": False,
        "mock": False,
        "reduced_accuracy": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_location_attestation_jitters_and_rejects_spoof() -> None:
    app = create_web_app(clock=lambda: NOW, today=TODAY, signup_relaxed=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await enter_app(client)
        second = await enter_app(client)
        spoofed = await client.post(
            "/api/location",
            headers=auth(first),
            json=_location_body(simulated=True),
        )
        assert spoofed.status_code == 400
        assert spoofed.json()["code"] == "location_unauthentic"
        empty = await client.get("/api/discover", headers=auth(first))
        assert empty.json()["candidate"]["distance_label"] == "Distance unavailable"
        assert empty.json()["location_ready"] is False
        for token, lat in ((first, 25.7617), (second, 25.77)):
            accepted = await client.post(
                "/api/location",
                headers=auth(token),
                json=_location_body(latitude=lat),
            )
            assert accepted.status_code == 200
            assert accepted.json()["location_ready"] is True
            assert "location_cell_lat" not in accepted.json()
            assert "latitude" not in accepted.json()
        card = await client.get("/api/discover", headers=auth(first))
        candidate = card.json()["candidate"]
        assert candidate["distance_label"] in {
            "About 1 mile",
            "About 5 miles",
            "About 15 miles",
            "Farther",
        }
        assert candidate["region_label"] == candidate["distance_label"]
        assert "distance_km" not in candidate
        assert "latitude" not in candidate
        assert "location_cell_lat" not in candidate


@pytest.mark.anyio
async def test_discover_photos_and_like_use_session_header(api: httpx.AsyncClient) -> None:
    token = await enter_app(api)
    bootstrap = await api.get("/api/bootstrap", headers=auth(token))
    assert bootstrap.status_code == 200
    assert bootstrap.json()["token"] == token
    assert bootstrap.json()["catalogs"]["gender"]
    discover = await api.get("/api/discover", headers=auth(token))
    assert discover.status_code == 200
    candidate = discover.json()["candidate"]
    assert candidate["id"]
    assert candidate["distance_label"] in {
        "About 1 mile",
        "About 5 miles",
        "About 15 miles",
        "Farther",
        "Distance unavailable",
    }
    assert "distance_km" not in candidate
    assert "latitude" not in candidate
    assert candidate["photo_count"] >= 1
    assert candidate["photos"][0].startswith("/api/discover/photos/")
    photo = await api.get(candidate["photo_url"], headers=auth(token))
    assert photo.status_code == 200
    assert photo.headers["cache-control"] == "private, no-store"
    assert photo.headers["content-type"].startswith("image/")
    assert len(photo.content) > 1000
    heic = await api.get(
        candidate["photo_url"],
        headers={**auth(token), "Accept": "image/heic,image/avif,*/*"},
    )
    assert heic.status_code == 200
    assert heic.headers["content-type"] == "image/heic"
    pack = await api.get("/api/discover/pack?ahead=3", headers=auth(token))
    assert pack.status_code == 200
    body = pack.json()
    assert body["catalog"] == "nas-hot-deck"
    assert body["encoding"] == "heic+avif+gzip"
    assert body["candidate"]["id"] == candidate["id"]
    assert body["candidate"]["about"]
    assert len(body["window"]) >= 1
    assert body["window"][0]["photos"][0].startswith("/api/discover/photos/")
    anonymous = await api.get(candidate["photo_url"])
    assert anonymous.status_code == 401
    liked = await api.post(
        "/api/discover/interest",
        headers=auth(token),
        json={"candidate_id": "p1"},
    )
    assert liked.status_code == 200
    assert liked.json()["matched"] is True
    assert liked.json()["match_id"] == "match:p1"
    matches = await api.get("/api/matches", headers=auth(token))
    assert matches.status_code == 200
    assert matches.json()["matches"][0]["id"] == "match:p1"


@pytest.mark.anyio
async def test_chat_filters_profile_and_community_round_trip(api: httpx.AsyncClient) -> None:
    token = await enter_app(api)
    await api.post("/api/discover/interest", headers=auth(token), json={"candidate_id": "p1"})
    chat = await api.get("/api/matches/match:p1", headers=auth(token))
    assert chat.status_code == 200
    assert chat.json()["match"]["display_name"]
    sent = await api.post(
        "/api/matches/match:p1/message",
        headers=auth(token),
        json={"body": "hey from expo"},
    )
    assert sent.status_code == 200
    assert sent.json()["messages"][-1]["body"] == "hey from expo"
    assert sent.json()["messages"][-1]["mine"] is True
    suggestion = sent.json()["meetup_suggestions"][0]["id"]
    meetup = await api.post(
        "/api/matches/match:p1/meetup",
        headers=auth(token),
        json={"suggestion_id": suggestion},
    )
    assert meetup.status_code == 200
    profile = await api.get("/api/profile", headers=auth(token))
    assert profile.status_code == 200
    saved = await api.post(
        "/api/profile",
        headers=auth(token),
        json={"display_name": "Ada", "about": "Local research profile."},
    )
    assert saved.status_code == 200
    assert saved.json()["profile"]["display_name"] == "Ada"
    hosted = await api.post("/api/profile/hosting", headers=auth(token), json={"hosting": True})
    assert hosted.status_code == 200
    assert hosted.json()["verified_host"] is True
    reach = await api.post("/api/profile/reach", headers=auth(token), json={"sku": "boost"})
    assert reach.status_code == 200
    filters = await api.post(
        "/api/filters",
        headers=auth(token),
        json={"show_genders": ["man"], "immediate_intent": ["casual_dating"]},
    )
    assert filters.status_code == 200
    assert "man" in filters.json()["values"]["show_genders"]
    reported = await api.post(
        "/api/discover/report",
        headers=auth(token),
        json={"candidate_id": "p2", "reason": "scam", "evidence_note": "scripted replies"},
    )
    assert reported.status_code == 200
    community = await api.get("/api/community", headers=auth(token))
    assert community.status_code == 200
    case = community.json()["cases"][0]
    vote = await api.post(
        f"/api/community/{case['id']}/vote",
        headers=auth(token),
        json={"reviewer_id": case["reviewers"][0]["id"], "choice": "suspicious"},
    )
    assert vote.status_code == 200
    unmatched = await api.post("/api/matches/match:p1/unmatch", headers=auth(token))
    assert unmatched.status_code == 200
    assert unmatched.json()["matches"] == []


@pytest.mark.anyio
async def test_pass_undo_and_boost_labels(api: httpx.AsyncClient) -> None:
    token = await enter_app(api)
    await api.post("/api/profile/hosting", headers=auth(token), json={"hosting": True})
    discover = await api.get("/api/discover", headers=auth(token))
    candidate_id = discover.json()["candidate"]["id"]
    passed = await api.post(
        "/api/discover/pass",
        headers=auth(token),
        json={"candidate_id": candidate_id},
    )
    assert passed.status_code == 200
    undone = await api.post("/api/discover/undo", headers=auth(token))
    assert undone.status_code == 200
    assert undone.json()["candidate"]["id"] == candidate_id
    boosted = await api.post("/api/discover/boost", headers=auth(token))
    assert boosted.status_code == 200
    assert boosted.json()["reach"]["boost_active"] is True
    again = await api.post("/api/discover/boost", headers=auth(token))
    assert again.status_code == 400
    assert again.json()["code"] == "boost_already_active"


@pytest.mark.anyio
async def test_onboarding_filters_superlike_errors_and_match_controls(  # noqa: PLR0915
    api: httpx.AsyncClient,
) -> None:
    token = await open_session(api)
    denied = await api.get("/api/onboarding", headers=auth(token))
    assert denied.status_code == 401
    await api.post("/api/age-gate", headers=auth(token), json={"birth_date": "2000-01-01"})
    form = await api.get("/api/onboarding", headers=auth(token))
    assert form.status_code == 200
    assert form.json()["missing_fields"]
    token = await enter_app(api)
    empty_undo = await api.post("/api/discover/undo", headers=auth(token))
    assert empty_undo.json()["notice"] == "There is nothing to undo yet."
    missing_photo = await api.get("/api/discover/photos/missing/0", headers=auth(token))
    assert missing_photo.status_code == 404
    bad_report = await api.post(
        "/api/discover/report",
        headers=auth(token),
        json={"candidate_id": "p2", "reason": "not-a-reason"},
    )
    assert bad_report.status_code == 400
    filters = await api.get("/api/filters", headers=auth(token))
    assert filters.status_code == 200
    no_reach = await api.post("/api/profile/reach", headers=auth(token), json={"sku": "nope"})
    assert no_reach.status_code == 400
    no_superlike = await api.post(
        "/api/discover/superlike",
        headers=auth(token),
        json={"candidate_id": "p3"},
    )
    assert no_superlike.status_code == 400
    await api.post("/api/profile/hosting", headers=auth(token), json={"hosting": True})
    superliked = await api.post(
        "/api/discover/superlike",
        headers=auth(token),
        json={"candidate_id": "p3"},
    )
    assert superliked.status_code == 200
    await api.post("/api/discover/interest", headers=auth(token), json={"candidate_id": "p1"})
    rewind_match = await api.post("/api/discover/undo", headers=auth(token))
    assert "Unmatch" in rewind_match.json()["error"]
    missing_chat = await api.get("/api/matches/match:missing", headers=auth(token))
    assert missing_chat.status_code == 404
    blank = await api.post(
        "/api/matches/match:p1/message",
        headers=auth(token),
        json={"body": ""},
    )
    assert blank.status_code == 400
    bad_meetup = await api.post(
        "/api/matches/match:p1/meetup",
        headers=auth(token),
        json={"suggestion_id": "missing"},
    )
    assert bad_meetup.status_code == 400
    too_soon = await api.post("/api/matches/match:p1/extend", headers=auth(token))
    assert too_soon.status_code == 400
    reported = await api.post(
        "/api/matches/match:p1/report",
        headers=auth(token),
        json={"reason": "spam_links", "evidence_note": "links"},
    )
    assert reported.status_code == 200
    community = await api.get("/api/community", headers=auth(token))
    case = community.json()["cases"][0]
    if case["can_appeal"]:
        appealed = await api.post(f"/api/community/{case['id']}/appeal", headers=auth(token))
        assert appealed.status_code in {200, 400}
    if case["can_adjudicate"]:
        judged = await api.post(f"/api/community/{case['id']}/adjudicate", headers=auth(token))
        assert judged.status_code in {200, 400}
    blocked = await api.post("/api/matches/match:p1/block", headers=auth(token))
    assert blocked.status_code == 200
    assert all(row["id"] != "match:p1" for row in blocked.json()["matches"])
    missing_block = await api.post("/api/matches/match:missing/block", headers=auth(token))
    assert missing_block.status_code == 400
    no_json = await api.post("/api/discover/pass", headers=auth(token))
    assert no_json.status_code == 400


@pytest.mark.anyio
async def test_profile_photos_upload_as_display_avif_and_remove(
    api: httpx.AsyncClient,
) -> None:
    token = await enter_app(api)
    existing = await api.get("/api/profile", headers=auth(token))
    assert existing.status_code == 200
    assert existing.json()["photo_count"] == 2
    uploaded = await api.post(
        "/api/profile/photos",
        headers=auth(token),
        files={"photo": ("me.png", PNG_1X1, "image/png")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["photo_count"] == 3
    assert uploaded.json()["photos"][0]["url"] == "/api/profile/photos/0"
    image = await api.get("/api/profile/photos/2", headers=auth(token))
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/avif")
    assert image.headers["cache-control"] == "private, no-store"
    assert image.content[4:12] == b"ftypavif"
    removed = await api.post("/api/profile/photos/2/remove", headers=auth(token))
    assert removed.status_code == 200
    assert removed.json()["photo_count"] == 2
    missing = await api.get("/api/profile/photos/2", headers=auth(token))
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_profile_photos_survive_session_reload(tmp_path: Path) -> None:
    store = BrowserSessionStore(
        clock=lambda: NOW,
        today=TODAY,
        sqlite_path=str(tmp_path / "photos.sqlite"),
        signup_relaxed=True,
    )
    transport = httpx.ASGITransport(
        app=create_web_app(clock=lambda: NOW, today=TODAY, session_store=store, signup_relaxed=True)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await enter_app(client)
        uploaded = await client.post(
            "/api/profile/photos",
            headers=auth(token),
            files={"photo": ("face.png", PNG_1X1, "image/png")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["photo_count"] == 3
        store._sessions.clear()
        restored = await client.get("/api/profile", headers=auth(token))
        assert restored.status_code == 200
        assert restored.json()["photo_count"] == 3
        image = await client.get("/api/profile/photos/0", headers=auth(token))
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/")


@pytest.mark.anyio
async def test_profile_photos_reject_empty_invalid_and_full_slots(
    api: httpx.AsyncClient,
) -> None:
    token = await enter_app(api)
    ungated = await api.get("/api/profile/photos/0")
    assert ungated.status_code == 401
    empty = await api.post("/api/profile/photos", headers=auth(token))
    assert empty.status_code == 400
    assert empty.json()["code"] == "photo_empty"
    bad = await api.post(
        "/api/profile/photos",
        headers=auth(token),
        files={"photo": ("x.bin", b"not-an-image", "application/octet-stream")},
    )
    assert bad.status_code == 400
    assert bad.json()["code"] == "photo_type_unsupported"
    pair = await api.post(
        "/api/profile/photos",
        headers=auth(token),
        files=[
            ("photo", ("a.png", PNG_1X1, "image/png")),
            ("photo", ("b.png", PNG_1X1, "image/png")),
        ],
    )
    assert pair.status_code == 200
    assert pair.json()["photo_count"] == 4
    assert pair.json()["notice"] == "2 photos added."
    invalid_slot = await api.post("/api/profile/photos/9/remove", headers=auth(token))
    assert invalid_slot.status_code == 400
    assert invalid_slot.json()["code"] == "photo_slot_invalid"
    for index in range(2):
        filled = await api.post(
            "/api/profile/photos",
            headers=auth(token),
            files={"photo": (f"{index}.png", PNG_1X1, "image/png")},
        )
        assert filled.status_code == 200
    overflow = await api.post(
        "/api/profile/photos",
        headers=auth(token),
        files={"photo": ("extra.png", PNG_1X1, "image/png")},
    )
    assert overflow.status_code == 400
    assert overflow.json()["code"] == "photo_empty"


@pytest.mark.anyio
async def test_discover_block_and_report_block_remove_profiles(
    api: httpx.AsyncClient,
) -> None:
    token = await enter_app(api)
    blocked = await api.post(
        "/api/discover/block",
        headers=auth(token),
        json={"candidate_id": "p2"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["candidate"]["id"] != "p2"
    again = await api.post(
        "/api/discover/interest",
        headers=auth(token),
        json={"candidate_id": "p2"},
    )
    assert again.status_code == 400
    assert again.json()["code"] == "candidate_blocked"
    reported = await api.post(
        "/api/discover/report",
        headers=auth(token),
        json={
            "candidate_id": "p5",
            "reason": "scam",
            "evidence_note": "scripted",
            "also_block": True,
        },
    )
    assert reported.status_code == 200
    assert "blocked" in reported.json()["notice"].lower()
    self_block = await api.post(
        "/api/discover/block",
        headers=auth(token),
        json={"candidate_id": "local-viewer"},
    )
    assert self_block.status_code == 400
    liked = await api.post(
        "/api/discover/interest",
        headers=auth(token),
        json={"candidate_id": "p1"},
    )
    assert liked.status_code == 200
    assert liked.json()["matched"] is True
    chat = await api.get("/api/matches/match:p1", headers=auth(token))
    assert chat.status_code == 200
    closed = await api.post(
        "/api/matches/match:p1/report",
        headers=auth(token),
        json={"reason": "scam", "also_block": True},
    )
    assert closed.status_code == 200
    assert "matches" in closed.json()
    hidden = await api.get("/api/matches/match:p1", headers=auth(token))
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "candidate_blocked"


@pytest.mark.anyio
async def test_account_export_and_delete(api: httpx.AsyncClient) -> None:
    token = await enter_app(api)
    exported = await api.get("/api/account/export", headers=auth(token))
    assert exported.status_code == 200
    assert exported.json()["export"]
    deleted = await api.post("/api/account/delete", headers=auth(token), json={})
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    rediscover = await api.get("/api/discover", headers=auth(token))
    assert rediscover.status_code == 401
    assert rediscover.json()["code"] == "session_required"


@pytest.mark.anyio
async def test_declared_age_range_fails_closed_under_18(api: httpx.AsyncClient) -> None:
    token = await open_session(api)
    refused = await api.post(
        "/api/age-gate",
        headers=auth(token),
        json={"assurance": "declared_age_range", "lower_bound": 17},
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "adult_only"
    accepted = await api.post(
        "/api/age-gate",
        headers=auth(token),
        json={"assurance": "declared_age_range", "lower_bound": 18},
    )
    assert accepted.status_code == 200
    assert accepted.json()["adult_accepted"] is True


@pytest.mark.anyio
async def test_two_adults_can_match_each_other(api: httpx.AsyncClient) -> None:
    first = await enter_app(api)
    second = await enter_app(api)
    first_id = (await api.get("/api/bootstrap", headers=auth(first))).json()["account_id"]
    second_id = (await api.get("/api/bootstrap", headers=auth(second))).json()["account_id"]
    assert first_id.startswith("live:")
    assert second_id.startswith("live:")
    assert first_id != second_id
    pending = await api.post(
        "/api/discover/interest",
        headers=auth(first),
        json={"candidate_id": second_id},
    )
    assert pending.status_code == 200
    assert pending.json()["matched"] is False
    matched = await api.post(
        "/api/discover/interest",
        headers=auth(second),
        json={"candidate_id": first_id},
    )
    assert matched.status_code == 200
    assert matched.json()["matched"] is True
    moment = matched.json()["matched_with"]
    assert moment["match_id"] == f"match:{first_id}"
    assert moment["display_name"]
    assert moment["photo_url"].startswith("/api/discover/photos/")
    face = await api.get(moment["photo_url"], headers=auth(second))
    assert face.status_code == 200
    assert face.headers["content-type"].startswith("image/")
    rows = await api.get("/api/matches", headers=auth(second))
    assert rows.status_code == 200
    listed = rows.json()["matches"]
    assert listed[0]["photo_url"].startswith("/api/discover/photos/")
    chat = await api.get(f"/api/matches/{moment['match_id']}", headers=auth(second))
    assert chat.json()["match"]["photo_url"].startswith("/api/discover/photos/")


@pytest.mark.anyio
async def test_getfkd_mode_match_dissolves_for_both_adults(api: httpx.AsyncClient) -> None:
    first = await enter_app(api)
    second = await enter_app(api)
    first_id = (await api.get("/api/bootstrap", headers=auth(first))).json()["account_id"]
    second_id = (await api.get("/api/bootstrap", headers=auth(second))).json()["account_id"]
    on = await api.post("/api/getfkd", headers=auth(first), json={"enabled": True})
    assert on.status_code == 200
    assert on.json()["get_fkd_enabled"] is True
    assert (await api.post("/api/getfkd", headers=auth(second), json={"enabled": True})).status_code == 200
    pending = await api.post(
        "/api/discover/interest",
        headers=auth(first),
        json={"candidate_id": second_id},
    )
    assert pending.json()["matched"] is False
    matched = await api.post(
        "/api/discover/interest",
        headers=auth(second),
        json={"candidate_id": first_id},
    )
    assert matched.status_code == 200
    assert matched.json()["matched"] is True
    assert matched.json()["matched_with"]["getfkd"] is True
    rows = await api.get("/api/matches", headers=auth(second))
    assert rows.json()["matches"][0]["getfkd"] is True
    sent = await api.post(
        f"/api/matches/match:{first_id}/message",
        headers=auth(second),
        json={"body": "get numbers later"},
    )
    assert sent.status_code == 200
    exited = await api.post("/api/getfkd", headers=auth(first), json={"enabled": False})
    assert exited.status_code == 200
    assert exited.json()["get_fkd_enabled"] is False
    assert second_id in exited.json()["dissolved"]
    left = await api.get("/api/matches", headers=auth(first))
    right = await api.get("/api/matches", headers=auth(second))
    assert left.json()["matches"] == []
    assert right.json()["matches"] == []


@pytest.mark.anyio
async def test_two_adults_share_the_same_chat_thread(api: httpx.AsyncClient) -> None:
    first = await enter_app(api)
    second = await enter_app(api)
    first_id = (await api.get("/api/bootstrap", headers=auth(first))).json()["account_id"]
    second_id = (await api.get("/api/bootstrap", headers=auth(second))).json()["account_id"]
    pending = await api.post(
        "/api/discover/interest",
        headers=auth(first),
        json={"candidate_id": second_id},
    )
    assert pending.status_code == 200
    matched = await api.post(
        "/api/discover/interest",
        headers=auth(second),
        json={"candidate_id": first_id},
    )
    assert matched.status_code == 200
    assert matched.json()["matched"] is True
    first_match = f"match:{second_id}"
    second_match = str(matched.json()["match_id"])
    sent = await api.post(
        f"/api/matches/{first_match}/message",
        headers=auth(first),
        json={"body": "hey from first phone"},
    )
    assert sent.status_code == 200
    assert sent.json()["messages"][-1]["body"] == "hey from first phone"
    assert sent.json()["messages"][-1]["mine"] is True
    peer = await api.get(f"/api/matches/{second_match}", headers=auth(second))
    assert peer.status_code == 200
    assert peer.json()["messages"][-1]["body"] == "hey from first phone"
    assert peer.json()["messages"][-1]["mine"] is False
    reply = await api.post(
        f"/api/matches/{second_match}/message",
        headers=auth(second),
        json={"body": "hey from second phone"},
    )
    assert reply.status_code == 200
    assert [item["body"] for item in reply.json()["messages"]] == [
        "hey from first phone",
        "hey from second phone",
    ]
    echoed = await api.get(f"/api/matches/{first_match}", headers=auth(first))
    assert [item["mine"] for item in echoed.json()["messages"]] == [True, False]
    assert echoed.json()["match"]["status"] == "active"


@pytest.mark.anyio
async def test_block_hides_the_other_adult_from_discovery_and_chat(
    api: httpx.AsyncClient,
) -> None:
    first = await enter_app(api)
    second = await enter_app(api)
    first_id = (await api.get("/api/bootstrap", headers=auth(first))).json()["account_id"]
    second_id = (await api.get("/api/bootstrap", headers=auth(second))).json()["account_id"]
    liked = await api.post(
        "/api/discover/interest",
        headers=auth(first),
        json={"candidate_id": second_id},
    )
    assert liked.status_code == 200
    matched = await api.post(
        "/api/discover/interest",
        headers=auth(second),
        json={"candidate_id": first_id},
    )
    assert matched.status_code == 200
    assert matched.json()["matched"] is True
    match_id = str(matched.json()["match_id"])
    blocked = await api.post(
        "/api/discover/block",
        headers=auth(first),
        json={"candidate_id": second_id},
    )
    assert blocked.status_code == 200
    pack = await api.get("/api/discover/pack", headers=auth(second))
    assert pack.status_code == 200
    ids = [row["id"] for row in pack.json().get("window") or []]
    if pack.json().get("candidate"):
        ids.append(pack.json()["candidate"]["id"])
    assert first_id not in ids
    refused = await api.post(
        "/api/discover/interest",
        headers=auth(second),
        json={"candidate_id": first_id},
    )
    assert refused.status_code == 400
    assert refused.json()["code"] == "candidate_blocked"
    chat = await api.get(f"/api/matches/{match_id}", headers=auth(second))
    assert chat.status_code == 404
    assert chat.json()["code"] == "candidate_blocked"
    message = await api.post(
        f"/api/matches/{match_id}/message",
        headers=auth(second),
        json={"body": "still there?"},
    )
    assert message.status_code == 400
    assert message.json()["code"] == "candidate_blocked"


def _apple_bundle() -> tuple[object, dict, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk["kid"] = "test-kid"
    return private, {"keys": [jwk]}, "test-kid"


def _apple_token(private: object, kid: str, sub: str, *, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    return jwt.encode(
        {
            "iss": "https://appleid.apple.com",
            "aud": "app.getfkd.ios",
            "sub": sub,
            "iat": issued,
            "exp": issued + 3600,
        },
        private,
        algorithm="RS256",
        headers={"kid": kid},
    )


@pytest.mark.anyio
async def test_apple_bind_restore_and_store_gate() -> None:
    app = create_web_app(clock=lambda: NOW, today=TODAY, signup_relaxed=True)
    private, jwks, kid = _apple_bundle()
    app.state.apple_jwks = jwks
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await enter_app(client)
        store = {"X-Getfkd-Release": "store", **auth(token)}
        gated = await client.get("/api/discover", headers=store)
        assert gated.status_code == 401
        assert gated.json()["code"] == "apple_sign_in_required"
        minor = await open_session(client)
        refused = await client.post(
            "/api/auth/apple",
            headers=auth(minor),
            json={"identity_token": _apple_token(private, kid, "sub-minor")},
        )
        assert refused.status_code == 401
        assert refused.json()["code"] == "adult_gate_required"
        bad = await client.post(
            "/api/auth/apple",
            headers=auth(token),
            json={"identity_token": "nope"},
        )
        assert bad.status_code == 401
        assert bad.json()["code"] == "apple_token_invalid"
        bound = await client.post(
            "/api/auth/apple",
            headers=auth(token),
            json={"identity_token": _apple_token(private, kid, "sub-ada")},
        )
        assert bound.status_code == 200
        assert bound.json()["apple_bound"] is True
        account_id = bound.json()["account_id"]
        opened = await client.get("/api/discover", headers=store)
        assert opened.status_code == 200
        await client.post("/api/auth/sign-out", headers=auth(token))
        second = await enter_app(client)
        restored = await client.post(
            "/api/auth/apple",
            headers=auth(second),
            json={"identity_token": _apple_token(private, kid, "sub-ada")},
        )
        assert restored.status_code == 200
        assert restored.json()["account_id"] == account_id
        assert restored.json()["apple_bound"] is True


@pytest.mark.anyio
async def test_suspend_hides_account_and_blocks_discover() -> None:
    app = create_web_app(clock=lambda: NOW, today=TODAY, signup_relaxed=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await enter_app(client)
        second = await enter_app(client)
        first_id = (await client.get("/api/bootstrap", headers=auth(first))).json()["account_id"]
        app.state.session_store._sqlite.set_suspended(first_id, True)
        blocked = await client.get("/api/discover", headers=auth(first))
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "account_suspended"
        pack = await client.get("/api/discover/pack", headers=auth(second))
        ids = [row["id"] for row in pack.json().get("window") or []]
        if pack.json().get("candidate"):
            ids.append(pack.json()["candidate"]["id"])
        assert first_id not in ids


@pytest.mark.anyio
async def test_alignment_percent_requires_compatibility_quiz(api: httpx.AsyncClient) -> None:
    token = await enter_app(api)
    before = await api.get("/api/discover", headers=auth(token))
    assert before.status_code == 200
    card = before.json()["candidate"]
    assert card["alignment"] is None
    assert card["alignment_participating"] is True
    assert card["alignment_answered"] == 6
    assert card["alignment_total"] == 200
    quiz = await api.get("/api/alignment", headers=auth(token))
    assert quiz.status_code == 200
    assert quiz.json()["answered"] == 0
    assert len(quiz.json()["questions"]) == 200
    saved = await api.post(
        "/api/alignment",
        headers=auth(token),
        json={
            "answers": {
                "worldview": "progressive",
                "lifestyle": "mix",
                "relationship": "figuring",
                "family": "later",
                "money": "mix",
                "social": "mix",
            }
        },
    )
    assert saved.status_code == 200
    assert saved.json()["answered"] == 6
    after = await api.get("/api/discover", headers=auth(token))
    scored = after.json()["candidate"]
    assert scored["alignment"] is not None
    assert 0 <= scored["alignment"] <= 100
    assert scored["alignment_answered"] == 6
    bootstrap = await api.get("/api/bootstrap", headers=auth(token))
    assert bootstrap.json()["alignment_answered"] == 6
    assert bootstrap.json()["alignment_total"] == 200
    skipped = await api.post(
        "/api/alignment",
        headers=auth(token),
        json={
            "answers": {
                "worldview": "skip",
                "lifestyle": "skip",
                "relationship": "skip",
                "family": "skip",
                "money": "skip",
                "social": "skip",
            }
        },
    )
    assert skipped.status_code == 200
    assert skipped.json()["answered"] == 6
    assert skipped.json()["answers"]["lifestyle"] == "skip"
    hidden = await api.get("/api/discover", headers=auth(token))
    assert hidden.json()["candidate"]["alignment"] is None


@pytest.mark.anyio
async def test_daily_swipe_limit_blocks_the_next_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GETFKD_DAILY_FREE_SWIPES", "2")
    app = create_test_app(clock=lambda: NOW, today=TODAY)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await enter_app(client)
        first = await client.get("/api/discover", headers=auth(token))
        assert first.status_code == 200
        assert first.json()["reach"]["daily_swipe_limit"] == 2
        assert first.json()["reach"]["swipes_remaining"] == 2
        first_id = first.json()["candidate"]["id"]
        passed = await client.post(
            "/api/discover/pass",
            headers=auth(token),
            json={"candidate_id": first_id},
        )
        assert passed.status_code == 200
        assert passed.json()["reach"]["swipes_remaining"] == 1
        second_id = passed.json()["candidate"]["id"]
        passed_again = await client.post(
            "/api/discover/pass",
            headers=auth(token),
            json={"candidate_id": second_id},
        )
        assert passed_again.status_code == 200
        assert passed_again.json()["reach"]["swipes_remaining"] == 0
        third_id = passed_again.json()["candidate"]["id"]
        blocked = await client.post(
            "/api/discover/pass",
            headers=auth(token),
            json={"candidate_id": third_id},
        )
        assert blocked.status_code == 400
        assert blocked.json()["code"] == "daily_swipe_limit"
        undone = await client.post("/api/discover/undo", headers=auth(token))
        assert undone.status_code == 200
        assert undone.json()["reach"]["swipes_remaining"] == 1
        assert undone.json()["candidate"]["id"] == second_id

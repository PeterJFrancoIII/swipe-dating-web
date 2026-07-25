from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from swipe_dating.api.app import MAX_REQUEST_BODY_BYTES, create_app

NOW = 1_700_000_000_000


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(clock=lambda: NOW))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


def credential(subject_id: str) -> dict[str, object]:
    return {
        "subjectId": subject_id,
        "issuedAtMs": NOW,
        "expiresAtMs": NOW + 3_600_000,
        "issuer": "staging-mock",
        "revoked": False,
    }


def presence(profile_id: str) -> dict[str, object]:
    return {
        "profileId": profile_id,
        "region": "rnd:test",
        "issuedAtMs": NOW,
        "expiresAtMs": NOW + 120_000,
        "adultCredential": credential(profile_id),
    }


@pytest.mark.anyio
async def test_health_identifies_synthetic_python_mode(api: httpx.AsyncClient) -> None:
    response = await api.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "python-rnd-synthetic-only"}


@pytest.mark.anyio
async def test_presence_discovery_reciprocal_likes_and_withdrawal(
    api: httpx.AsyncClient,
) -> None:
    for profile_id in ("a", "b"):
        response = await api.put("/v1/presence", json=presence(profile_id))
        assert response.status_code == 200
        assert response.json()["profileId"] == profile_id

    discovery = await api.get(
        "/v1/discovery", params={"region": "rnd:test", "requesterProfileId": "a"}
    )
    assert discovery.status_code == 200
    assert discovery.json() == {"profileIds": ["b"]}

    first = await api.post("/v1/likes", json={"senderProfileId": "a", "recipientProfileId": "b"})
    assert first.status_code == 200
    assert first.json() == {"matched": False, "receipt": None}
    reciprocal = await api.post(
        "/v1/likes", json={"senderProfileId": "b", "recipientProfileId": "a"}
    )
    assert reciprocal.status_code == 200
    assert reciprocal.json() == {
        "matched": True,
        "receipt": {"profileA": "a", "profileB": "b", "matchedAtMs": NOW},
    }

    withdrawal = await api.delete("/v1/presence/b")
    assert withdrawal.status_code == 200
    assert withdrawal.json() == {"withdrawn": True}


@pytest.mark.anyio
async def test_block_removes_likes_and_rejects_future_interaction(
    api: httpx.AsyncClient,
) -> None:
    first = await api.post("/v1/likes", json={"senderProfileId": "a", "recipientProfileId": "b"})
    assert first.status_code == 200
    blocked = await api.post("/v1/blocks", json={"blockerProfileId": "b", "blockedProfileId": "a"})
    assert blocked.status_code == 204
    assert blocked.content == b""
    interaction = await api.post(
        "/v1/likes", json={"senderProfileId": "a", "recipientProfileId": "b"}
    )
    assert interaction.status_code == 400
    assert interaction.json() == {"error": "interaction_blocked"}


@pytest.mark.anyio
async def test_invalid_input_invalid_json_and_unknown_routes_fail_closed(
    api: httpx.AsyncClient,
) -> None:
    invalid_credential = presence("a")
    invalid_credential["adultCredential"] = credential("b")
    response = await api.put("/v1/presence", json=invalid_credential)
    assert response.status_code == 400
    assert response.json() == {"error": "adult_credential_subject_bound"}

    missing = await api.post("/v1/likes", json={"senderProfileId": "a"})
    assert missing.status_code == 400
    assert missing.json() == {"error": "bad_request"}

    malformed = await api.post(
        "/v1/likes", content=b"{broken", headers={"content-type": "application/json"}
    )
    assert malformed.status_code == 400
    assert malformed.json() == {"error": "bad_request"}

    not_found = await api.get("/not-a-route")
    assert not_found.status_code == 404
    assert not_found.json() == {"error": "not_found"}


@pytest.mark.anyio
async def test_request_body_limit_is_enforced_at_65536_bytes(
    api: httpx.AsyncClient,
) -> None:
    body = b"{" + b'"padding":"' + b"x" * MAX_REQUEST_BODY_BYTES + b'"}'
    assert len(body) > MAX_REQUEST_BODY_BYTES
    response = await api.post(
        "/v1/likes", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json() == {"error": "request_body_too_large"}


@pytest.mark.anyio
async def test_discovery_limit_is_clamped_to_twenty(api: httpx.AsyncClient) -> None:
    for index in range(25):
        profile_id = f"p{index:02d}"
        response = await api.put("/v1/presence", json=presence(profile_id))
        assert response.status_code == 200
    response = await api.get(
        "/v1/discovery",
        params={"region": "rnd:test", "requesterProfileId": "viewer", "limit": 999},
    )
    assert response.status_code == 200
    assert len(response.json()["profileIds"]) == 20

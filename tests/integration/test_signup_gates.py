from __future__ import annotations

import json
import tempfile
import time
from io import BytesIO

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from PIL import Image

from swipe_dating.domain.signup_fraud import MIN_ONBOARDING_MS
from swipe_dating.web.app import create_web_app
from tests.onboarding_support import REQUIRED_ONBOARDING

NOW = 1_753_185_600_000
TODAY = "2026-07-22"
SESSION_HEADER = "X-Swipe-Session"
IP = {"CF-Connecting-IP": "203.0.113.77"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def auth(token: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {SESSION_HEADER: token, **IP, "X-Getfkd-Install": "install-a"}
    if extra:
        headers.update(extra)
    return headers


def unique_png(seed: int) -> bytes:
    image = Image.new("RGB", (2, 2), (seed % 256, (seed * 3) % 256, (seed * 7) % 256))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _apple_bundle() -> tuple[object, dict, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    jwk["kid"] = "signup-kid"
    return private, {"keys": [jwk]}, "signup-kid"


def _apple_token(private: object, kid: str, sub: str, *, now: int) -> str:
    return jwt.encode(
        {
            "iss": "https://appleid.apple.com",
            "aud": "app.getfkd.ios",
            "sub": sub,
            "iat": now,
            "exp": now + 3600,
        },
        private,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _strict_app(clock, sqlite_path: str | None = None):
    path = sqlite_path or tempfile.mkstemp(prefix="signup-fraud-", suffix=".sqlite")[1]
    app = create_web_app(clock=clock, today=TODAY, sqlite_path=path, signup_relaxed=False)
    private, jwks, kid = _apple_bundle()
    app.state.apple_jwks = jwks
    return app, private, kid, path


async def _open(client: httpx.AsyncClient, install: str = "install-a") -> str:
    response = await client.post("/api/session", headers={**IP, "X-Getfkd-Install": install})
    assert response.status_code == 200, response.text
    return str(response.json()["token"])


async def _age(client: httpx.AsyncClient, token: str, year: str = "2000", install: str = "install-a") -> httpx.Response:
    return await client.post(
        "/api/age-gate",
        headers=auth(token, {"X-Getfkd-Install": install}),
        json={"birth_month": "01", "birth_day": "01", "birth_year": year},
    )


async def _bind_apple(client: httpx.AsyncClient, token: str, private: object, kid: str, sub: str, now: int) -> None:
    bound = await client.post(
        "/api/auth/apple",
        headers=auth(token),
        json={"identity_token": _apple_token(private, kid, sub, now=now)},
    )
    assert bound.status_code == 200, bound.text


async def _photos(client: httpx.AsyncClient, token: str, seed: int) -> httpx.Response:
    return await client.post(
        "/api/profile/photos",
        headers=auth(token),
        files=[
            ("photo", ("a.png", unique_png(seed), "image/png")),
            ("photo", ("b.png", unique_png(seed + 50), "image/png")),
        ],
    )


@pytest.mark.anyio
async def test_session_mint_cap_per_ip() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        for index in range(8):
            minted = await client.post(
                "/api/session",
                headers={**IP, "X-Getfkd-Install": f"cap-{index}"},
            )
            assert minted.status_code == 200
        blocked = await client.post(
            "/api/session",
            headers={**IP, "X-Getfkd-Install": "cap-overflow"},
        )
        assert blocked.status_code == 429
        assert blocked.json()["code"] == "signup_rate_limited"
        assert blocked.json()["error"] == "Slow down and try again later."


@pytest.mark.anyio
async def test_photo_upload_does_not_mint_or_burn_session_cap() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client, "photo-live")
        assert (await _age(client, token, install="photo-live")).status_code == 200
        for index in range(7):
            minted = await client.post(
                "/api/session",
                headers={**IP, "X-Getfkd-Install": f"photo-cap-{index}"},
            )
            assert minted.status_code == 200
        blocked = await client.post(
            "/api/session",
            headers={**IP, "X-Getfkd-Install": "photo-overflow"},
        )
        assert blocked.status_code == 429
        missing = await client.post(
            "/api/profile/photos",
            headers={**IP, "X-Getfkd-Install": "photo-no-session"},
            files=[("photo", ("a.png", unique_png(90), "image/png"))],
        )
        assert missing.status_code == 401
        assert missing.json()["code"] == "session_required"
        stale = await client.post(
            "/api/profile/photos",
            headers=auth("dead-token", {"X-Getfkd-Install": "photo-stale"}),
            files=[("photo", ("a.png", unique_png(91), "image/png"))],
        )
        assert stale.status_code == 401
        assert stale.json()["code"] == "session_required"
        bootstrap = await client.get(
            "/api/bootstrap",
            headers={SESSION_HEADER: "dead-token", **IP, "X-Getfkd-Install": "photo-stale"},
        )
        assert bootstrap.status_code == 401
        assert bootstrap.json()["code"] == "session_required"
        uploaded = await _photos(client, token, 92)
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["photo_count"] >= 1


@pytest.mark.anyio
async def test_photo_upload_accepts_session_form_field_without_header() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client, "photo-form")
        assert (await _age(client, token, install="photo-form")).status_code == 200
        uploaded = await client.post(
            "/api/profile/photos",
            headers={**IP, "X-Getfkd-Install": "photo-form"},
            data={"session": token},
            files=[("photo", ("a.png", unique_png(94), "image/png"))],
        )
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["photo_count"] >= 1


@pytest.mark.anyio
async def test_birth_date_change_locks_session() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client)
        refused = await _age(client, token, "2010")
        assert refused.status_code == 400
        assert refused.json()["code"] == "adult_only"
        changed = await _age(client, token, "2000")
        assert changed.status_code == 403
        assert changed.json()["code"] == "signup_unauthentic"
        assert changed.json()["error"] == "This signup could not be verified."
        again = await _age(client, token, "2000")
        assert again.status_code == 403
        assert again.json()["code"] == "signup_unauthentic"


@pytest.mark.anyio
async def test_finish_without_apple_stays_incomplete() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client)
        accepted = await _age(client, token)
        assert accepted.status_code == 200
        now[0] += MIN_ONBOARDING_MS + 1
        photos = await _photos(client, token, 3)
        assert photos.status_code == 200
        finished = await client.post(
            "/api/onboarding",
            headers=auth(token),
            json=REQUIRED_ONBOARDING,
        )
        assert finished.status_code == 401
        assert finished.json()["code"] == "apple_sign_in_required"
        assert finished.json()["onboarding_complete"] is False


@pytest.mark.anyio
async def test_dev_skip_apple_allows_metro_finish() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    app.state.session_store.dev_skip_apple = True
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client, "skip-apple")
        assert (await _age(client, token, install="skip-apple")).status_code == 200
        now[0] += MIN_ONBOARDING_MS + 1
        photos = await _photos(client, token, 41)
        assert photos.status_code == 200
        finished = await client.post(
            "/api/onboarding",
            headers=auth(token, {"X-Getfkd-Install": "skip-apple"}),
            json=REQUIRED_ONBOARDING,
        )
        assert finished.status_code == 200, finished.text
        assert finished.json()["onboarding_complete"] is True


@pytest.mark.anyio
async def test_dev_skip_apple_does_not_bypass_store_release() -> None:
    now = [NOW]
    app, _private, _kid, _path = _strict_app(lambda: now[0])
    app.state.session_store.dev_skip_apple = True
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client, "store-apple")
        assert (await _age(client, token, install="store-apple")).status_code == 200
        now[0] += MIN_ONBOARDING_MS + 1
        photos = await _photos(client, token, 43)
        assert photos.status_code == 200
        finished = await client.post(
            "/api/onboarding",
            headers=auth(token, {"X-Getfkd-Install": "store-apple", "X-Getfkd-Release": "store"}),
            json=REQUIRED_ONBOARDING,
        )
        assert finished.status_code == 401
        assert finished.json()["code"] == "apple_sign_in_required"


@pytest.mark.anyio
async def test_too_fast_onboarding_locks() -> None:
    now = [NOW]
    app, private, kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _open(client)
        assert (await _age(client, token)).status_code == 200
        await _bind_apple(client, token, private, kid, "sub-fast", int(time.time()))
        assert (await _photos(client, token, 11)).status_code == 200
        finished = await client.post(
            "/api/onboarding",
            headers=auth(token),
            json=REQUIRED_ONBOARDING,
        )
        assert finished.status_code == 403
        assert finished.json()["code"] == "signup_unauthentic"
        assert finished.json()["onboarding_complete"] is False
        discover = await client.get("/api/discover", headers=auth(token))
        assert discover.status_code == 403
        assert discover.json()["code"] == "signup_unauthentic"


@pytest.mark.anyio
async def test_photo_reuse_across_accounts() -> None:
    now = [NOW]
    app, private, kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    shared = unique_png(99)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await _open(client, "install-one")
        assert (await _age(client, first, install="install-one")).status_code == 200
        await _bind_apple(client, first, private, kid, "sub-one", int(time.time()))
        uploaded = await client.post(
            "/api/profile/photos",
            headers=auth(first, {"X-Getfkd-Install": "install-one"}),
            files=[("photo", ("a.png", shared, "image/png"))],
        )
        assert uploaded.status_code == 200
        second = await _open(client, "install-two")
        assert (await _age(client, second, install="install-two")).status_code == 200
        reused = await client.post(
            "/api/profile/photos",
            headers=auth(second, {"X-Getfkd-Install": "install-two"}),
            files=[("photo", ("a.png", shared, "image/png"))],
        )
        assert reused.status_code == 400
        assert reused.json()["code"] == "photo_reused"


@pytest.mark.anyio
async def test_locked_account_hidden_from_discover() -> None:
    now = [NOW]
    app, private, kid, _path = _strict_app(lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        victim = await _open(client, "install-victim")
        assert (await _age(client, victim, install="install-victim")).status_code == 200
        await _bind_apple(client, victim, private, kid, "sub-victim", int(time.time()))
        assert (await _photos(client, victim, 21)).status_code == 200
        too_fast = await client.post(
            "/api/onboarding",
            headers=auth(victim, {"X-Getfkd-Install": "install-victim"}),
            json=REQUIRED_ONBOARDING,
        )
        assert too_fast.status_code == 403
        victim_id = str((await client.get("/api/bootstrap", headers=auth(victim))).json()["account_id"])
        viewer = await _open(client, "install-viewer")
        assert (await _age(client, viewer, install="install-viewer")).status_code == 200
        await _bind_apple(client, viewer, private, kid, "sub-viewer", int(time.time()))
        assert (await _photos(client, viewer, 31)).status_code == 200
        now[0] += MIN_ONBOARDING_MS + 1
        finished = await client.post(
            "/api/onboarding",
            headers=auth(viewer, {"X-Getfkd-Install": "install-viewer"}),
            json=REQUIRED_ONBOARDING,
        )
        assert finished.status_code == 200, finished.text
        assert finished.json()["onboarding_complete"] is True
        pack = await client.get("/api/discover/pack", headers=auth(viewer, {"X-Getfkd-Install": "install-viewer"}))
        assert pack.status_code == 200
        ids = [row["id"] for row in pack.json().get("window") or []]
        if pack.json().get("candidate"):
            ids.append(pack.json()["candidate"]["id"])
        assert victim_id not in ids
        hidden = await client.get("/api/discover", headers=auth(victim))
        assert hidden.status_code == 403


@pytest.mark.anyio
async def test_relaxed_helper_still_finishes_in_milliseconds() -> None:
    from tests.onboarding_support import create_test_app, finish_onboarding

    transport = httpx.ASGITransport(app=create_test_app(clock=lambda: NOW, today=TODAY))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = str((await client.post("/api/session")).json()["token"])
        accepted = await client.post(
            "/api/age-gate",
            headers={SESSION_HEADER: token},
            json={"birth_month": "01", "birth_day": "01", "birth_year": "2000"},
        )
        assert accepted.status_code == 200
        await finish_onboarding(client, token)
        bootstrap = await client.get("/api/bootstrap", headers={SESSION_HEADER: token})
        assert bootstrap.json()["onboarding_complete"] is True

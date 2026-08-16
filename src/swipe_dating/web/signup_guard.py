"""Apply ADR-0023 checks at session, age-gate, photo, and onboarding finish."""

from __future__ import annotations

from collections.abc import Mapping

from swipe_dating.application.session import ResearchSession
from swipe_dating.domain.signup_fraud import (
    AGE_GATES_PER_IP_HOUR,
    APPLE_SIGN_IN_REQUIRED,
    DAY_MS,
    HOUR_MS,
    KIND_AGE_FAIL,
    KIND_AGE_GATE,
    KIND_LOCK,
    KIND_ONBOARD_COMPLETE,
    KIND_SESSION_MINT,
    MIN_ONBOARDING_MS,
    ONBOARDS_PER_IP_DAY,
    PHOTO_REUSED,
    SESSION_REQUIRED,
    SIGNUP_RATE_LIMITED,
    SIGNUP_UNAUTHENTIC,
    WEEK_MS,
    SignupFraudError,
    assert_birth_frozen,
    client_ip,
    hash_token,
    header_value,
    install_id,
    onboard_install_cap,
    photo_sha256,
    session_mint_cap,
    signup_message,
)


def apply_session_flags(session: ResearchSession, sessions: object) -> None:
    relaxed = bool(getattr(sessions, "signup_relaxed", False))
    session.require_apple_to_finish = not relaxed
    if sessions.is_signup_locked(session.account_id):  # type: ignore[attr-defined]
        session.signup_locked = True


def obtain_session(request: object, sessions: object) -> tuple[str, ResearchSession, bool]:
    from swipe_dating.web.app import SESSION_HEADER, request_session_token

    token = request_session_token(request)  # type: ignore[arg-type]
    existing = sessions.get(token) if token else None  # type: ignore[attr-defined]
    if existing is not None:
        apply_session_flags(existing, sessions)
        return str(token), existing, False
    if header_value(getattr(request, "headers", {}), SESSION_HEADER):
        raise SignupFraudError(SESSION_REQUIRED, status_code=401)
    if not getattr(sessions, "signup_relaxed", False):
        ctx = _context(request)
        now = sessions.now_ms()  # type: ignore[attr-defined]
        minted = sessions.count_signup_events(  # type: ignore[attr-defined]
            kind=KIND_SESSION_MINT, ip_hash=ctx["ip_hash"], since=now - HOUR_MS
        )
        if minted >= session_mint_cap(ctx["ip_hash"]):
            raise SignupFraudError(SIGNUP_RATE_LIMITED, status_code=429)
    token, session = sessions.create()  # type: ignore[attr-defined]
    apply_session_flags(session, sessions)
    if not getattr(sessions, "signup_relaxed", False):
        ctx = _context(request)
        sessions.record_signup_event(  # type: ignore[attr-defined]
            kind=KIND_SESSION_MINT,
            ip_hash=ctx["ip_hash"],
            install_hash=ctx["install_hash"],
            account_id=session.account_id,
            created_at=sessions.now_ms(),  # type: ignore[attr-defined]
        )
    return token, session, True


def require_existing_session(request: object, sessions: object) -> tuple[str, ResearchSession]:
    from swipe_dating.web.app import request_session_token

    token = request_session_token(request)  # type: ignore[arg-type]
    existing = sessions.get(token) if token else None  # type: ignore[attr-defined]
    if existing is None:
        raise SignupFraudError(SESSION_REQUIRED, status_code=401)
    apply_session_flags(existing, sessions)
    return str(token), existing


def assert_not_locked(session: ResearchSession, sessions: object) -> None:
    apply_session_flags(session, sessions)
    if session.signup_locked or sessions.is_signup_locked(session.account_id):  # type: ignore[attr-defined]
        raise SignupFraudError(SIGNUP_UNAUTHENTIC, status_code=403)


def prepare_age_gate(session: ResearchSession, sessions: object, request: object, birth_key: str) -> None:
    assert_not_locked(session, sessions)
    if getattr(sessions, "signup_relaxed", False):
        session.signup_birth_key = birth_key or session.signup_birth_key
        return
    ctx = _context(request)
    now = sessions.now_ms()  # type: ignore[attr-defined]
    attempts = sessions.count_signup_events(  # type: ignore[attr-defined]
        kind=KIND_AGE_GATE, ip_hash=ctx["ip_hash"], since=now - HOUR_MS
    )
    if attempts >= AGE_GATES_PER_IP_HOUR:
        raise SignupFraudError(SIGNUP_RATE_LIMITED, status_code=429)
    try:
        assert_birth_frozen(session.signup_birth_key, birth_key)
    except SignupFraudError:
        lock_unauthentic(session, sessions, request)
        raise
    session.signup_birth_key = birth_key
    sessions.record_signup_event(  # type: ignore[attr-defined]
        kind=KIND_AGE_GATE,
        ip_hash=ctx["ip_hash"],
        install_hash=ctx["install_hash"],
        account_id=session.account_id,
        created_at=now,
    )


def note_age_gate_accepted(session: ResearchSession) -> None:
    if not session.age_gate_accepted_at:
        session.age_gate_accepted_at = int(session.clock())


def note_age_gate_failed(session: ResearchSession, sessions: object, request: object) -> None:
    if getattr(sessions, "signup_relaxed", False):
        return
    ctx = _context(request)
    sessions.record_signup_event(  # type: ignore[attr-defined]
        kind=KIND_AGE_FAIL,
        ip_hash=ctx["ip_hash"],
        install_hash=ctx["install_hash"],
        account_id=session.account_id,
        created_at=sessions.now_ms(),  # type: ignore[attr-defined]
    )


def lock_unauthentic(session: ResearchSession, sessions: object, request: object) -> None:
    session.signup_locked = True
    sessions.lock_signup(session.account_id, SIGNUP_UNAUTHENTIC)  # type: ignore[attr-defined]
    if getattr(sessions, "signup_relaxed", False):
        return
    ctx = _context(request)
    sessions.record_signup_event(  # type: ignore[attr-defined]
        kind=KIND_LOCK,
        ip_hash=ctx["ip_hash"],
        install_hash=ctx["install_hash"],
        account_id=session.account_id,
        created_at=sessions.now_ms(),  # type: ignore[attr-defined]
    )


def claim_photo_bytes(session: ResearchSession, sessions: object, payload: bytes) -> None:
    if getattr(sessions, "signup_relaxed", False):
        return
    digest = photo_sha256(payload)
    if not sessions.claim_photo_hash(digest, session.account_id, sessions.now_ms()):  # type: ignore[attr-defined]
        raise SignupFraudError(PHOTO_REUSED, status_code=400)


def finish_onboarding(session: ResearchSession, sessions: object, request: object) -> None:
    assert_not_locked(session, sessions)
    if getattr(sessions, "signup_relaxed", False):
        return
    if not sessions.apple_bound(session):  # type: ignore[attr-defined]
        raise SignupFraudError(APPLE_SIGN_IN_REQUIRED, status_code=401)
    now = sessions.now_ms()  # type: ignore[attr-defined]
    accepted = int(session.age_gate_accepted_at or 0)
    if accepted <= 0 or now - accepted < MIN_ONBOARDING_MS:
        lock_unauthentic(session, sessions, request)
        raise SignupFraudError(SIGNUP_UNAUTHENTIC, status_code=403, lock=True)
    ctx = _context(request)
    completed_ip = sessions.count_signup_events(  # type: ignore[attr-defined]
        kind=KIND_ONBOARD_COMPLETE, ip_hash=ctx["ip_hash"], since=now - DAY_MS
    )
    if completed_ip >= ONBOARDS_PER_IP_DAY:
        lock_unauthentic(session, sessions, request)
        raise SignupFraudError(SIGNUP_UNAUTHENTIC, status_code=403, lock=True)
    completed_install = sessions.count_signup_events(  # type: ignore[attr-defined]
        kind=KIND_ONBOARD_COMPLETE, install_hash=ctx["install_hash"], since=now - WEEK_MS
    )
    if completed_install >= onboard_install_cap(ctx["install_hash"]):
        lock_unauthentic(session, sessions, request)
        raise SignupFraudError(SIGNUP_UNAUTHENTIC, status_code=403, lock=True)
    sessions.record_signup_event(  # type: ignore[attr-defined]
        kind=KIND_ONBOARD_COMPLETE,
        ip_hash=ctx["ip_hash"],
        install_hash=ctx["install_hash"],
        account_id=session.account_id,
        created_at=now,
    )
    session._onboarding_done = True


def fraud_http(error: SignupFraudError) -> tuple[str, int, str]:
    return signup_message(error.code), error.status_code, error.code


def _context(request: object) -> dict[str, str]:
    headers: Mapping[str, str] = getattr(request, "headers", {})
    return {
        "ip_hash": hash_token(client_ip(headers)),
        "install_hash": hash_token(install_id(headers)),
    }

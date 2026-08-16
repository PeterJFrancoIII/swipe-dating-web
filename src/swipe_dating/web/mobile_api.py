"""JSON API for the Apple-first Expo client. Same session store as the HTML app."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response

from swipe_dating.adapters.apple_identity import AppleIdentityError, verify_apple_identity_token
from swipe_dating.adapters.hot_deck import get_hot_deck
from swipe_dating.application.session import ResearchSession
from swipe_dating.domain.alignment_catalog import question_count
from swipe_dating.domain.bot_moderation import ReportReason, VoteChoice
from swipe_dating.domain.conversations import (
    EXPIRED_STATUSES,
    match_expires_at_ms,
    match_remaining_ms,
    match_urgency,
)
from swipe_dating.domain.discovery import IMMEDIATE_INTENTS, RELATIONAL_OPENNESS
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.loose_location import ALLOWED_DISTANCE_LABELS
from swipe_dating.domain.models import iso_from_ms
from swipe_dating.domain.system_config import config_int
from swipe_dating.domain.system_reports import (
    ERROR_RATE_LIMIT,
    FEEDBACK_RATE_LIMIT,
    RATE_WINDOW_MS,
    auto_tags,
    clip_explanation,
    clip_feedback,
    sanitize_context,
    sanitize_tags,
    screenshot_mime,
)
from swipe_dating.domain.gender_catalog import GENDER_OPTIONS
from swipe_dating.domain.preferences import (
    BEDROOM_OPTIONS,
    DRINKING_OPTIONS,
    DRUGS_OPTIONS,
    HOBBY_OPTIONS,
    INTEREST_OPTIONS,
    MAX_TURN_TAGS,
    PERSONALITY_OPTIONS,
    SMOKING_OPTIONS,
    TURN_ON_OPTIONS,
    choice_icon,
    choice_label,
    section_mark,
)
from swipe_dating.domain.profile_photos import PROFILE_PHOTO_MAX_UPLOAD_BYTES, PROFILE_PHOTO_SLOTS
from swipe_dating.domain.signup_fraud import (
    SignupFraudError,
    birth_key_from_date,
    birth_key_from_range,
)
from swipe_dating.web.signup_guard import (
    assert_not_locked,
    claim_photo_bytes,
    finish_onboarding,
    fraud_http,
    note_age_gate_accepted,
    note_age_gate_failed,
    obtain_session,
    prepare_age_gate,
    require_existing_session,
)
from swipe_dating.web.app import (
    FEATURE_MATCH_MAP,
    FEATURE_PROXIMITY,
    REPORT_OPTIONS,
    BrowserSessionStore,
    _after_age_gate_path,
    _domain_message,
    _looking_from_form,
    _photo_index,
    _photo_response,
    age_gate_picker_context,
    compose_submitted_birth_date,
    request_session_token,
)
from swipe_dating.web.chat_hub import ChatHub, live_thread_key
from swipe_dating.web.legal_pages import render_legal_page

SESSION_HEADER = "X-Swipe-Session"
RELEASE_HEADER = "X-Getfkd-Release"
_FINAL_CASE_STATUSES = frozenset({"adjudicated_bot", "adjudicated_human"})
_SECTION_GROUPS = (
    "gender",
    "preference",
    "smoking",
    "drinking",
    "drugs",
    "looking",
    "turn_ons",
    "interests",
    "hobbies",
    "personality",
    "bedroom",
)


def register_mobile_api(application: FastAPI, sessions: BrowserSessionStore) -> None:
    _register_session_routes(application, sessions)
    _register_auth_routes(application, sessions)
    _register_account_routes(application, sessions)
    _register_onboarding_routes(application, sessions)
    _register_location_routes(application, sessions)
    _register_getfkd_routes(application, sessions)
    _register_discover_routes(application, sessions)
    _register_match_routes(application, sessions)
    _register_profile_routes(application, sessions)
    _register_profile_photo_routes(application, sessions)
    _register_community_routes(application, sessions)
    _register_system_routes(application, sessions)
    _register_legal_routes(application)


def _register_session_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/health")
    async def api_health() -> dict[str, str]:
        return {"status": "ok", "client": "expo"}

    @application.post("/api/session")
    async def api_session(request: Request) -> JSONResponse:
        try:
            token, session, created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        return _ok({"token": token, "created": created, **_auth_payload(session)})

    @application.get("/api/bootstrap")
    async def api_bootstrap(request: Request) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        picker = age_gate_picker_context(session.today, "")
        return _ok(
            {
                "token": token,
                **_auth_payload(session),
                "catalogs": _catalogs(),
                "section_marks": {group: section_mark(group) for group in _SECTION_GROUPS},
                "turn_limit": MAX_TURN_TAGS,
                "birth_months": list(picker["birth_months"]),
                "birth_days": list(picker["birth_days"]),
                "birth_years": list(picker["birth_years"]),
                "report_options": [
                    {"id": reason.value, "label": label} for reason, label in REPORT_OPTIONS
                ],
                "feature_proximity": FEATURE_PROXIMITY,
                "feature_match_map": FEATURE_MATCH_MAP,
            }
        )

    @application.post("/api/age-gate")
    async def api_age_gate(request: Request) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        body = await _json_body(request)
        submitted = compose_submitted_birth_date(
            birth_date=str(body.get("birth_date", "")),
            birth_month=str(body.get("birth_month", "")),
            birth_day=str(body.get("birth_day", "")),
            birth_year=str(body.get("birth_year", "")),
        )
        if str(body.get("assurance", "")) == "declared_age_range":
            try:
                lower = int(body.get("lower_bound", 0))
            except (TypeError, ValueError):
                lower = 0
            try:
                prepare_age_gate(session, sessions, request, birth_key_from_range(lower))
                session.accept_declared_age_range(lower)
                note_age_gate_accepted(session)
            except SignupFraudError as error:
                message, status, code = fraud_http(error)
                return _error(message, status_code=status, code=code)
            except DomainError as error:
                note_age_gate_failed(session, sessions, request)
                return _error(
                    "You must be at least 18 years old to continue.",
                    status_code=400,
                    code=error.code,
                )
            return _ok(
                {"token": token, **_auth_payload(session), "next": _after_age_gate_path(session)}
            )
        try:
            prepare_age_gate(session, sessions, request, birth_key_from_date(submitted))
            session.accept_adult_gate(submitted)
            note_age_gate_accepted(session)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        except DomainError as error:
            note_age_gate_failed(session, sessions, request)
            message = (
                "Choose a real calendar date as month, day, and year."
                if error.code == "birth_date_invalid"
                else "You must be at least 18 years old to continue."
            )
            return _error(message, status_code=400, code=error.code)
        return _ok(
            {
                "token": token,
                **_auth_payload(session, request, sessions),
                "next": _after_age_gate_path(session),
            }
        )


def _register_auth_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.post("/api/auth/apple")
    async def api_auth_apple(request: Request) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        if not session.adult_accepted:
            return _error("adult_gate_required", status_code=401, code="adult_gate_required")
        body = await _json_body(request)
        identity_token = str(body.get("identity_token") or body.get("identityToken") or "")
        try:
            claims = verify_apple_identity_token(
                identity_token,
                jwks=getattr(request.app.state, "apple_jwks", None),
            )
        except AppleIdentityError as error:
            return _error("Sign in with Apple failed.", status_code=401, code=error.code)
        session = sessions.attach_apple(token, claims.sub, claims.email)
        payload = {"token": token, **_auth_payload(session, request, sessions)}
        if sessions.is_suspended(session.account_id):
            return _error(
                "This account is suspended.",
                status_code=403,
                code="account_suspended",
                extra=payload,
            )
        return _ok(payload)

    @application.post("/api/auth/sign-out")
    async def api_auth_sign_out(request: Request) -> JSONResponse:
        token = request_session_token(request)
        sessions.sign_out(token)
        return _ok({"signed_out": True})


def _register_legal_routes(application: FastAPI) -> None:
    @application.get("/legal/{slug}", response_class=HTMLResponse)
    async def legal_page(slug: str) -> HTMLResponse:
        html = render_legal_page(slug)
        if html is None:
            return HTMLResponse("<p>Not found.</p>", status_code=404)
        return HTMLResponse(html)


def _register_account_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/account/export")
    async def api_account_export(request: Request) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        exported = session.export_saved_profile()
        return _ok(
            {
                "token": token,
                "exported_at": session.today,
                "export": exported,
                **_auth_payload(session),
            }
        )

    @application.post("/api/account/delete")
    async def api_account_delete(request: Request) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        session.reset_saved_profile()
        sessions.drop(token)
        return _ok({"deleted": True})


def _register_onboarding_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/onboarding")
    async def api_onboarding(request: Request) -> JSONResponse:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok(_onboarding_payload(session))

    @application.post("/api/onboarding")
    async def api_save_onboarding(request: Request) -> JSONResponse:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        current = session.local_state.profile
        finish = bool(body.get("finish", True))
        try:
            session.update_profile(
                display_name=str(body.get("display_name", current.display_name)),
                about=str(body.get("about", current.about)),
                home_region=(
                    None if "home_region" not in body else str(body.get("home_region") or "")
                ),
                gender_identities=(
                    None
                    if "gender_identities" not in body
                    else tuple(_as_list(body.get("gender_identities")))
                ),
                photo_id=current.photo_id,
                lifestyle_tags=(
                    current.lifestyle_tags
                    if "lifestyle_tags" not in body
                    else tuple(_as_list(body.get("lifestyle_tags")))
                ),
                hobby_tags=(
                    current.hobby_tags
                    if "hobby_tags" not in body
                    else tuple(_as_list(body.get("hobby_tags")))
                ),
                personality_tags=(
                    current.personality_tags
                    if "personality_tags" not in body
                    else tuple(_as_list(body.get("personality_tags")))
                ),
                bedroom_tags=current.bedroom_tags,
                smoking=None if "smoking" not in body else str(body.get("smoking") or ""),
                drinking=None if "drinking" not in body else str(body.get("drinking") or ""),
                drugs=None if "drugs" not in body else str(body.get("drugs") or ""),
                turn_ons=(
                    None if "turn_ons" not in body else tuple(_as_list(body.get("turn_ons")))
                ),
                feed_genders=(
                    tuple(session.selected_genders)
                    if "show_genders" not in body
                    else tuple(_as_list(body.get("show_genders")))
                ),
                visibility=current.visibility,
            )
        except DomainError as error:
            return _error(
                _domain_message(error),
                status_code=400,
                code=error.code,
                extra=_onboarding_payload(session),
            )
        if "immediate_intent" in body or "relational_openness" in body:
            session.update_preferences(
                immediate_intent=_looking_from_form(_as_list(body.get("immediate_intent"))),
                relational_openness=tuple(_as_list(body.get("relational_openness"))),
            )
        raw_alignment = body.get("alignment_answers")
        if isinstance(raw_alignment, dict):
            session.save_alignment({str(key): str(value) for key, value in raw_alignment.items()})
        if finish and session.onboarding_gaps():
            return _error(
                "Finish the highlighted questions to continue.",
                status_code=400,
                extra=_onboarding_payload(session),
            )
        if finish and not session.onboarding_gaps():
            try:
                finish_onboarding(session, sessions, request)
            except SignupFraudError as error:
                message, status, code = fraud_http(error)
                return _error(
                    message,
                    status_code=status,
                    code=code,
                    extra=_onboarding_payload(session),
                )
        notice = (
            "You're in. Filters can narrow the same answers."
            if session.onboarding_is_complete()
            else None
        )
        return _ok({**_onboarding_payload(session), **({"notice": notice} if notice else {})})

    @application.get("/api/alignment")
    async def api_alignment(request: Request) -> JSONResponse:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok(session.alignment_payload())

    @application.post("/api/alignment")
    async def api_save_alignment(request: Request) -> JSONResponse:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        raw = body.get("answers", body.get("alignment_answers") or {})
        if not isinstance(raw, dict):
            return _error("Alignment answers must be a map.", status_code=400)
        session.save_alignment({str(key): str(value) for key, value in raw.items()})
        return _ok(session.alignment_payload())


def _register_location_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.post("/api/location")
    async def api_location(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            accepted = session.accept_loose_location(body)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok({**accepted, **_auth_payload(session, request, sessions)})


def _register_getfkd_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.post("/api/getfkd")
    async def api_getfkd(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        enabled = bool(body.get("enabled"))
        try:
            peers = session.set_get_fkd_enabled(enabled)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        if not enabled and peers:
            sessions.absorb_getfkd_exit(session.account_id, peers)
            for peer_id in peers:
                await _publish_closed(request, session, peer_id, "getfkd_ended")
        return _ok(
            {
                **_auth_payload(session, request, sessions),
                "get_fkd_enabled": session.get_fkd_enabled,
                "dissolved": list(peers),
                "notice": (
                    "Get Fk'd mode is on."
                    if session.get_fkd_enabled
                    else "Get Fk'd mode is off. Those matches and chats are gone."
                ),
            }
        )


def _register_discover_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/discover")
    async def api_discover(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok(_discover_payload(session, request))

    @application.get("/api/discover/pack")
    async def api_discover_pack(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        ahead = _pack_ahead(request)
        payload = _discover_pack_payload(session, request, ahead=ahead)
        return _ok(payload)

    @application.get("/api/discover/photos/{candidate_id}/{slot}")
    async def api_discover_photo(
        request: Request,
        candidate_id: str,
        slot: int,
    ) -> Response:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            stored = session.deck_photo(
                candidate_id, slot, include_heic=_wants_heic(request)
            )
        except DomainError:
            return Response(status_code=404)
        return _photo_response(stored, heif=_wants_heic(request))

    @application.post("/api/discover/pass")
    async def api_pass(request: Request) -> JSONResponse:
        return await _discover_action(request, sessions, "pass")

    @application.post("/api/discover/interest")
    async def api_interest(request: Request) -> JSONResponse:
        return await _discover_action(request, sessions, "interest")

    @application.post("/api/discover/superlike")
    async def api_superlike(request: Request) -> JSONResponse:
        return await _discover_action(request, sessions, "superlike")

    @application.post("/api/discover/boost")
    async def api_boost(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            session.activate_boost()
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok(
            {
                **_discover_payload(session, request),
                "notice": "Boost is on. You're in the labeled priority cohort for 30 minutes.",
            }
        )

    @application.post("/api/discover/undo")
    async def api_undo(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        outcome = session.undo_last_decision()
        payload = _discover_payload(session, request)
        if outcome.get("kind") == "match_requires_unmatch":
            payload["error"] = "Matches cannot be rewound. Unmatch from the chat instead."
        elif outcome.get("restored_candidate_id"):
            payload["notice"] = "Your last non-match decision was restored."
        else:
            payload["notice"] = "There is nothing to undo yet."
        return _ok(payload)

    @application.post("/api/discover/block")
    async def api_discover_block(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            session.block_profile(str(body.get("candidate_id", "")))
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok(
            {
                **_discover_payload(session, request),
                "notice": "Blocked. They cannot see you, and you will not see them again.",
            }
        )

    @application.post("/api/discover/report")
    async def api_report(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        also_block = bool(body.get("also_block"))
        try:
            case = session.report_suspected_bot(
                str(body.get("candidate_id", "")),
                ReportReason(str(body.get("reason", ""))),
                evidence_note=str(body.get("evidence_note", "")),
                also_block=also_block,
            )
        except (DomainError, ValueError) as error:
            message = (
                _domain_message(error)
                if isinstance(error, DomainError)
                else "Unknown report reason."
            )
            return _error(message, status_code=400)
        notice = f"Report received. {case.id} is in private community review."
        if also_block:
            notice = f"{notice} They are blocked."
        return _ok(
            {
                **_discover_payload(session, request),
                "notice": notice,
                "next": "/community",
            }
        )


def _register_match_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.websocket("/api/matches/{match_id:path}/live")
    async def api_chat_live(websocket: WebSocket, match_id: str) -> None:
        session = _live_session(websocket, sessions)
        if session is None:
            await websocket.close(code=1008)
            return
        try:
            match = session.match(match_id)
            if match.status.value == "blocked" or session._partner_blocked(match.candidate.id):
                await websocket.close(code=1008)
                return
        except DomainError:
            await websocket.close(code=1008)
            return
        hub = _chat_hub(websocket)
        thread_id = live_thread_key(session.account_id, match.candidate.id)
        await websocket.accept()
        hub.subscribe(thread_id, session.account_id, websocket)
        try:
            while True:
                try:
                    incoming = await asyncio.wait_for(websocket.receive_json(), timeout=20)
                except TimeoutError:
                    await websocket.send_json({"type": "ping"})
                    continue
                if incoming.get("type") == "typing":
                    await hub.publish(
                        thread_id,
                        {"type": "typing", "account_id": session.account_id},
                        exclude=session.account_id,
                    )
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(thread_id, session.account_id, websocket)

    @application.get("/api/matches/{match_id:path}/live")
    async def api_chat_live_http() -> JSONResponse:
        return _error(
            "Live chat uses a socket, not a page refresh.",
            status_code=426,
            code="upgrade_required",
        )

    @application.get("/api/matches")
    async def api_matches(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok({"matches": [_match_row(session, match) for match in session.active_matches()]})

    @application.get("/api/matches/{match_id:path}")
    async def api_match(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            match = session.match(match_id)
            if match.status.value == "blocked" or session._partner_blocked(match.candidate.id):
                return _error(
                    "That person is blocked.",
                    status_code=404,
                    code="candidate_blocked",
                )
            return _ok(_chat_payload(session, match_id))
        except DomainError as error:
            return _error(_domain_message(error), status_code=404, code=error.code)

    @application.post("/api/matches/{match_id:path}/message")
    async def api_message(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            session.send_message(match_id, str(body.get("body", body.get("text", ""))))
            payload = _chat_payload(session, match_id)
            await _publish_chat_event(request, session, match_id, "message", payload)
            return _ok(payload)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)

    @application.post("/api/matches/{match_id:path}/meetup")
    async def api_meetup(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            session.propose_meetup(match_id, str(body.get("suggestion_id", "")))
            payload = {**_chat_payload(session, match_id), "notice": "Meetup idea sent."}
            await _publish_chat_event(request, session, match_id, "message", payload)
            return _ok(payload)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)

    @application.post("/api/matches/{match_id:path}/extend")
    async def api_extend(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            session.extend_messages(match_id)
            return _ok(_chat_payload(session, match_id))
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)

    @application.post("/api/matches/{match_id:path}/unmatch")
    async def api_unmatch(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            peer_id = session.match(match_id).candidate.id
            session.unmatch(match_id)
            await _publish_closed(request, session, peer_id, "unmatched")
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok({"matches": [_match_row(session, match) for match in session.active_matches()]})

    @application.post("/api/matches/{match_id:path}/block")
    async def api_block(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            peer_id = session.match(match_id).candidate.id
            session.block(match_id)
            await _publish_closed(request, session, peer_id, "blocked")
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok({"matches": [_match_row(session, match) for match in session.active_matches()]})

    @application.post("/api/matches/{match_id:path}/report")
    async def api_match_report(request: Request, match_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            peer_id = session.match(match_id).candidate.id
        except DomainError:
            peer_id = ""
        response = _match_report_response(session, match_id, body)
        if peer_id and body.get("also_block"):
            await _publish_closed(request, session, peer_id, "blocked")
        return response


def _register_profile_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/profile")
    async def api_profile(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok(_profile_payload(session))

    @application.post("/api/profile")
    async def api_save_profile(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        current = session.local_state.profile
        try:
            session.update_profile(
                display_name=str(body.get("display_name", current.display_name)),
                about=str(body.get("about", current.about)),
                home_region=(
                    None if "home_region" not in body else str(body.get("home_region") or "")
                ),
                gender_identities=tuple(
                    _as_list(body.get("gender_identities")) or current.gender_identities
                ),
                photo_id=current.photo_id,
                lifestyle_tags=tuple(_as_list(body.get("lifestyle_tags")) or current.lifestyle_tags),
                hobby_tags=tuple(_as_list(body.get("hobby_tags")) or current.hobby_tags),
                personality_tags=tuple(
                    _as_list(body.get("personality_tags")) or current.personality_tags
                ),
                bedroom_tags=tuple(_as_list(body.get("bedroom_tags")) or current.bedroom_tags),
                smoking=str(body.get("smoking", current.smoking)),
                drinking=str(body.get("drinking", current.drinking)),
                drugs=str(body.get("drugs", current.drugs)),
                turn_ons=tuple(_as_list(body.get("turn_ons")) or current.turn_ons),
                feed_genders=tuple(session.selected_genders),
                visibility=current.visibility,
            )
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok({**_profile_payload(session), "notice": "Profile saved."})

    @application.post("/api/profile/hosting")
    async def api_hosting(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        session.set_hosting(bool(body.get("hosting")))
        notice = (
            "Hosting is on. Weekly Boost and Superlike allotments are labeled, not purchased rank."
            if session.verified_host
            else "Hosting is off. Host allotments were removed."
        )
        return _ok({**_profile_payload(session), "notice": notice})

    @application.post("/api/profile/reach")
    async def api_buy_reach(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            session.buy_reach(str(body.get("sku", "")))
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok(
            {**_profile_payload(session), "notice": "Synthetic reach item added to this session."}
        )

    @application.get("/api/filters")
    async def api_filters(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok(_filters_payload(session))

    @application.post("/api/filters")
    async def api_save_filters(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        session.update_preferences(
            immediate_intent=_looking_from_form(_as_list(body.get("immediate_intent"))),
            relational_openness=tuple(_as_list(body.get("relational_openness"))),
            feed_genders=tuple(_as_list(body.get("show_genders"))),
            feed_smoking=tuple(_as_list(body.get("show_smoking"))),
            feed_drinking=tuple(_as_list(body.get("show_drinking"))),
            feed_drugs=tuple(_as_list(body.get("show_drugs"))),
            feed_turn_ons=tuple(_as_list(body.get("show_turn_ons"))),
        )
        return _ok(
            {
                **_filters_payload(session),
                "notice": "Filters updated. Ranking weights remain fixed.",
            }
        )


def _register_profile_photo_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/profile/photos/{slot}")
    async def api_profile_photo(request: Request, slot: int) -> Response:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        stored = session.profile_photo_at(slot)
        if stored is None:
            return Response(status_code=404)
        return _photo_response(stored, heif=False)

    @application.post("/api/profile/photos")
    async def api_add_profile_photos(
        request: Request,
        photo: Annotated[list[UploadFile] | None, File()] = None,
    ) -> JSONResponse:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        uploads = list(photo or ())
        if not uploads:
            return _error(
                "Choose photos, then tap Add photos.",
                status_code=400,
                code="photo_empty",
            )
        added = 0
        last_error: DomainError | None = None
        try:
            for upload in uploads:
                if session.next_empty_photo_slot() is None:
                    break
                payload = await upload.read(PROFILE_PHOTO_MAX_UPLOAD_BYTES + 1)
                try:
                    claim_photo_bytes(session, sessions, payload)
                    session.add_profile_photo(payload)
                    added += 1
                except SignupFraudError as error:
                    message, status, code = fraud_http(error)
                    return _error(message, status_code=status, code=code)
                except DomainError as error:
                    last_error = error
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        if added == 0:
            message = (
                _domain_message(last_error)
                if last_error is not None
                else "Choose photos, then tap Add photos."
            )
            code = last_error.code if last_error is not None else "photo_empty"
            return _error(message, status_code=400, code=code)
        notice = "Photo added." if added == 1 else f"{added} photos added."
        return _ok({**_profile_payload(session), "notice": notice})

    @application.post("/api/profile/photos/{slot}/remove")
    async def api_remove_profile_photo(request: Request, slot: int) -> JSONResponse:
        session = _api_adult(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            session.clear_profile_photo(slot)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok({**_profile_payload(session), "notice": "Photo removed."})


def _register_community_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/api/community")
    async def api_community(request: Request) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        return _ok(_community_payload(session))

    @application.post("/api/community/{case_id}/vote")
    async def api_vote(request: Request, case_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        body = await _json_body(request)
        try:
            session.vote_on_bot_case(
                case_id,
                str(body.get("reviewer_id", "")),
                VoteChoice(str(body.get("choice", ""))),
            )
        except (DomainError, ValueError) as error:
            message = _domain_message(error) if isinstance(error, DomainError) else "Unknown vote."
            return _error(message, status_code=400)
        return _ok(
            {
                **_community_payload(session),
                "notice": "One private synthetic review vote was recorded.",
            }
        )

    @application.post("/api/community/{case_id}/appeal")
    async def api_appeal(request: Request, case_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            session.appeal_bot_containment(case_id)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        return _ok(
            {
                **_community_payload(session),
                "notice": "Synthetic appeal opened. Containment remains pending review.",
            }
        )

    @application.post("/api/community/{case_id}/adjudicate")
    async def api_adjudicate(request: Request, case_id: str) -> JSONResponse:
        session = _api_gated(request, sessions)
        if isinstance(session, JSONResponse):
            return session
        try:
            case = session.run_synthetic_adjudication(case_id)
        except DomainError as error:
            return _error(_domain_message(error), status_code=400, code=error.code)
        outcome = "bot removed from discovery" if case.contained else "human restored"
        return _ok(
            {
                **_community_payload(session),
                "notice": f"Synthetic fixture adjudicated: {outcome}.",
            }
        )


def _register_system_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.post("/api/system/errors")
    async def api_system_error(
        request: Request,
        screenshot: Annotated[UploadFile | None, File()] = None,
        explanation: Annotated[str, Form()] = "",
        context: Annotated[str, Form()] = "{}",
        tags: Annotated[str, Form()] = "[]",
    ) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        now = _store_now_ms(sessions)
        account_id = session.account_id
        if sessions._sqlite.count_error_reports_since(account_id, now - RATE_WINDOW_MS) >= ERROR_RATE_LIMIT:
            return _error("Slow down. Try again tomorrow.", status_code=429, code="rate_limited")
        upload = screenshot
        if upload is None:
            return _error(
                "Add a screenshot of the page or error.",
                status_code=400,
                code="screenshot_required",
            )
        payload = await upload.read(2 * 1024 * 1024 + 1)
        mime = screenshot_mime(payload)
        if not mime:
            return _error(
                "Use a JPEG, PNG, or WebP screenshot under 2 MB.",
                status_code=400,
                code="screenshot_invalid",
            )
        clean_context = sanitize_context(context)
        clean_context.setdefault("account_id", account_id)
        clean_tags = auto_tags(clean_context, sanitize_tags(tags))
        report = sessions._sqlite.save_error_report(
            account_id=account_id,
            created_at=now,
            route=str(clean_context.get("route") or ""),
            screen=str(clean_context.get("screen") or ""),
            explanation=clip_explanation(explanation),
            tags=clean_tags,
            context=clean_context,
            screenshot=payload,
            screenshot_mime=mime,
        )
        return _ok(
            {
                "token": token,
                "id": report["id"],
                "title": report["title"],
                "tags": report["tags"],
                "notice": "Saved for repair. Thank you.",
            }
        )

    @application.post("/api/system/feedback")
    async def api_system_feedback(request: Request) -> JSONResponse:
        try:
            token, session, _created = _api_session(request, sessions)
        except SignupFraudError as error:
            message, status, code = fraud_http(error)
            return _error(message, status_code=status, code=code)
        now = _store_now_ms(sessions)
        account_id = session.account_id
        if sessions._sqlite.count_feedback_since(account_id, now - RATE_WINDOW_MS) >= FEEDBACK_RATE_LIMIT:
            return _error("Slow down. Try again tomorrow.", status_code=429, code="rate_limited")
        body = await _json_body(request)
        text = clip_feedback(body.get("body") or body.get("text") or "")
        if not text:
            return _error("Write the idea you want us to consider.", status_code=400, code="feedback_required")
        item = sessions._sqlite.save_feedback(
            account_id=account_id,
            created_at=now,
            body=text,
            tags=sanitize_tags(body.get("tags") or ["feedback"]),
        )
        return _ok({"token": token, "id": item["id"], "notice": "Idea saved. Thank you."})


def _store_now_ms(sessions: BrowserSessionStore) -> int:
    clock = getattr(sessions, "_clock", None)
    if clock is not None:
        return int(clock())
    return int(time.time() * 1000)


def _api_session(
    request: Request,
    sessions: BrowserSessionStore,
) -> tuple[str, ResearchSession, bool]:
    return obtain_session(request, sessions)


def _apple_required(request: Request) -> bool:
    return request.headers.get(RELEASE_HEADER, "").strip().lower() in {"store", "preview"}


def _api_adult(
    request: Request,
    sessions: BrowserSessionStore,
) -> ResearchSession | JSONResponse:
    try:
        _token, session = require_existing_session(request, sessions)
        assert_not_locked(session, sessions)
    except SignupFraudError as error:
        message, status, code = fraud_http(error)
        return _error(message, status_code=status, code=code)
    if not session.adult_accepted:
        return _error("adult_gate_required", status_code=401, code="adult_gate_required")
    if sessions.is_suspended(session.account_id):
        return _error("This account is suspended.", status_code=403, code="account_suspended")
    if _apple_required(request) and not sessions.apple_bound(session):
        return _error(
            "Sign in with Apple is required.",
            status_code=401,
            code="apple_sign_in_required",
        )
    return session


def _api_gated(
    request: Request,
    sessions: BrowserSessionStore,
) -> ResearchSession | JSONResponse:
    session = _api_adult(request, sessions)
    if isinstance(session, JSONResponse):
        return session
    if not session.onboarding_is_complete():
        return _error("onboarding_required", status_code=403, code="onboarding_required")
    return session


async def _discover_action(
    request: Request,
    sessions: BrowserSessionStore,
    kind: str,
) -> JSONResponse:
    session = _api_gated(request, sessions)
    if isinstance(session, JSONResponse):
        return session
    body = await _json_body(request)
    candidate_id = str(body.get("candidate_id", ""))
    try:
        if kind == "pass":
            session.pass_candidate(candidate_id)
            notice = "Passed. Your choice stays in this session only."
            outcome: dict[str, Any] = {}
        elif kind == "interest":
            outcome = dict(session.express_interest(candidate_id))
            notice = (
                "It's a match. Open the chat."
                if outcome.get("matched")
                else "Like sent. A match only appears after mutual interest."
            )
        else:
            outcome = dict(session.express_superlike(candidate_id))
            notice = (
                "Superlike sent. It's a match."
                if outcome.get("matched")
                else "Superlike sent. They'll see it was labeled, not an ordinary like."
            )
    except DomainError as error:
        return _error(_domain_message(error), status_code=400, code=error.code)
    payload = _discover_payload(session, request)
    payload["notice"] = notice
    payload["matched"] = bool(outcome.get("matched"))
    payload["match_id"] = outcome.get("match_id")
    if outcome.get("matched"):
        payload["matched_with"] = _matched_with_payload(
            session, candidate_id, str(outcome.get("match_id") or "")
        )
    return _ok(payload)


def _auth_payload(
    session: ResearchSession,
    request: Request | None = None,
    store: BrowserSessionStore | None = None,
) -> dict[str, Any]:
    apple_bound = bool(getattr(session, "apple_sub", ""))
    suspended = False
    if store is not None:
        apple_bound = store.apple_bound(session)
        suspended = store.is_suspended(session.account_id)
    return {
        "account_id": session.account_id,
        "adult_accepted": session.adult_accepted,
        "onboarding_complete": session.onboarding_is_complete(),
        "onboarding_gaps": list(session.onboarding_gaps()),
        "display_name": session.local_state.profile.display_name or "You",
        "apple_bound": apple_bound,
        "apple_required": bool(request is not None and _apple_required(request)),
        "suspended": suspended,
        "unresolved_matches": session.unresolved_count(),
        "active_match_limit": config_int("active_match_limit"),
        "reliability_score": session.reliability_score(),
        "alignment_answered": len(session.questionnaire_answers),
        "alignment_total": question_count(),
        "location_ready": session.location_cell is not None,
        "get_fkd_enabled": bool(session.get_fkd_enabled),
    }


def _onboarding_payload(session: ResearchSession) -> dict[str, Any]:
    profile = session.local_state.profile
    return {
        **_auth_payload(session),
        "catalogs": _catalogs(),
        "section_marks": {group: section_mark(group) for group in _SECTION_GROUPS},
        "turn_limit": MAX_TURN_TAGS,
        "values": {
            "gender_identities": list(profile.gender_identities),
            "show_genders": list(session.selected_genders),
            "display_name": profile.display_name,
            "about": profile.about,
            "home_region": profile.home_region,
            "smoking": profile.smoking,
            "drinking": profile.drinking,
            "drugs": profile.drugs,
            "turn_ons": list(profile.turn_ons),
            "lifestyle_tags": list(profile.lifestyle_tags),
            "hobby_tags": list(profile.hobby_tags),
            "personality_tags": list(profile.personality_tags),
            "immediate_intent": list(session.selected_looking),
            "relational_openness": list(session.selected_openness),
        },
        "missing_fields": list(session.onboarding_gaps()),
        "photo_limit": PROFILE_PHOTO_SLOTS,
        "photo_count": session.filled_photo_count(),
        "photos": [
            {"slot": slot, "url": f"/api/profile/photos/{slot}"}
            for slot in range(PROFILE_PHOTO_SLOTS)
            if session.profile_photo_at(slot) is not None
        ],
        "alignment": session.alignment_payload(),
    }


def _discover_payload(session: ResearchSession, request: Request) -> dict[str, Any]:
    candidate = session.current_candidate()
    reach = _reach_payload(session)
    if candidate is None:
        return {
            "candidate": None,
            "reach": reach,
            "feature_proximity": FEATURE_PROXIMITY,
            "location_ready": session.location_cell is not None,
        }
    return {
        "reach": reach,
        "feature_proximity": FEATURE_PROXIMITY,
        "location_ready": session.location_cell is not None,
        "candidate": _candidate_payload(session, candidate, request),
    }


def _discover_pack_payload(
    session: ResearchSession,
    request: Request,
    *,
    ahead: int,
) -> dict[str, Any]:
    window = []
    deck = get_hot_deck()
    for entry in session.upcoming_candidates(ahead):
        card = _candidate_payload(session, entry, request)
        deck.card_gzip(card["id"], card)
        window.append(card)
    if window:
        deck.warm(window[0]["id"], slots=1)
    return {
        "reach": _reach_payload(session),
        "feature_proximity": FEATURE_PROXIMITY,
        "location_ready": session.location_cell is not None,
        "encoding": "heic+avif+gzip",
        "catalog": "nas-hot-deck",
        "candidate": window[0] if window else None,
        "window": window,
    }


def _reach_payload(session: ResearchSession) -> dict[str, Any]:
    return {
        "boosts": session.boosts_remaining(),
        "superlikes": session.superlikes_remaining(),
        "boost_active": session.boost_is_active(),
        "boost_remaining_ms": session.boost_remaining_ms(),
        "swipes_remaining": session.swipes_remaining(),
        "daily_swipe_limit": session.daily_swipe_limit(),
    }


def _alignment_fields(session: ResearchSession, profile: Any) -> dict[str, Any]:
    answered = len(getattr(profile, "alignment_answers", ()) or ())
    return {
        "alignment": session.pairwise_alignment_percent(profile),
        "alignment_answered": answered,
        "alignment_total": question_count(),
        "alignment_participating": answered > 0,
    }


def _candidate_payload(session: ResearchSession, candidate: Any, request: Request) -> dict[str, Any]:
    profile = candidate.candidate
    photo_count = session.deck_photo_count(profile.id)
    photo_index = _photo_index(request) % photo_count if photo_count else 0
    photo_urls = _api_photo_urls(profile.id, photo_count)
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "age_band": profile.age_band,
        "about": profile.about,
        "looking": _looking_line(profile),
        "habits": (
            f"{choice_label(profile.smoking) if profile.smoking else '—'} smoke · "
            f"{choice_label(profile.drinking) if profile.drinking else '—'} drinks · "
            f"{choice_label(profile.drugs) if profile.drugs else '—'} drugs"
        ),
        **_alignment_fields(session, profile),
        **_distance_fields(session, profile),
        "verified_host": profile.verified_host,
        "boosted": profile.boosted,
        "genders": [choice_label(value) for value in profile.genders],
        "interests": [
            {"id": tag, "label": choice_label(tag), "icon": choice_icon(tag, "interests")}
            for tag in profile.lifestyle_tags[:3]
        ],
        "all_interests": [
            {"id": tag, "label": choice_label(tag), "icon": choice_icon(tag, "interests")}
            for tag in profile.lifestyle_tags
        ],
        "turn_ons": [choice_label(tag) for tag in profile.turn_ons],
        "smoking": profile.smoking,
        "drinking": profile.drinking,
        "drugs": profile.drugs,
        "photo_index": photo_index,
        "photo_count": photo_count,
        "photo_url": photo_urls[photo_index] if photo_urls else "",
        "photos": list(photo_urls),
    }


def coarse_region_label(distance_km: object) -> str:
    try:
        kilometers = float(distance_km)
    except (TypeError, ValueError):
        return "Same region"
    if kilometers <= 8:
        return "Nearby"
    if kilometers <= 20:
        return "Same city"
    return "Same region"


def _distance_fields(session: ResearchSession, profile: Any) -> dict[str, str]:
    label = session.distance_label_for(profile)
    if label not in ALLOWED_DISTANCE_LABELS:
        label = "Distance unavailable"
    return {"distance_label": label, "region_label": label}


def _wants_heic(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    return "image/heic" in accept or "image/heif" in accept


def _pack_ahead(request: Request) -> int:
    raw = request.query_params.get("ahead", "3")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 3
    return max(1, min(value, 4))


def _match_report_response(
    session: ResearchSession, match_id: str, body: dict[str, Any]
) -> JSONResponse:
    also_block = bool(body.get("also_block"))
    try:
        match = session.match(match_id)
        case = session.report_suspected_bot(
            match.candidate.id,
            ReportReason(str(body.get("reason", ""))),
            evidence_note=str(body.get("evidence_note", "")),
            also_block=also_block,
        )
    except (DomainError, ValueError) as error:
        message = (
            _domain_message(error) if isinstance(error, DomainError) else "Unknown report reason."
        )
        return _error(message, status_code=400)
    notice = f"Report received. {case.id} is in private community review."
    if also_block:
        return _ok(
            {
                "matches": [_match_row(session, item) for item in session.active_matches()],
                "notice": f"{notice} They are blocked.",
                "next": "/matches",
            }
        )
    return _ok({**_chat_payload(session, match_id), "notice": notice, "next": "/community"})


def _match_lifecycle(session: ResearchSession, match: Any) -> dict[str, Any]:
    now = session.clock()
    expires = match_expires_at_ms(match)
    return {
        "status": match.status.value,
        "remaining_ms": match_remaining_ms(match, now),
        "expires_at": iso_from_ms(expires) if expires is not None else match.ended_at,
        "urgency": match_urgency(match, now),
    }


def _match_row(session: ResearchSession, match: Any) -> dict[str, Any]:
    if match.status in EXPIRED_STATUSES:
        last = "EXPIRED"
    elif match.messages:
        last = match.messages[-1].body
    else:
        last = "Matched. Say hi when you want to."
    return {
        "id": match.id,
        "display_name": match.candidate.display_name,
        "age_band": match.candidate.age_band,
        "preview": last,
        "initial": match.candidate.display_name[0],
        "candidate_id": match.candidate.id,
        "photo_url": _first_photo_url(session, match.candidate.id),
        "getfkd": bool(match.getfkd),
        **_alignment_fields(session, session.candidate_profile(match.candidate.id)),
        **_match_lifecycle(session, match),
    }


def _chat_hub(source: Request | WebSocket) -> ChatHub:
    return source.app.state.chat_hub


def _live_session(websocket: WebSocket, sessions: BrowserSessionStore) -> ResearchSession | None:
    token = str(websocket.query_params.get("token") or websocket.headers.get(SESSION_HEADER) or "")
    session = sessions.get(token)
    if session is None or not session.adult_accepted or not session.onboarding_is_complete():
        return None
    if sessions.is_suspended(session.account_id):
        return None
    if str(websocket.query_params.get("release") or "") == "store" and not sessions.apple_bound(
        session
    ):
        return None
    return session


async def _publish_chat_event(
    request: Request,
    session: ResearchSession,
    match_id: str,
    kind: str,
    payload: dict[str, Any],
) -> None:
    match = payload.get("match") or {}
    peer_id = str(match.get("candidate_id") or "")
    messages = payload.get("messages") or []
    last = messages[-1] if messages else {}
    await _chat_hub(request).publish(
        live_thread_key(session.account_id, peer_id),
        {
            "type": kind,
            "account_id": session.account_id,
            "message": {
                "id": last.get("id"),
                "body": last.get("body"),
                "sender_id": session.account_id,
            },
            "match": {
                "status": match.get("status"),
                "message_count": match.get("message_count"),
                "message_limit": match.get("message_limit"),
                "extension_used": match.get("extension_used"),
                "remaining_ms": match.get("remaining_ms"),
                "urgency": match.get("urgency"),
            },
        },
        exclude=session.account_id,
    )


async def _publish_closed(
    request: Request,
    session: ResearchSession,
    peer_id: str,
    reason: str,
) -> None:
    await _chat_hub(request).publish(
        live_thread_key(session.account_id, peer_id),
        {"type": "closed", "reason": reason, "account_id": session.account_id},
        exclude=session.account_id,
    )


def _chat_payload(session: ResearchSession, match_id: str) -> dict[str, Any]:
    match = session.match(match_id)
    profile = session.candidate_profile(match.candidate.id)
    expired = match.status in EXPIRED_STATUSES
    meetup = []
    if not expired:
        meetup = [
            {"id": item.id, "title": item.title} for item in session.meetup_suggestions(match.id)
        ]
    return {
        "viewer_id": session.account_id,
        "match": {
            "id": match.id,
            "display_name": match.candidate.display_name,
            "age_band": match.candidate.age_band,
            **_distance_fields(session, profile),
            **_alignment_fields(session, profile),
            "message_count": len(match.messages),
            "message_limit": match.message_limit,
            "extension_used": match.extension_used,
            "candidate_id": match.candidate.id,
            "getfkd": bool(match.getfkd),
            "photo_url": _first_photo_url(session, match.candidate.id),
            "verified_host": profile.verified_host,
            "boosted": profile.boosted,
            "about": "" if expired else profile.about,
            "looking": _looking_line(profile),
            "genders": [choice_label(value) for value in profile.genders],
            "interests": []
            if expired
            else [
                {"id": tag, "label": choice_label(tag), "icon": choice_icon(tag, "interests")}
                for tag in profile.lifestyle_tags
            ],
            "turn_ons": [] if expired else [choice_label(tag) for tag in profile.turn_ons],
            "smoking": profile.smoking,
            "drinking": profile.drinking,
            "drugs": profile.drugs,
            **_match_lifecycle(session, match),
        },
        "messages": [
            {
                "id": message.id,
                "body": message.body,
                "mine": message.sender == "local",
                "sender": "You" if message.sender == "local" else match.candidate.display_name,
            }
            for message in match.messages
        ],
        "meetup_suggestions": meetup,
        "feature_match_map": FEATURE_MATCH_MAP,
        "report_options": [
            {"id": reason.value, "label": label} for reason, label in REPORT_OPTIONS
        ],
    }


def _profile_payload(session: ResearchSession) -> dict[str, Any]:
    profile = session.local_state.profile
    return {
        **_auth_payload(session),
        "catalogs": _catalogs(),
        "section_marks": {group: section_mark(group) for group in _SECTION_GROUPS},
        "turn_limit": MAX_TURN_TAGS,
        "profile": {
            "display_name": profile.display_name,
            "about": profile.about,
            "home_region": profile.home_region,
            "gender_identities": list(profile.gender_identities),
            "smoking": profile.smoking,
            "drinking": profile.drinking,
            "drugs": profile.drugs,
            "turn_ons": list(profile.turn_ons),
            "lifestyle_tags": list(profile.lifestyle_tags),
            "hobby_tags": list(profile.hobby_tags),
            "personality_tags": list(profile.personality_tags),
            "bedroom_tags": list(profile.bedroom_tags),
        },
        "verified_host": session.verified_host,
        "boosts": session.boosts_remaining(),
        "superlikes": session.superlikes_remaining(),
        "photo_limit": PROFILE_PHOTO_SLOTS,
        "photo_count": session.filled_photo_count(),
        "photos": [
            {"slot": slot, "url": f"/api/profile/photos/{slot}"}
            for slot in range(PROFILE_PHOTO_SLOTS)
            if session.profile_photo_at(slot) is not None
        ],
    }


def _filters_payload(session: ResearchSession) -> dict[str, Any]:
    return {
        "catalogs": _catalogs(),
        "section_marks": {group: section_mark(group) for group in _SECTION_GROUPS},
        "values": {
            "immediate_intent": list(session.selected_looking),
            "relational_openness": list(session.selected_openness),
            "show_genders": list(session.selected_genders),
            "show_smoking": list(session.selected_smoking),
            "show_drinking": list(session.selected_drinking),
            "show_drugs": list(session.selected_drugs),
            "show_turn_ons": list(session.selected_turn_ons),
        },
    }


def _community_payload(session: ResearchSession) -> dict[str, Any]:
    rows = []
    for case in session.moderation_cases():
        profile = session.candidate_profile(case.report.subject_profile_id)
        status = case.status.value if hasattr(case.status, "value") else str(case.status)
        suspicious = sum(
            1
            for vote in case.votes
            if (vote.choice.value if hasattr(vote.choice, "value") else str(vote.choice))
            == "suspicious"
        )
        rows.append(
            {
                "id": case.id,
                "status": status,
                "contained": case.contained,
                "review_complete": case.review_complete,
                "subject": profile.display_name,
                "age_band": profile.age_band,
                "about": profile.about,
                "reason": case.report.reason.value
                if hasattr(case.report.reason, "value")
                else str(case.report.reason),
                "evidence_note": case.report.evidence_note,
                "vote_count": len(case.votes),
                "suspicious_votes": suspicious,
                "risk_score": case.risk_score,
                "risk_reasons": [reason.replace("_", " ") for reason in case.risk_reasons],
                "can_appeal": case.contained
                and status not in _FINAL_CASE_STATUSES
                and status != "appealed_pending_review",
                "can_adjudicate": (case.review_complete or case.contained)
                and status not in _FINAL_CASE_STATUSES,
                "reviewers": [
                    {
                        "id": reviewer.id,
                        "account_age_days": reviewer.account_age_days,
                        "reputation": reviewer.moderation_reputation,
                    }
                    for reviewer in session.eligible_reviewers(case.id)
                ],
            }
        )
    return {"cases": rows}


def _catalogs() -> dict[str, list[dict[str, str]]]:
    return {
        "gender": _choices(GENDER_OPTIONS, "gender"),
        "preference": _choices(GENDER_OPTIONS, "preference"),
        "smoking": _choices(SMOKING_OPTIONS, "smoking"),
        "drinking": _choices(DRINKING_OPTIONS, "drinking"),
        "drugs": _choices(DRUGS_OPTIONS, "drugs"),
        "turn_ons": _choices(TURN_ON_OPTIONS, "turn_ons"),
        "looking": _choices(IMMEDIATE_INTENTS, "looking"),
        "openness": _choices(RELATIONAL_OPENNESS, "openness"),
        "interests": _choices(INTEREST_OPTIONS, "interests"),
        "hobbies": _choices(HOBBY_OPTIONS, "hobbies"),
        "personality": _choices(PERSONALITY_OPTIONS, "personality"),
        "bedroom": _choices(BEDROOM_OPTIONS, "bedroom"),
    }


def _choices(options: tuple[str, ...], group: str) -> list[dict[str, str]]:
    return [
        {"id": option, "label": choice_label(option), "icon": choice_icon(option, group)}
        for option in options
    ]


def _looking_line(profile: Any) -> str:
    return f"{choice_label(profile.immediate_intent)} · {choice_label(profile.relational_openness)}"


def _api_photo_urls(candidate_id: str, photo_count: int) -> tuple[str, ...]:
    base = f"/api/discover/photos/{quote(candidate_id, safe='')}"
    return tuple(f"{base}/{slot}" for slot in range(photo_count))


def _first_photo_url(session: ResearchSession, candidate_id: str) -> str:
    urls = _api_photo_urls(candidate_id, session.deck_photo_count(candidate_id))
    return urls[0] if urls else ""


def _matched_with_payload(
    session: ResearchSession, candidate_id: str, match_id: str
) -> dict[str, Any]:
    match = session.conversations.matches.get(match_id)
    getfkd = bool(match.getfkd) if match is not None else False
    try:
        profile = session.candidate_profile(candidate_id)
    except DomainError:
        return {
            "match_id": match_id,
            "display_name": "",
            "age_band": "",
            "photo_url": "",
            "getfkd": getfkd,
        }
    return {
        "match_id": match_id,
        "display_name": profile.display_name,
        "age_band": profile.age_band,
        "photo_url": _first_photo_url(session, candidate_id),
        "getfkd": getfkd,
    }


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    return [str(item) for item in value if str(item)]


async def _json_body(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return {}
    payload = await request.json()
    return payload if isinstance(payload, dict) else {}


def _ok(payload: dict[str, Any]) -> JSONResponse:
    return JSONResponse(payload)


def _error(
    message: str,
    *,
    status_code: int,
    code: str = "",
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"error": message, "code": code or message}
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status_code)

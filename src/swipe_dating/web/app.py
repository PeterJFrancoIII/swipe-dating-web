"""FastAPI/Jinja adapter for the canonical synthetic Swipe Dating web experience."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from swipe_dating.adapters.storage import LocalStateRepository, MemoryStorageAdapter
from swipe_dating.application.session import ResearchSession
from swipe_dating.domain.bot_moderation import ReportReason, VoteChoice
from swipe_dating.domain.discovery import IMMEDIATE_INTENTS, RELATIONAL_OPENNESS
from swipe_dating.domain.errors import DomainError

SESSION_COOKIE = "swipe_rnd_session"
WEB_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(WEB_ROOT / "templates"))

FEATURE_PROXIMITY = False
FEATURE_MATCH_MAP = False
FEATURE_SKIN_SHOP = False
BOUNDARY_OPTIONS = (
    "condoms_required",
    "recent_testing_discussion",
    "public_first_meet",
    "sober_meetup",
    "no_group_encounters",
    "group_encounter_open",
    "no_smoking",
    "no_drugs",
)
REPORT_OPTIONS = (
    (ReportReason.AUTOMATION_PATTERN, "Suspected bot"),
    (ReportReason.SCAM, "Scam"),
    (ReportReason.IMPERSONATION, "Impersonation"),
    (ReportReason.STOLEN_PHOTOS, "Stolen photos"),
    (ReportReason.SPAM_LINKS, "Spam links"),
    (ReportReason.OTHER_ABUSE, "Other abuse"),
)


class BrowserSessionStore:
    """Process-local synthetic sessions addressed by an opaque browser cookie."""

    def __init__(
        self,
        *,
        clock: Callable[[], int] | None = None,
        today: str | None = None,
    ) -> None:
        self._clock = clock
        self._today = today
        self._sessions: dict[str, ResearchSession] = {}

    def create(self) -> tuple[str, ResearchSession]:
        token = secrets.token_urlsafe(32)
        session = ResearchSession(
            repository=LocalStateRepository(MemoryStorageAdapter()),
            clock=self._clock,
            today=self._today or date.today().isoformat(),
        )
        self._sessions[token] = session
        return token, session

    def get(self, token: str | None) -> ResearchSession | None:
        if token is None:
            return None
        return self._sessions.get(token)


def create_web_app(
    *,
    clock: Callable[[], int] | None = None,
    today: str | None = None,
    session_store: BrowserSessionStore | None = None,
) -> FastAPI:
    sessions = session_store or BrowserSessionStore(clock=clock, today=today)
    application = FastAPI(
        title="Swipe Dating Web R&D",
        version="0.3.0",
        docs_url=None,
        redoc_url=None,
    )
    application.state.session_store = sessions
    application.mount(
        "/static",
        StaticFiles(directory=str(WEB_ROOT / "static")),
        name="static",
    )
    _register_gate_routes(application, sessions)
    _register_discovery_routes(application, sessions)
    _register_profile_routes(application, sessions)
    _register_community_routes(application, sessions)
    _register_match_routes(application, sessions)
    _register_match_control_routes(application, sessions)
    return application


def _register_gate_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "python-web-synthetic-only"}

    @application.get("/", response_class=HTMLResponse)
    async def age_gate(request: Request) -> Response:
        token, session, created = _ensure_session(request, sessions)
        if session.adult_accepted:
            return RedirectResponse("/discover", status_code=303)
        response = _render(
            request,
            "age_gate.html",
            session=session,
            birth_date="",
            error=None,
        )
        if created:
            _set_session_cookie(response, token)
        return response

    @application.post("/age-gate", response_class=HTMLResponse)
    async def accept_age_gate(
        request: Request,
        birth_date: Annotated[str, Form()],
    ) -> Response:
        token, session, created = _ensure_session(request, sessions)
        try:
            session.accept_adult_gate(birth_date)
        except DomainError as error:
            message = (
                "Use YYYY-MM-DD only, for example 2000-01-01."
                if error.code == "birth_date_invalid"
                else "You must be at least 18 years old to continue."
            )
            response = _render(
                request,
                "age_gate.html",
                session=session,
                birth_date=birth_date,
                error=message,
                status_code=400,
            )
            if created:
                _set_session_cookie(response, token)
            return response
        response = RedirectResponse("/discover", status_code=303)
        if created:
            _set_session_cookie(response, token)
        return response


def _register_discovery_routes(
    application: FastAPI,
    sessions: BrowserSessionStore,
) -> None:
    @application.get("/discover", response_class=HTMLResponse)
    async def discover(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        return _render(
            request,
            "discover.html",
            session=session,
            candidate=session.current_candidate(),
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
            report_options=REPORT_OPTIONS,
            feature_proximity=FEATURE_PROXIMITY,
        )

    @application.post("/discover/pass")
    async def pass_candidate(
        request: Request,
        candidate_id: Annotated[str, Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.pass_candidate(candidate_id)
        except DomainError as error:
            return _redirect("/discover", error=_domain_message(error))
        return _redirect(
            "/discover",
            notice="Passed. Your choice stays in this session only.",
        )

    @application.post("/discover/interest")
    async def express_interest(
        request: Request,
        candidate_id: Annotated[str, Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            outcome = session.express_interest(candidate_id)
        except DomainError as error:
            return _redirect("/discover", error=_domain_message(error))
        if outcome.get("matched") is True:
            match_id = str(outcome.get("match_id", ""))
            display_name = session.match(match_id).candidate.display_name
            return _redirect(
                "/matches",
                notice=f"It's a match. Open {display_name} to chat.",
            )
        return _redirect(
            "/discover",
            notice="Like sent. A match only appears after mutual interest.",
        )

    @application.post("/discover/undo")
    async def undo_decision(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        outcome = session.undo_last_decision()
        if outcome.get("restored_candidate_id"):
            return _redirect(
                "/discover",
                notice="Your last non-match decision was restored.",
            )
        if outcome.get("kind") == "match_requires_unmatch":
            return _redirect(
                "/discover",
                error="Matches cannot be rewound. Unmatch from the chat instead.",
            )
        return _redirect("/discover", notice="There is nothing to undo yet.")

    @application.post("/discover/report")
    async def report_candidate(
        request: Request,
        candidate_id: Annotated[str, Form()],
        reason: Annotated[str, Form()],
        evidence_note: Annotated[str, Form()] = "",
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            case = session.report_suspected_bot(
                candidate_id,
                ReportReason(reason),
                evidence_note=evidence_note,
            )
        except (DomainError, ValueError) as error:
            message = (
                _domain_message(error)
                if isinstance(error, DomainError)
                else "Unknown report reason."
            )
            return _redirect("/discover", error=message)
        return _redirect(
            "/community",
            notice=f"Report received. {case.id} is in private community review.",
        )


def _register_profile_routes(
    application: FastAPI,
    sessions: BrowserSessionStore,
) -> None:
    @application.get("/profile", response_class=HTMLResponse)
    async def profile(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        return _render(
            request,
            "profile.html",
            session=session,
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
            readiness=session.profile_readiness(),
            feature_skin_shop=FEATURE_SKIN_SHOP,
        )

    @application.post("/profile")
    async def save_profile(
        request: Request,
        display_name: Annotated[str, Form()],
        about: Annotated[str, Form()],
        pronouns: Annotated[str, Form()] = "",
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        session.update_profile(
            display_name=display_name.strip()[:64],
            about=about.strip()[:500],
            pronouns=pronouns.strip()[:64],
        )
        return _redirect(
            "/profile",
            notice="Profile saved to this local R&D session.",
        )

    @application.get("/filters", response_class=HTMLResponse)
    async def filters(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        return _render(
            request,
            "filters.html",
            session=session,
            immediate_intents=IMMEDIATE_INTENTS,
            relational_options=RELATIONAL_OPENNESS,
            boundary_options=BOUNDARY_OPTIONS,
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
        )

    @application.post("/filters")
    async def save_filters(
        request: Request,
        immediate_intent: Annotated[str, Form()],
        relational_openness: Annotated[str, Form()],
        required_boundaries: Annotated[list[str], Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        invalid_intent = immediate_intent not in IMMEDIATE_INTENTS
        invalid_openness = relational_openness not in RELATIONAL_OPENNESS
        if invalid_intent or invalid_openness:
            return _redirect(
                "/filters",
                error="Choose supported Looking For options.",
            )
        safe_boundaries = tuple(
            value for value in required_boundaries if value in BOUNDARY_OPTIONS
        )
        session.update_preferences(
            immediate_intent=immediate_intent,
            relational_openness=relational_openness,
            required_boundaries=safe_boundaries,
        )
        return _redirect(
            "/discover",
            notice="Filters updated. Ranking weights remain fixed.",
        )


def _register_community_routes(
    application: FastAPI,
    sessions: BrowserSessionStore,
) -> None:
    @application.get("/community", response_class=HTMLResponse)
    async def community_review(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        case_rows = tuple(
            {
                "case": case,
                "profile": session.candidate_profile(case.report.subject_profile_id),
                "reviewers": session.eligible_reviewers(case.id),
            }
            for case in session.moderation_cases()
        )
        return _render(
            request,
            "community.html",
            session=session,
            case_rows=case_rows,
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
        )

    @application.post("/community/{case_id}/vote")
    async def vote_on_case(
        request: Request,
        case_id: str,
        reviewer_id: Annotated[str, Form()],
        choice: Annotated[str, Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.vote_on_bot_case(case_id, reviewer_id, VoteChoice(choice))
        except (DomainError, ValueError) as error:
            message = (
                _domain_message(error)
                if isinstance(error, DomainError)
                else "Unknown vote."
            )
            return _redirect("/community", error=message)
        return _redirect(
            "/community",
            notice="One private synthetic review vote was recorded.",
        )

    @application.post("/community/{case_id}/appeal")
    async def appeal_case(request: Request, case_id: str) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.appeal_bot_containment(case_id)
        except DomainError as error:
            return _redirect("/community", error=_domain_message(error))
        return _redirect(
            "/community",
            notice="Synthetic appeal opened. Containment remains pending review.",
        )

    @application.post("/community/{case_id}/adjudicate")
    async def adjudicate_case(request: Request, case_id: str) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            case = session.run_synthetic_adjudication(case_id)
        except DomainError as error:
            return _redirect("/community", error=_domain_message(error))
        outcome = "bot removed from discovery" if case.contained else "human restored"
        return _redirect(
            "/community",
            notice=f"Synthetic fixture adjudicated: {outcome}.",
        )


def _register_match_routes(
    application: FastAPI,
    sessions: BrowserSessionStore,
) -> None:
    @application.get("/matches", response_class=HTMLResponse)
    async def matches(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        return _render(
            request,
            "matches.html",
            session=session,
            matches=session.active_matches(),
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
        )

    @application.get("/matches/{match_id:path}", response_class=HTMLResponse)
    async def chat(request: Request, match_id: str) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            match = session.match(match_id)
            profile = session.candidate_profile(match.candidate.id)
            meetup_suggestions = session.meetup_suggestions(match_id)
        except DomainError as error:
            return _redirect("/matches", error=_domain_message(error))
        return _render(
            request,
            "chat.html",
            session=session,
            match=match,
            profile=profile,
            meetup_suggestions=meetup_suggestions,
            report_options=REPORT_OPTIONS,
            feature_match_map=FEATURE_MATCH_MAP,
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
        )

    @application.post("/matches/{match_id:path}/message")
    async def message(
        request: Request,
        match_id: str,
        text: Annotated[str, Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.send_message(match_id, text)
        except DomainError as error:
            return _redirect(_chat_path(match_id), error=_domain_message(error))
        return _redirect(_chat_path(match_id))

    @application.post("/matches/{match_id:path}/meetup")
    async def plan_meetup(
        request: Request,
        match_id: str,
        suggestion_id: Annotated[str, Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.propose_meetup(match_id, suggestion_id)
        except DomainError as error:
            return _redirect(_chat_path(match_id), error=_domain_message(error))
        return _redirect(
            _chat_path(match_id),
            notice="Meetup proposal added. No location was shared.",
        )

    @application.post("/matches/{match_id:path}/extend")
    async def extend_chat(request: Request, match_id: str) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.extend_messages(match_id)
        except DomainError as error:
            return _redirect(_chat_path(match_id), error=_domain_message(error))
        return _redirect(
            _chat_path(match_id),
            notice="Synthetic mutual extension applied once.",
        )


def _register_match_control_routes(
    application: FastAPI,
    sessions: BrowserSessionStore,
) -> None:
    @application.post("/matches/{match_id:path}/unmatch")
    async def unmatch(request: Request, match_id: str) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.unmatch(match_id)
        except DomainError as error:
            return _redirect(_chat_path(match_id), error=_domain_message(error))
        return _redirect(
            "/matches",
            notice="Unmatched. This conversation is no longer active.",
        )

    @application.post("/matches/{match_id:path}/block")
    async def block(request: Request, match_id: str) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.block(match_id)
        except DomainError as error:
            return _redirect(_chat_path(match_id), error=_domain_message(error))
        return _redirect(
            "/matches",
            notice="Blocked. Visible conversation content was purged.",
        )

    @application.post("/matches/{match_id:path}/report")
    async def report_match(
        request: Request,
        match_id: str,
        reason: Annotated[str, Form()],
        evidence_note: Annotated[str, Form()] = "",
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            match = session.match(match_id)
            session.report_suspected_bot(
                match.candidate.id,
                ReportReason(reason),
                evidence_note=evidence_note,
            )
        except (DomainError, ValueError) as error:
            message_text = (
                _domain_message(error)
                if isinstance(error, DomainError)
                else "Unknown report reason."
            )
            return _redirect(_chat_path(match_id), error=message_text)
        return _redirect(
            "/community",
            notice="Conversation report entered private community review.",
        )


def _ensure_session(
    request: Request,
    sessions: BrowserSessionStore,
) -> tuple[str, ResearchSession, bool]:
    existing_token = request.cookies.get(SESSION_COOKIE)
    existing_session = sessions.get(existing_token)
    if existing_token is not None and existing_session is not None:
        return existing_token, existing_session, False
    token, session = sessions.create()
    return token, session, True


def _adult_session(
    request: Request,
    sessions: BrowserSessionStore,
) -> ResearchSession | None:
    session = sessions.get(request.cookies.get(SESSION_COOKIE))
    if session is None or not session.adult_accepted:
        return None
    return session


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


def _chat_path(match_id: str) -> str:
    return f"/matches/{quote(match_id, safe='')}"


def _redirect(
    path: str,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    query = {
        key: value
        for key, value in {"notice": notice, "error": error}.items()
        if value is not None
    }
    location = f"{path}?{urlencode(query)}" if query else path
    return RedirectResponse(location, status_code=303)


def _domain_message(error: DomainError) -> str:
    messages = {
        "adult_gate_required": "Complete the adults-only gate first.",
        "candidate_not_found": "That synthetic profile is unavailable.",
        "candidate_temporarily_contained": (
            "That profile is temporarily hidden pending review."
        ),
        "candidate_already_decided": "You already made a decision on this profile.",
        "duplicate_bot_vote": "Each trusted reviewer gets one vote per case.",
        "reviewer_not_eligible": "This synthetic reviewer is not eligible to vote.",
        "reviewer_not_independent": "Review quorum requires independent trust clusters.",
        "case_voting_closed": "Community voting is closed for this case.",
        "case_not_contained": "Only a contained profile can appeal.",
        "case_not_ready_for_adjudication": (
            "Complete community review before adjudication."
        ),
        "case_already_adjudicated": "This case already has a synthetic adjudication.",
        "report_limit_reached": "The synthetic report limit has been reached.",
        "active_bot_case_exists": "That profile already has an active private review.",
        "match_not_found": "That match is unavailable.",
        "match_not_active": "That match is no longer active.",
        "message_required": "Write a message before sending.",
        "message_too_long": "Messages are limited to 500 characters.",
        "message_limit_reached": (
            "This chat reached its message limit. Plan a meetup, extend once, or unmatch."
        ),
        "message_extension_already_used": (
            "The one-time message extension was already used."
        ),
        "message_extension_not_available": (
            "The extension becomes available when the current limit is reached."
        ),
        "unknown_meetup_suggestion": "Choose one of the available meetup ideas.",
    }
    return messages.get(error.code, error.code.replace("_", " "))


def _render(
    request: Request,
    template_name: str,
    *,
    session: ResearchSession,
    status_code: int = 200,
    **context: object,
) -> Response:
    return TEMPLATES.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "session": session,
            "current_path": request.url.path,
            **context,
        },
        status_code=status_code,
    )


app = create_web_app()

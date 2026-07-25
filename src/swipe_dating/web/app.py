"""FastAPI/Jinja adapter for the focused synthetic bot-control research flow."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from swipe_dating.adapters.storage import LocalStateRepository, MemoryStorageAdapter
from swipe_dating.application.session import ResearchSession
from swipe_dating.domain.bot_moderation import ReportReason, VoteChoice
from swipe_dating.domain.conversations import MatchStatus
from swipe_dating.domain.errors import DomainError

SESSION_COOKIE = "swipe_rnd_session"
WEB_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(WEB_ROOT / "templates"))


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
        title="Swipe Dating Bot-Control R&D",
        version="0.2.0",
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
    _register_community_routes(application, sessions)
    _register_match_routes(application, sessions)
    return application


def _register_gate_routes(
    application: FastAPI,
    sessions: BrowserSessionStore,
) -> None:
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
            birth_date="2000-01-01",
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
        return _redirect("/discover", notice="Profile passed. The decision stays in memory.")

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
            return _redirect("/matches", notice="It's a match - reciprocal synthetic interest.")
        return _redirect("/discover", notice="Interest recorded. No unilateral match was created.")

    @application.post("/discover/report")
    async def report_candidate(
        request: Request,
        candidate_id: Annotated[str, Form()],
        reason: Annotated[str, Form()],
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            case = session.report_suspected_bot(candidate_id, ReportReason(reason))
        except (DomainError, ValueError) as error:
            message = (
                _domain_message(error)
                if isinstance(error, DomainError)
                else "Unknown report reason."
            )
            return _redirect("/discover", error=message)
        return _redirect(
            "/community",
            notice=f"{case.id} opened. Only eligible synthetic reviewers can vote.",
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
            message = _domain_message(error) if isinstance(error, DomainError) else "Unknown vote."
            return _redirect("/community", error=message)
        return _redirect("/community", notice=f"{reviewer_id} cast one synthetic vote.")

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
        outcome = "bot" if case.contained else "human"
        return _redirect(
            "/community",
            notice=f"Synthetic fixture adjudicated this profile as {outcome}.",
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
        active_matches = tuple(
            match
            for match in session.conversations.matches.values()
            if match.status is MatchStatus.ACTIVE
        )
        return _render(
            request,
            "matches.html",
            session=session,
            matches=active_matches,
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
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


def _redirect(
    path: str,
    *,
    notice: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    query = {
        key: value
        for key, value in {
            "notice": notice,
            "error": error,
        }.items()
        if value is not None
    }
    location = f"{path}?{urlencode(query)}" if query else path
    return RedirectResponse(location, status_code=303)


def _domain_message(error: DomainError) -> str:
    messages = {
        "adult_gate_required": "Complete the adults-only gate first.",
        "candidate_not_found": "That synthetic profile is unavailable.",
        "candidate_temporarily_contained": "That profile is temporarily buried pending review.",
        "duplicate_bot_vote": "Each trusted reviewer gets one vote per case.",
        "reviewer_not_eligible": "This synthetic reviewer is not eligible to vote.",
        "reviewer_not_independent": "Review quorum requires independent trust clusters.",
        "case_voting_closed": "Community voting is closed for this case.",
        "case_not_contained": "Only a contained profile can appeal.",
        "case_not_ready_for_adjudication": "Complete community review before adjudication.",
        "case_already_adjudicated": "This case already has a synthetic adjudication.",
        "report_limit_reached": "The synthetic report limit has been reached.",
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

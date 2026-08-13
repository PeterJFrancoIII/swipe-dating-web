"""FastAPI/Jinja adapter for the canonical synthetic Swipe Dating web experience."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated, TypedDict
from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from swipe_dating.adapters.storage import LocalStateRepository, MemoryStorageAdapter
from swipe_dating.application.session import ResearchSession
from swipe_dating.domain.adult import parse_date_only
from swipe_dating.domain.bot_moderation import ReportReason, VoteChoice
from swipe_dating.domain.discovery import IMMEDIATE_INTENTS, RELATIONAL_OPENNESS
from swipe_dating.domain.errors import DomainError
from swipe_dating.domain.gender_catalog import GENDER_OPTIONS, gender_labels
from swipe_dating.domain.preferences import (
    BEDROOM_OPTIONS,
    HOBBY_OPTIONS,
    INTEREST_OPTIONS,
    PERSONALITY_OPTIONS,
    choice_label,
    combined_profile_tags,
    visibility_from_form,
)
from swipe_dating.domain.profile_photos import (
    PROFILE_PHOTO_MAX_UPLOAD_BYTES,
    PROFILE_PHOTO_SLOTS,
    ProfilePhoto,
)

SESSION_COOKIE = "swipe_rnd_session"
WEB_ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(WEB_ROOT / "templates"))
TEMPLATES.env.filters["choice_label"] = choice_label

FEATURE_PROXIMITY = False
FEATURE_MATCH_MAP = False
FEATURE_SKIN_SHOP = False
EARLIEST_BIRTH_YEAR = 1900
BIRTH_MONTHS = tuple(f"{month:02d}" for month in range(1, 13))
BIRTH_DAYS = tuple(f"{day:02d}" for day in range(1, 32))


class DatingCardContext(TypedDict):
    card_name: str
    card_age: int | None
    card_about: str
    card_pronouns: str
    card_tags: tuple[str, ...]
    card_interests: tuple[str, ...]
    card_hobbies: tuple[str, ...]
    card_personality: tuple[str, ...]
    card_bedroom: tuple[str, ...]
    card_gender: str
    card_looking: str
    photo_index: int
    photo_count: int
    photo_url: str
    heif_url: str
    prev_photo: int
    next_photo: int
    monogram: str


class AgeGatePickerContext(TypedDict):
    birth_date: str
    birth_months: tuple[str, ...]
    birth_days: tuple[str, ...]
    birth_years: tuple[str, ...]
    selected_month: str
    selected_day: str
    selected_year: str


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
        self._shares: dict[str, str] = {}

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

    def publish_share(self, session_token: str, session: ResearchSession) -> str:
        share = session.ensure_share_token()
        self._shares[share] = session_token
        return share

    def get_by_share(self, share: str) -> ResearchSession | None:
        session_token = self._shares.get(share)
        if session_token is None:
            return None
        session = self._sessions.get(session_token)
        if session is None or session.share_token != share:
            self._shares.pop(share, None)
            return None
        return session


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


def compose_submitted_birth_date(
    *,
    birth_date: str,
    birth_month: str,
    birth_day: str,
    birth_year: str,
) -> str:
    """Prefer a direct ISO date, otherwise compose MM/DD/YYYY wheel values."""
    direct = birth_date.strip()
    if direct:
        return direct
    month = birth_month.strip()
    day = birth_day.strip()
    year = birth_year.strip()
    if not (month.isdigit() and day.isdigit() and year.isdigit()):
        return ""
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def birth_date_parts(birth_date: str) -> tuple[str, str, str]:
    parsed = parse_date_only(birth_date)
    if parsed is None:
        return "", "", ""
    return f"{parsed.month:02d}", f"{parsed.day:02d}", f"{parsed.year:04d}"


def birth_year_choices(today: str) -> tuple[str, ...]:
    parsed = parse_date_only(today)
    latest = parsed.year if parsed is not None else date.today().year
    adult_birth_year = latest - 18
    adult_years = tuple(
        f"{year:04d}" for year in range(adult_birth_year, EARLIEST_BIRTH_YEAR - 1, -1)
    )
    later_years = tuple(f"{year:04d}" for year in range(adult_birth_year + 1, latest + 1))
    return adult_years + later_years


def age_gate_picker_context(today: str, birth_date: str) -> AgeGatePickerContext:
    selected_month, selected_day, selected_year = birth_date_parts(birth_date)
    return {
        "birth_date": birth_date,
        "birth_months": BIRTH_MONTHS,
        "birth_days": BIRTH_DAYS,
        "birth_years": birth_year_choices(today),
        "selected_month": selected_month,
        "selected_day": selected_day,
        "selected_year": selected_year,
    }


def _register_gate_routes(application: FastAPI, sessions: BrowserSessionStore) -> None:
    @application.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": "python-web-synthetic-only"}

    @application.get("/", response_class=HTMLResponse)
    async def age_gate(request: Request) -> Response:
        token, session, created = _ensure_session(request, sessions)
        nxt = _safe_next_path(request.query_params.get("next"))
        if session.adult_accepted:
            return RedirectResponse(nxt or "/discover", status_code=303)
        response = _render(
            request,
            "age_gate.html",
            session=session,
            error=None,
            next_path=nxt or "",
            **age_gate_picker_context(session.today, ""),
        )
        if created:
            _set_session_cookie(response, token)
        return response

    @application.post("/age-gate", response_class=HTMLResponse)
    async def accept_age_gate(
        request: Request,
        birth_date: Annotated[str, Form()] = "",
        birth_month: Annotated[str, Form()] = "",
        birth_day: Annotated[str, Form()] = "",
        birth_year: Annotated[str, Form()] = "",
        next_path: Annotated[str, Form()] = "",
    ) -> Response:
        token, session, created = _ensure_session(request, sessions)
        submitted = compose_submitted_birth_date(
            birth_date=birth_date,
            birth_month=birth_month,
            birth_day=birth_day,
            birth_year=birth_year,
        )
        try:
            session.accept_adult_gate(submitted)
        except DomainError as error:
            message = (
                "Choose a real calendar date as month, day, and year."
                if error.code == "birth_date_invalid"
                else "You must be at least 18 years old to continue."
            )
            response = _render(
                request,
                "age_gate.html",
                session=session,
                error=message,
                status_code=400,
                next_path=_safe_next_path(next_path) or "",
                **age_gate_picker_context(session.today, submitted),
            )
            if created:
                _set_session_cookie(response, token)
            return response
        response = RedirectResponse(
            _safe_next_path(next_path) or "/discover",
            status_code=303,
        )
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


def _register_profile_routes(  # noqa: PLR0915
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
            profile_age=session.profile_age(),
            photo_slots=tuple(range(PROFILE_PHOTO_SLOTS)),
            photo_limit=PROFILE_PHOTO_SLOTS,
            next_photo_slot=session.next_empty_photo_slot(),
            share_url=(
                f"{str(request.base_url).rstrip('/')}/p/{session.share_token}"
                if session.share_token
                else ""
            ),
            gender_options=GENDER_OPTIONS,
            lifestyle_options=INTEREST_OPTIONS,
            hobby_options=HOBBY_OPTIONS,
            personality_options=PERSONALITY_OPTIONS,
            bedroom_options=BEDROOM_OPTIONS,
            feature_skin_shop=FEATURE_SKIN_SHOP,
        )

    @application.post("/profile")
    async def save_profile(
        request: Request,
        display_name: Annotated[str, Form()] = "",
        about: Annotated[str, Form()] = "",
        pronouns: Annotated[str, Form()] = "",
        gender_identities: Annotated[list[str] | None, Form()] = None,
        photo_id: Annotated[str, Form()] = "",
        show_genders: Annotated[list[str] | None, Form()] = None,
        lifestyle_tags: Annotated[list[str] | None, Form()] = None,
        hobby_tags: Annotated[list[str] | None, Form()] = None,
        personality_tags: Annotated[list[str] | None, Form()] = None,
        bedroom_tags: Annotated[list[str] | None, Form()] = None,
        show_on_card: Annotated[list[str] | None, Form()] = None,
        card_visibility_present: Annotated[str, Form()] = "",
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        session.update_profile(
            display_name=display_name.strip()[:64],
            about=about.strip()[:500],
            pronouns=pronouns.strip()[:40],
            gender_identities=tuple(gender_identities or ()),
            photo_id=photo_id.strip(),
            feed_genders=tuple(show_genders or ()),
            lifestyle_tags=tuple(lifestyle_tags or ()),
            hobby_tags=tuple(hobby_tags or ()),
            personality_tags=tuple(personality_tags or ()),
            bedroom_tags=tuple(bedroom_tags or ()),
            visibility=visibility_from_form(
                show_on_card,
                present=card_visibility_present == "1",
            ),
        )
        return _redirect(
            "/profile",
            notice="Profile saved to this local R&D session.",
        )

    @application.post("/profile/photos")
    async def add_profile_photo(
        request: Request,
        slot: Annotated[str, Form()] = "",
        photo: Annotated[list[UploadFile] | None, File()] = None,
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        uploads = list(photo or ())
        if not uploads:
            return _redirect("/profile", error="Choose photos, then tap Add photos.")
        try:
            if slot.strip() != "" and len(uploads) == 1:
                payload = await uploads[0].read(PROFILE_PHOTO_MAX_UPLOAD_BYTES + 1)
                session.set_profile_photo(int(slot.strip()), payload)
                return _redirect("/profile", notice="Photo added to this session only.")
            added = 0
            unused = 0
            last_error: DomainError | None = None
            for upload in uploads:
                if session.next_empty_photo_slot() is None:
                    unused += 1
                    continue
                payload = await upload.read(PROFILE_PHOTO_MAX_UPLOAD_BYTES + 1)
                try:
                    session.add_profile_photo(payload)
                    added += 1
                except DomainError as error:
                    last_error = error
            if added == 0:
                message = (
                    _domain_message(last_error)
                    if last_error is not None
                    else "Choose photos, then tap Add photos."
                )
                return _redirect("/profile", error=message)
            notice = (
                "Photo added to this session only."
                if added == 1
                else f"{added} photos added to this session only."
            )
            if unused:
                notice += f" Extras were skipped because {PROFILE_PHOTO_SLOTS} is the limit."
            return _redirect("/profile", notice=notice)
        except (DomainError, ValueError) as error:
            message = (
                _domain_message(error)
                if isinstance(error, DomainError)
                else "Choose one of the six photo slots."
            )
            return _redirect("/profile", error=message)

    @application.post("/profile/photos/reorder")
    async def reorder_profile_photos(
        request: Request,
        order: Annotated[list[int] | None, Form()] = None,
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.reorder_profile_photos(tuple(order or ()))
        except DomainError as error:
            return _redirect("/profile", error=_domain_message(error))
        return _redirect("/profile", notice="Photo order updated.")

    @application.post("/profile/photos/{slot}/move")
    async def move_profile_photo(
        request: Request,
        slot: int,
        direction: Annotated[str, Form()] = "",
    ) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.move_profile_photo(slot, direction)
        except DomainError as error:
            return _redirect("/profile", error=_domain_message(error))
        return _redirect("/profile", notice="Photo order updated.")

    @application.post("/profile/photos/{slot}/remove")
    async def remove_profile_photo(request: Request, slot: int) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        try:
            session.clear_profile_photo(slot)
        except DomainError as error:
            return _redirect("/profile", error=_domain_message(error))
        return _redirect("/profile", notice="Photo removed.")

    @application.get("/profile/photos/{slot}")
    async def show_profile_photo(request: Request, slot: int) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        stored = session.profile_photo_at(slot)
        if stored is None:
            return Response(status_code=404)
        return _photo_response(stored, heif=False)

    @application.get("/profile/photos/{slot}/heif")
    async def show_profile_photo_heif(request: Request, slot: int) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        stored = session.profile_photo_at(slot)
        if stored is None:
            return Response(status_code=404)
        return _photo_response(stored, heif=True)

    @application.get("/profile/preview", response_class=HTMLResponse)
    async def preview_profile(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        photo_index = _photo_index(request)
        return _render(
            request,
            "profile_preview.html",
            session=session,
            **_card_context(session, photo_index, "/profile/photos"),
        )

    @application.post("/profile/share")
    async def share_profile(request: Request) -> Response:
        session = _adult_session(request, sessions)
        if session is None:
            return RedirectResponse("/", status_code=303)
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie is None:
            return RedirectResponse("/", status_code=303)
        sessions.publish_share(cookie, session)
        return _redirect(
            "/profile",
            notice=(
                "Share link ready. Anyone 18+ with the link can open this card "
                "while this local session is running."
            ),
        )

    @application.get("/p/{share}", response_class=HTMLResponse)
    async def shared_profile(request: Request, share: str) -> Response:
        viewer = _adult_session(request, sessions)
        if viewer is None:
            return RedirectResponse(f"/?next=/p/{share}", status_code=303)
        owner = sessions.get_by_share(share)
        if owner is None or not owner.adult_accepted:
            return Response("This profile link is unavailable.", status_code=404)
        photo_index = _photo_index(request)
        return _render(
            request,
            "profile_share.html",
            session=viewer,
            **_card_context(owner, photo_index, f"/p/{share}/photos"),
        )

    @application.get("/p/{share}/photos/{slot}")
    async def shared_profile_photo(request: Request, share: str, slot: int) -> Response:
        return _shared_photo(request, sessions, share, slot, heif=False)

    @application.get("/p/{share}/photos/{slot}/heif")
    async def shared_profile_photo_heif(request: Request, share: str, slot: int) -> Response:
        return _shared_photo(request, sessions, share, slot, heif=True)

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
            gender_options=GENDER_OPTIONS,
            boundary_options=BOUNDARY_OPTIONS,
            error=request.query_params.get("error"),
            notice=request.query_params.get("notice"),
        )

    @application.post("/filters")
    async def save_filters(
        request: Request,
        immediate_intent: Annotated[str, Form()],
        relational_openness: Annotated[str, Form()],
        required_boundaries: Annotated[list[str] | None, Form()] = None,
        show_genders: Annotated[list[str] | None, Form()] = None,
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
            value for value in (required_boundaries or []) if value in BOUNDARY_OPTIONS
        )
        session.update_preferences(
            immediate_intent=immediate_intent,
            relational_openness=relational_openness,
            required_boundaries=safe_boundaries,
            feed_genders=tuple(show_genders or ()),
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
            message = _domain_message(error) if isinstance(error, DomainError) else "Unknown vote."
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
        key: value for key, value in {"notice": notice, "error": error}.items() if value is not None
    }
    location = f"{path}?{urlencode(query)}" if query else path
    return RedirectResponse(location, status_code=303)


def _domain_message(error: DomainError) -> str:
    messages = {
        "adult_gate_required": "Complete the adults-only gate first.",
        "candidate_not_found": "That synthetic profile is unavailable.",
        "candidate_temporarily_contained": ("That profile is temporarily hidden pending review."),
        "candidate_already_decided": "You already made a decision on this profile.",
        "duplicate_bot_vote": "Each trusted reviewer gets one vote per case.",
        "reviewer_not_eligible": "This synthetic reviewer is not eligible to vote.",
        "reviewer_not_independent": "Review quorum requires independent trust clusters.",
        "case_voting_closed": "Community voting is closed for this case.",
        "case_not_contained": "Only a contained profile can appeal.",
        "case_not_ready_for_adjudication": ("Complete community review before adjudication."),
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
        "photo_slot_invalid": "Choose one of the six photo slots.",
        "photo_empty": "Choose photos, then tap Add photos.",
        "photo_order_invalid": "Drag the photos into the order you want.",
        "photo_too_large": (
            "That original is too large to process, or it could not be compressed under 5 MB."
        ),
        "photo_type_unsupported": "Use a JPEG, PNG, WebP, HEIC, or AVIF photo.",
        "photo_slots_full": "You already added 6 photos. Remove one to add another.",
        "photo_move_invalid": "Use Move up or Move down to change photo order.",
        "message_extension_already_used": ("The one-time message extension was already used."),
        "message_extension_not_available": (
            "The extension becomes available when the current limit is reached."
        ),
        "unknown_meetup_suggestion": "Choose one of the available meetup ideas.",
    }
    return messages.get(error.code, error.code.replace("_", " "))


def _photo_index(request: Request) -> int:
    raw = request.query_params.get("photo", "0")
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _photo_response(stored: ProfilePhoto, *, heif: bool) -> Response:
    return Response(
        content=stored.payload if heif else stored.display_payload,
        media_type=stored.content_type if heif else stored.display_content_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


def _shared_photo(
    request: Request,
    sessions: BrowserSessionStore,
    share: str,
    slot: int,
    *,
    heif: bool,
) -> Response:
    if _adult_session(request, sessions) is None:
        return RedirectResponse(f"/?next=/p/{share}", status_code=303)
    owner = sessions.get_by_share(share)
    if owner is None:
        return Response(status_code=404)
    stored = owner.profile_photo_at(slot)
    if stored is None:
        return Response(status_code=404)
    return _photo_response(stored, heif=heif)


def _safe_next_path(raw: str | None) -> str | None:
    if raw is None:
        return None
    path = raw.strip()
    if not path.startswith("/p/"):
        return None
    if any(marker in path for marker in ("://", "\\", "//", " ")):
        return None
    return path.split("?", 1)[0]


def _card_context(
    session: ResearchSession,
    photo_index: int,
    photo_base: str,
) -> DatingCardContext:
    profile = session.local_state.profile
    visibility = profile.visibility
    filled = session.filled_photo_count() if visibility.photos else 0
    index = photo_index % filled if filled else 0
    card_interests = profile.lifestyle_tags if visibility.interests else ()
    card_hobbies = profile.hobby_tags if visibility.hobbies else ()
    card_personality = profile.personality_tags if visibility.personality else ()
    card_bedroom = profile.bedroom_tags if visibility.bedroom else ()
    shown_name = profile.display_name.strip() if visibility.display_name else ""
    looking = (
        f"{session.immediate_intent.replace('_', ' ')}"
        f" · {session.relational_openness.replace('_', ' ')}"
        if visibility.looking_for
        else ""
    )
    return {
        "card_name": shown_name or "Someone",
        "card_age": session.profile_age() if visibility.age else None,
        "card_about": profile.about if visibility.about else "",
        "card_pronouns": profile.pronouns if visibility.pronouns else "",
        "card_tags": combined_profile_tags(card_interests, card_hobbies, card_personality),
        "card_interests": card_interests,
        "card_hobbies": card_hobbies,
        "card_personality": card_personality,
        "card_bedroom": card_bedroom,
        "card_gender": " · ".join(gender_labels(profile.gender_identities)),
        "card_looking": looking,
        "photo_index": index,
        "photo_count": filled,
        "photo_url": f"{photo_base}/{index}" if filled else "",
        "heif_url": f"{photo_base}/{index}/heif" if filled else "",
        "prev_photo": (index - 1) % filled if filled else 0,
        "next_photo": (index + 1) % filled if filled else 0,
        "monogram": (shown_name[:1] or "?"),
    }


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

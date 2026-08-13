from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from html.parser import HTMLParser
from unittest.mock import patch
from urllib.parse import unquote_plus

import httpx
import pytest

from swipe_dating.web.app import BrowserSessionStore, _safe_next_path, create_web_app

NOW = 1_753_185_600_000


class RenderedHtml(HTMLParser):
    _VOID_ELEMENTS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "source",
        }
    )

    def __init__(self, source: str) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.primary_navigation_links: list[dict[str, str | None]] = []
        self.text_by_id: dict[str, list[str]] = {}
        self._inside_primary_navigation = False
        self._open_elements: list[tuple[str, str | None]] = []
        self.feed(source)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        element_id = attributes.get("id")
        if element_id is not None:
            self.text_by_id[element_id] = []
        if tag not in self._VOID_ELEMENTS:
            self._open_elements.append((tag, element_id))
        if tag == "nav" and attributes.get("aria-label") == "Primary navigation":
            self._inside_primary_navigation = True
        elif tag == "a" and self._inside_primary_navigation:
            self.primary_navigation_links.append(attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav" and self._inside_primary_navigation:
            self._inside_primary_navigation = False
        for index in range(len(self._open_elements) - 1, -1, -1):
            if self._open_elements[index][0] == tag:
                del self._open_elements[index:]
                break

    def handle_data(self, data: str) -> None:
        for _tag, element_id in self._open_elements:
            if element_id is not None:
                self.text_by_id[element_id].append(data)

    def element_with(
        self,
        tag: str,
        attribute: str,
        value: str,
    ) -> dict[str, str | None] | None:
        return next(
            (
                attributes
                for element_tag, attributes in self.elements
                if tag in ("*", element_tag) and attributes.get(attribute) == value
            ),
            None,
        )

    def elements_with_class(
        self,
        tag: str,
        class_name: str,
    ) -> list[dict[str, str | None]]:
        return [
            attributes
            for element_tag, attributes in self.elements
            if tag in ("*", element_tag) and class_name in (attributes.get("class") or "").split()
        ]

    def radio(self, name: str, value: str) -> dict[str, str | None]:
        return next(
            attributes
            for tag, attributes in self.elements
            if tag == "input"
            and attributes.get("name") == name
            and attributes.get("value") == value
        )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def web_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_web_app(clock=lambda: NOW, today="2026-07-22"))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        yield client


async def enter_app(client: httpx.AsyncClient) -> None:
    await client.get("/")
    accepted = await client.post("/age-gate", data={"birth_date": "2000-01-01"})
    assert accepted.status_code == 303


async def create_alex_match(client: httpx.AsyncClient) -> str:
    await enter_app(client)
    matched = await client.post("/discover/interest", data={"candidate_id": "p1"})
    assert matched.status_code == 303
    assert matched.headers["location"].startswith("/matches")
    return "match:p1"


def test_live_browser_session_store_uses_runtime_calendar_date() -> None:
    with patch("swipe_dating.web.app.date") as current_date:
        current_date.today.return_value = date(2030, 1, 2)
        _token, session = BrowserSessionStore().create()
    assert session.today == "2030-01-02"


@pytest.mark.anyio
async def test_health_and_age_gate_are_accessible_and_fail_closed(
    web_client: httpx.AsyncClient,
) -> None:
    health = await web_client.get("/healthz")
    assert health.json() == {
        "status": "ok",
        "mode": "python-web-synthetic-only",
    }

    gate = await web_client.get("/")
    document = RenderedHtml(gate.text)
    month = document.element_with("input", "name", "birth_month")
    day = document.element_with("input", "name", "birth_day")
    year = document.element_with("input", "name", "birth_year")
    assert document.element_with("a", "href", "#main-content") is not None
    assert document.element_with("main", "id", "main-content") is not None
    assert document.element_with("*", "id", "birth-month-label") is not None
    assert document.element_with("*", "id", "birth-day-label") is not None
    assert document.element_with("*", "id", "birth-year-label") is not None
    assert month is not None
    assert day is not None
    assert year is not None
    assert month.get("type") == "radio"
    assert day.get("type") == "radio"
    assert year.get("type") == "radio"
    assert month.get("autocomplete") == "bday-month"
    assert day.get("autocomplete") == "bday-day"
    assert year.get("autocomplete") == "bday-year"
    assert "checked" not in month
    assert "checked" not in day
    assert "checked" not in year
    assert document.element_with("input", "id", "birth_date") is None
    assert "Adults 18+ only" in gate.text
    assert "LOCAL RESEARCH BUILD" in gate.text
    assert "MM-DD-YYYY" in gate.text
    assert "No real profiles" in gate.text
    assert "No real messages" in gate.text
    assert "No location collection" in gate.text

    empty = await web_client.post("/age-gate", data={"birth_date": ""})
    assert empty.status_code in (400, 422)
    blocked = await web_client.get("/discover")
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/"

    invalid = await web_client.post("/age-gate", data={"birth_date": "not-a-date"})
    assert invalid.status_code == 400
    assert "Choose a real calendar date as month, day, and year." in invalid.text

    rejected = await web_client.post("/age-gate", data={"birth_date": "2010-01-01"})
    rejected_document = RenderedHtml(rejected.text)
    assert rejected.status_code == 400
    assert "checked" in rejected_document.radio("birth_month", "01")
    assert "checked" in rejected_document.radio("birth_day", "01")
    assert "checked" in rejected_document.radio("birth_year", "2010")


@pytest.mark.anyio
async def test_age_gate_accepts_mm_dd_yyyy_wheels_and_rejects_impossible_dates(
    web_client: httpx.AsyncClient,
) -> None:
    impossible = await web_client.post(
        "/age-gate",
        data={"birth_month": "02", "birth_day": "31", "birth_year": "2000"},
    )
    assert impossible.status_code == 400
    assert "Choose a real calendar date as month, day, and year." in impossible.text

    wheeled = await web_client.post(
        "/age-gate",
        data={"birth_month": "01", "birth_day": "01", "birth_year": "2000"},
    )
    assert wheeled.status_code == 303
    assert wheeled.headers["location"] == "/discover"


@pytest.mark.anyio
async def test_primary_navigation_is_exactly_swipe_and_matches(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    navigation_paths = ("/discover", "/matches")
    for current_path in navigation_paths:
        page = await web_client.get(current_path)
        document = RenderedHtml(page.text)
        links = {link.get("href"): link for link in document.primary_navigation_links}
        assert set(links) == set(navigation_paths)
        assert links[current_path].get("aria-current") == "page"
        assert all(
            "aria-current" not in link for path, link in links.items() if path != current_path
        )


@pytest.mark.anyio
async def test_swipe_card_is_focused_accessible_and_has_nested_controls(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    discover = await web_client.get("/discover")
    document = RenderedHtml(discover.text)
    profile_visuals = document.elements_with_class("*", "profile-visual")
    assert discover.status_code == 200
    assert len(profile_visuals) == 1
    assert profile_visuals[0].get("role") == "img"
    assert "synthetic profile" in (profile_visuals[0].get("aria-label") or "").lower()
    assert "Alex" in (profile_visuals[0].get("aria-label") or "")
    assert "% aligned" in discover.text
    assert "Open profile" in discover.text
    assert "Open filters" in discover.text
    assert "Report Alex" in discover.text
    assert "Nearby mode stays off" in discover.text

    passed = await web_client.post("/discover/pass", data={"candidate_id": "p1"})
    assert passed.status_code == 303
    after_pass = await web_client.get("/discover")
    assert "Alex" not in after_pass.text
    undone = await web_client.post("/discover/undo")
    assert undone.status_code == 303
    restored = await web_client.get("/discover")
    assert "Alex" in restored.text


@pytest.mark.anyio
async def test_profile_and_filters_are_nested_not_primary_tabs(  # noqa: PLR0915
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    profile = await web_client.get("/profile")
    profile_document = RenderedHtml(profile.text)
    assert profile.status_code == 200
    assert not profile_document.primary_navigation_links
    saved = await web_client.post(
        "/profile",
        data={
            "display_name": "Taylor",
            "pronouns": "they/them",
            "about": "Climbing and films.",
            "gender_identities": ["woman"],
            "show_genders": ["man", "woman", "non_binary"],
            "lifestyle_tags": ["coffee", "movie_night"],
            "hobby_tags": ["climbing"],
            "personality_tags": ["calm", "intense"],
        },
    )
    assert saved.status_code == 303
    refreshed = await web_client.get("/profile")
    assert "Taylor" in refreshed.text
    assert "Climbing and films." in refreshed.text
    assert "they/them" in refreshed.text
    assert "Woman" in refreshed.text
    assert "Agender" in refreshed.text
    assert "Genderfluid" in refreshed.text
    assert "Two-Spirit" in refreshed.text
    assert "Show me" in refreshed.text
    assert "Sexual preference" in refreshed.text
    assert "Hobbies" in refreshed.text
    assert "Personality" in refreshed.text
    assert "In the bedroom" in refreshed.text
    assert "Your current top 5 favorites" in refreshed.text
    assert "Show on my card" in refreshed.text
    assert "Always shown on your card" in refreshed.text
    assert "Always private" in refreshed.text
    assert "Calm" in refreshed.text
    assert "Intense" in refreshed.text
    assert "BDSM" in refreshed.text
    assert "Vanilla" in refreshed.text
    assert "Add photos" in refreshed.text
    assert "multiple" in refreshed.text
    assert "Move up" not in refreshed.text
    assert refreshed.text.count('name="photo"') == 1
    assert "Preview how you appear" in refreshed.text
    preview = await web_client.get("/profile/preview")
    assert preview.status_code == 200
    assert "Taylor" in preview.text
    assert "Climbing and films." in preview.text
    assert "Woman" in preview.text
    assert "Calm" in preview.text
    assert "Show me" not in preview.text
    assert "Sexual preference" not in preview.text
    assert "BDSM" not in preview.text
    assert 'name="photo_id"' not in refreshed.text
    document = RenderedHtml(refreshed.text)
    assert "checked" in document.radio("gender_identities", "woman")
    assert "checked" in document.radio("show_genders", "man")

    filters = await web_client.get("/filters")
    filters_document = RenderedHtml(filters.text)
    assert filters.status_code == 200
    assert not filters_document.primary_navigation_links
    assert "Ranking stays curated" in filters.text
    invalid = await web_client.post(
        "/filters",
        data={
            "immediate_intent": "unsupported",
            "relational_openness": "open_to_more",
            "required_boundaries": ["public_first_meet"],
        },
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    applied = await web_client.post(
        "/filters",
        data={
            "immediate_intent": "casual_dating",
            "relational_openness": "open_to_more",
            "required_boundaries": [
                "condoms_required",
                "public_first_meet",
                "no_drugs",
            ],
        },
    )
    assert applied.status_code == 303
    assert applied.headers["location"].startswith("/discover")
    assert "Agender" in filters.text
    gendered = await web_client.post(
        "/filters",
        data={
            "immediate_intent": "casual_dating",
            "relational_openness": "open_to_more",
            "required_boundaries": [
                "condoms_required",
                "public_first_meet",
                "no_drugs",
            ],
            "show_genders": ["man"],
        },
    )
    assert gendered.status_code == 303
    deck = await web_client.get("/discover")
    assert "Jordan" in deck.text
    assert "Alex" not in deck.text


@pytest.mark.anyio
async def test_profile_card_visibility_hides_optional_fields_not_gender(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    hidden = await web_client.post(
        "/profile",
        data={
            "display_name": "Taylor",
            "pronouns": "they/them",
            "about": "Climbing and films.",
            "gender_identities": ["woman"],
            "show_genders": ["man"],
            "lifestyle_tags": ["coffee"],
            "hobby_tags": ["climbing"],
            "personality_tags": ["calm"],
            "bedroom_tags": ["bdsm", "vanilla"],
            "card_visibility_present": "1",
            "show_on_card": ["photos", "interests"],
        },
    )
    assert hidden.status_code == 303
    preview = await web_client.get("/profile/preview")
    assert preview.status_code == 200
    assert "Someone" in preview.text
    assert "Taylor" not in preview.text
    assert "Climbing and films." not in preview.text
    assert "they/them" not in preview.text
    assert "Woman" in preview.text
    assert "Coffee" in preview.text
    assert "Climbing" not in preview.text
    assert "Calm" not in preview.text
    assert "BDSM" not in preview.text
    assert "Vanilla" not in preview.text
    assert "Show me" not in preview.text
    assert "Sexual preference" not in preview.text
    revealed = await web_client.post(
        "/profile",
        data={
            "display_name": "Taylor",
            "pronouns": "they/them",
            "about": "Climbing and films.",
            "gender_identities": ["woman"],
            "show_genders": ["man"],
            "lifestyle_tags": ["coffee"],
            "hobby_tags": ["climbing"],
            "personality_tags": ["calm"],
            "bedroom_tags": ["bdsm", "vanilla"],
            "card_visibility_present": "1",
            "show_on_card": [
                "photos",
                "display_name",
                "age",
                "pronouns",
                "about",
                "looking_for",
                "interests",
                "hobbies",
                "personality",
                "bedroom",
            ],
        },
    )
    assert revealed.status_code == 303
    shown = await web_client.get("/profile/preview")
    assert "Taylor" in shown.text
    assert "Climbing and films." in shown.text
    assert "they/them" in shown.text
    assert "Woman" in shown.text
    assert "BDSM" in shown.text
    assert "Vanilla" in shown.text
    assert "Show me" not in shown.text


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.anyio
async def test_profile_photos_upload_serve_and_remove(  # noqa: PLR0915
    web_client: httpx.AsyncClient,
) -> None:
    missing = await web_client.get("/profile/photos/0")
    assert missing.status_code == 303
    await enter_app(web_client)
    empty = await web_client.get("/profile/photos/0")
    assert empty.status_code == 404
    uploaded = await web_client.post(
        "/profile/photos",
        data={"slot": "0"},
        files={"photo": ("me.png", PNG_1X1, "image/png")},
    )
    assert uploaded.status_code == 303
    assert "notice=" in uploaded.headers["location"]
    image = await web_client.get("/profile/photos/0")
    assert image.status_code == 200
    assert image.content[4:12] == b"ftypavif"
    assert image.headers["content-type"].startswith("image/avif")
    assert image.headers["cache-control"] == "private, no-store"
    assert image.headers["x-content-type-options"] == "nosniff"
    heif = await web_client.get("/profile/photos/0/heif")
    assert heif.status_code == 200
    assert heif.content[4:8] == b"ftyp"
    assert heif.headers["content-type"].startswith("image/heic")
    profile = await web_client.get("/profile")
    assert "/profile/photos/0" in profile.text
    assert "/profile/photos/0/heif" in profile.text
    assert "Remove photo 1" in profile.text
    assert "Add photo" in profile.text
    assert "1080×2400" in profile.text
    assert profile.text.count('name="photo"') == 1
    assert "multiple" in profile.text
    assert "Move up" not in profile.text
    assert "Drag" in profile.text
    second = await web_client.post(
        "/profile/photos",
        files=[
            ("photo", ("me2.png", PNG_1X1, "image/png")),
        ],
    )
    assert second.status_code == 303
    assert "notice=" in second.headers["location"]
    two = await web_client.get("/profile/photos/1")
    assert two.status_code == 200
    moved = await web_client.post(
        "/profile/photos/reorder",
        data={"order": ["1", "0"]},
    )
    assert moved.status_code == 303
    assert "notice=" in moved.headers["location"]
    preview = await web_client.get("/profile/preview")
    assert preview.status_code == 200
    assert "How you appear" in preview.text
    assert "This is the card other people see" in preview.text
    shared = await web_client.post("/profile/share")
    assert shared.status_code == 303
    profile_shared = await web_client.get("/profile")
    assert 'id="share-link"' in profile_shared.text
    rejected = await web_client.post(
        "/profile/photos",
        data={"slot": "1"},
        files={"photo": ("me.txt", b"not-an-image", "image/png")},
    )
    assert rejected.status_code == 303
    assert "error=" in rejected.headers["location"]
    invalid_slot = await web_client.post(
        "/profile/photos",
        data={"slot": "9"},
        files={"photo": ("me.png", PNG_1X1, "image/png")},
    )
    assert invalid_slot.status_code == 303
    assert "error=" in invalid_slot.headers["location"]
    removed = await web_client.post("/profile/photos/0/remove")
    assert removed.status_code == 303
    packed = await web_client.get("/profile/photos/0")
    assert packed.status_code == 200
    removed_last = await web_client.post("/profile/photos/0/remove")
    assert removed_last.status_code == 303
    gone = await web_client.get("/profile/photos/0")
    assert gone.status_code == 404


@pytest.mark.anyio
async def test_profile_photo_picker_keeps_only_the_six_slot_limit(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    uploaded = await web_client.post(
        "/profile/photos",
        files=[("photo", (f"me{index}.png", PNG_1X1, "image/png")) for index in range(8)],
    )
    assert uploaded.status_code == 303
    location = unquote_plus(uploaded.headers["location"])
    assert "6 photos added" in location
    assert "Extras were skipped because 6 is the limit." in location
    sixth = await web_client.get("/profile/photos/5")
    assert sixth.status_code == 200
    overflow = await web_client.get("/profile/photos/6")
    assert overflow.status_code == 404
    profile = await web_client.get("/profile")
    assert 'id="photo-picker"' not in profile.text
    assert "Move up" not in profile.text


@pytest.mark.anyio
async def test_profile_share_link_opens_for_another_adult_session() -> None:
    store = BrowserSessionStore(clock=lambda: NOW, today="2026-07-22")
    app = create_web_app(clock=lambda: NOW, today="2026-07-22", session_store=store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as owner:
        await enter_app(owner)
        await owner.post(
            "/profile",
            data={"display_name": "Taylor", "about": "Climbing and films.", "pronouns": ""},
        )
        await owner.post(
            "/profile/photos",
            files={"photo": ("me.png", PNG_1X1, "image/png")},
        )
        await owner.post("/profile/share")
        page = await owner.get("/profile")
        share_input = RenderedHtml(page.text).element_with("input", "id", "share-link")
        assert share_input is not None
        share_url = share_input.get("value") or ""
        share_path = "/" + share_url.split("/", 3)[-1]
        assert share_path.startswith("/p/")
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as guest:
        blocked = await guest.get(share_path)
        assert blocked.status_code == 303
        assert "next=" in blocked.headers["location"]
        await enter_app(guest)
        shared = await guest.get(share_path)
        assert shared.status_code == 200
        assert "Taylor" in shared.text
        assert "Climbing and films." in shared.text
        assert "Shared profile card" in shared.text


def test_share_next_path_only_allows_local_profile_links() -> None:
    assert _safe_next_path(None) is None
    assert _safe_next_path("/discover") is None
    assert _safe_next_path("/p/abc://evil") is None
    assert _safe_next_path("/p/abc//nested") is None
    assert _safe_next_path("/p/has space") is None
    assert _safe_next_path("/p/ok?photo=1") == "/p/ok"


def test_stale_share_token_is_forgotten() -> None:
    store = BrowserSessionStore(clock=lambda: NOW, today="2026-07-22")
    token, session = store.create()
    session.accept_adult_gate("2000-01-01")
    share = store.publish_share(token, session)
    assert store.get_by_share(share) is session
    session.reset_saved_profile()
    assert store.get_by_share(share) is None
    assert store.get_by_share("missing") is None


@pytest.mark.anyio
async def test_match_chat_meetup_and_unmatch_flow(web_client: httpx.AsyncClient) -> None:
    match_id = await create_alex_match(web_client)
    matches = await web_client.get("/matches")
    assert "People who chose you too" in matches.text
    assert "Alex" in matches.text
    assert "Matched. Say hi when you want to." in matches.text

    chat = await web_client.get(f"/matches/{match_id}")
    chat_document = RenderedHtml(chat.text)
    assert chat.status_code == 200
    assert not chat_document.primary_navigation_links
    assert "No automatic message was sent" in chat.text
    assert "Plan a meetup" in chat.text
    assert "0 / 20" in chat.text

    blank = await web_client.post(
        f"/matches/{match_id}/message",
        data={"text": "   "},
    )
    assert blank.status_code == 303
    assert "error=" in blank.headers["location"]

    sent = await web_client.post(
        f"/matches/{match_id}/message",
        data={"text": "Coffee this week?"},
    )
    assert sent.status_code == 303
    thread = await web_client.get(f"/matches/{match_id}")
    assert "Coffee this week?" in thread.text
    assert "1 / 20" in thread.text

    bad_meetup = await web_client.post(
        f"/matches/{match_id}/meetup",
        data={"suggestion_id": "private_address"},
    )
    assert "error=" in bad_meetup.headers["location"]

    proposed = await web_client.post(
        f"/matches/{match_id}/meetup",
        data={"suggestion_id": "coffee_public"},
    )
    assert proposed.status_code == 303
    meetup_chat = await web_client.get(f"/matches/{match_id}")
    assert "Would you like to meet for coffee in a public place?" in meetup_chat.text
    assert "No+location+was+shared" in proposed.headers["location"]

    unmatched = await web_client.post(f"/matches/{match_id}/unmatch")
    assert unmatched.status_code == 303
    remaining = await web_client.get("/matches")
    assert "No matches yet" in remaining.text


@pytest.mark.anyio
async def test_web_message_limit_allows_one_extension(web_client: httpx.AsyncClient) -> None:
    match_id = await create_alex_match(web_client)
    for index in range(20):
        sent = await web_client.post(
            f"/matches/{match_id}/message",
            data={"text": f"message {index}"},
        )
        assert sent.status_code == 303

    at_limit = await web_client.get(f"/matches/{match_id}")
    assert "20 / 20" in at_limit.text
    assert "Simulate mutual extension" in at_limit.text

    blocked = await web_client.post(
        f"/matches/{match_id}/message",
        data={"text": "too many"},
    )
    assert "error=" in blocked.headers["location"]

    extended = await web_client.post(f"/matches/{match_id}/extend")
    assert extended.status_code == 303
    after_extension = await web_client.get(f"/matches/{match_id}")
    assert "20 / 40" in after_extension.text
    repeated = await web_client.post(f"/matches/{match_id}/extend")
    assert "error=" in repeated.headers["location"]


@pytest.mark.anyio
async def test_block_purges_visible_content_and_suppresses_rediscovery(
    web_client: httpx.AsyncClient,
) -> None:
    match_id = await create_alex_match(web_client)
    await web_client.post(
        f"/matches/{match_id}/message",
        data={"text": "This will be purged."},
    )
    blocked = await web_client.post(f"/matches/{match_id}/block")
    assert blocked.status_code == 303
    matches = await web_client.get("/matches")
    assert "This will be purged." not in matches.text
    discover = await web_client.get("/discover")
    assert "Alex" not in discover.text


@pytest.mark.anyio
async def test_report_seven_vote_contain_appeal_restore_and_match(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    bad_reason = await web_client.post(
        "/discover/report",
        data={"candidate_id": "p1", "reason": "not-real", "evidence_note": ""},
    )
    assert "error=" in bad_reason.headers["location"]

    reported = await web_client.post(
        "/discover/report",
        data={
            "candidate_id": "p1",
            "reason": "automation_pattern",
            "evidence_note": "Repeated pattern in the synthetic fixture.",
        },
    )
    assert reported.status_code == 303
    assert reported.headers["location"].startswith("/community")
    community = await web_client.get("/community")
    assert "Alex" in community.text
    assert "0 / 7 trusted votes" in community.text
    assert "reviewer-1" in community.text
    assert "Repeated pattern" in community.text

    invalid_vote = await web_client.post(
        "/community/bot-case-1/vote",
        data={"reviewer_id": "reviewer-1", "choice": "not-real"},
    )
    assert "error=" in invalid_vote.headers["location"]

    choices = (
        "suspicious",
        "suspicious",
        "likely_human",
        "suspicious",
        "suspicious",
        "likely_human",
        "suspicious",
    )
    for index, choice in enumerate(choices, start=1):
        voted = await web_client.post(
            "/community/bot-case-1/vote",
            data={"reviewer_id": f"reviewer-{index}", "choice": choice},
        )
        assert voted.status_code == 303

    contained = await web_client.get("/community")
    assert "Temporarily buried" in contained.text
    assert "7 / 7 trusted votes" in contained.text
    hidden = await web_client.get("/discover")
    assert "Alex" not in hidden.text

    appealed = await web_client.post("/community/bot-case-1/appeal")
    assert appealed.status_code == 303
    adjudicated = await web_client.post("/community/bot-case-1/adjudicate")
    assert adjudicated.status_code == 303
    adjudicated_page = await web_client.get("/community")
    assert "Synthetic human restored" in adjudicated_page.text

    restored = await web_client.get("/discover")
    assert "Alex" in restored.text
    matched = await web_client.post("/discover/interest", data={"candidate_id": "p1"})
    assert matched.status_code == 303
    matches = await web_client.get("/matches")
    assert "Alex" in matches.text


@pytest.mark.anyio
async def test_automated_bot_containment_and_final_bot_adjudication(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    reported = await web_client.post(
        "/discover/report",
        data={"candidate_id": "p2", "reason": "spam_links", "evidence_note": ""},
    )
    assert reported.status_code == 303
    community = await web_client.get("/community")
    assert "Temporarily buried" in community.text
    appealed = await web_client.post("/community/bot-case-1/appeal")
    assert appealed.status_code == 303
    final = await web_client.post("/community/bot-case-1/adjudicate")
    assert final.status_code == 303
    page = await web_client.get("/community")
    assert "Synthetic bot confirmed" in page.text


@pytest.mark.anyio
async def test_conversation_report_reaches_private_review(
    web_client: httpx.AsyncClient,
) -> None:
    match_id = await create_alex_match(web_client)
    bad = await web_client.post(
        f"/matches/{match_id}/report",
        data={"reason": "not-real", "evidence_note": ""},
    )
    assert "error=" in bad.headers["location"]
    reported = await web_client.post(
        f"/matches/{match_id}/report",
        data={
            "reason": "impersonation",
            "evidence_note": "Synthetic conversation concern.",
        },
    )
    assert reported.status_code == 303
    assert reported.headers["location"].startswith("/community")
    review = await web_client.get("/community")
    assert "impersonation" in review.text
    assert "Synthetic conversation concern" in review.text


@pytest.mark.anyio
async def test_unknown_nested_resources_redirect_with_safe_errors(
    web_client: httpx.AsyncClient,
) -> None:
    await enter_app(web_client)
    missing_chat = await web_client.get("/matches/match:none")
    assert missing_chat.status_code == 303
    assert missing_chat.headers["location"].startswith("/matches?error=")
    early_appeal = await web_client.post("/community/not-real/appeal")
    assert early_appeal.status_code == 303
    assert "error=" in early_appeal.headers["location"]
    early_adjudication = await web_client.post("/community/not-real/adjudicate")
    assert early_adjudication.status_code == 303
    assert "error=" in early_adjudication.headers["location"]


@pytest.mark.anyio
async def test_browser_sessions_are_isolated(web_client: httpx.AsyncClient) -> None:
    _ = web_client
    app = create_web_app(clock=lambda: NOW, today="2026-07-22")
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as first,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            follow_redirects=False,
        ) as second,
    ):
        await enter_app(first)
        await first.post("/discover/pass", data={"candidate_id": "p1"})
        first_queue = await first.get("/discover")
        assert "Alex" not in first_queue.text

        blocked = await second.get("/discover")
        assert blocked.status_code == 303
        await enter_app(second)
        second_queue = await second.get("/discover")
        assert "Alex" in second_queue.text

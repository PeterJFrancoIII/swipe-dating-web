from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from html.parser import HTMLParser
from unittest.mock import patch

import httpx
import pytest

from swipe_dating.web.app import BrowserSessionStore, create_web_app

NOW = 1_753_185_600_000


class RenderedHtml(HTMLParser):
    _VOID_ELEMENTS = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
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

    def text_for_id(self, element_id: str) -> str:
        return " ".join("".join(self.text_by_id.get(element_id, [])).split())


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_live_browser_session_store_uses_the_runtime_calendar_date() -> None:
    with patch("swipe_dating.web.app.date") as current_date:
        current_date.today.return_value = date(2030, 1, 2)
        _token, session = BrowserSessionStore().create()

    assert session.today == "2030-01-02"


@pytest.fixture
async def web_client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_web_app(clock=lambda: NOW, today="2026-07-22"))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        yield client


@pytest.mark.anyio
async def test_age_gate_has_a_skip_link_to_the_stable_main_landmark(
    web_client: httpx.AsyncClient,
) -> None:
    gate = await web_client.get("/")
    document = RenderedHtml(gate.text)

    assert document.element_with("a", "href", "#main-content") is not None
    assert document.element_with("main", "id", "main-content") is not None


@pytest.mark.anyio
async def test_primary_navigation_identifies_only_the_current_page(
    web_client: httpx.AsyncClient,
) -> None:
    await web_client.get("/")
    await web_client.post("/age-gate", data={"birth_date": "2000-01-01"})

    navigation_paths = ("/discover", "/matches")
    for current_path in navigation_paths:
        page = await web_client.get(current_path)
        document = RenderedHtml(page.text)
        links = {link.get("href"): link for link in document.primary_navigation_links}

        assert set(links) == set(navigation_paths)
        assert "Swipe" in page.text
        assert "Community review" not in "".join(
            link.get("href") or "" for link in document.primary_navigation_links
        )
        assert links[current_path].get("aria-current") == "page"
        assert all(
            "aria-current" not in link for path, link in links.items() if path != current_path
        )


@pytest.mark.anyio
async def test_birth_date_uses_the_native_control_without_losing_its_contract(
    web_client: httpx.AsyncClient,
) -> None:
    gate = await web_client.get("/")
    document = RenderedHtml(gate.text)
    birth_date = document.element_with("input", "id", "birth_date")

    assert document.element_with("label", "for", "birth_date") is not None
    assert birth_date is not None
    assert birth_date.get("name") == "birth_date"
    assert birth_date.get("autocomplete") == "bday"
    assert birth_date.get("type") == "date"


@pytest.mark.anyio
async def test_age_gate_initially_renders_without_an_eligible_birth_date(
    web_client: httpx.AsyncClient,
) -> None:
    gate = await web_client.get("/")
    document = RenderedHtml(gate.text)
    birth_date = document.element_with("input", "id", "birth_date")

    assert birth_date is not None
    assert birth_date.get("value") in (None, "")


@pytest.mark.anyio
async def test_empty_birth_date_cannot_proceed_past_the_gate(
    web_client: httpx.AsyncClient,
) -> None:
    await web_client.get("/")

    empty = await web_client.post("/age-gate", data={"birth_date": ""})
    assert empty.status_code in (400, 422)
    assert empty.headers.get("location") is None

    blocked = await web_client.get("/discover")
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/"


@pytest.mark.anyio
async def test_age_gate_preserves_a_rejected_well_formed_birth_date(
    web_client: httpx.AsyncClient,
) -> None:
    rejected = await web_client.post("/age-gate", data={"birth_date": "2010-01-01"})
    document = RenderedHtml(rejected.text)
    birth_date = document.element_with("input", "id", "birth_date")

    assert rejected.status_code == 400
    assert birth_date is not None
    assert birth_date.get("value") == "2010-01-01"


@pytest.mark.anyio
async def test_birth_date_control_is_linked_to_its_existing_format_help(
    web_client: httpx.AsyncClient,
) -> None:
    gate = await web_client.get("/")
    document = RenderedHtml(gate.text)
    birth_date = document.element_with("input", "id", "birth_date")

    assert "Use YYYY-MM-DD" in gate.text
    assert birth_date is not None
    helper_ids = (birth_date.get("aria-describedby") or "").split()
    assert helper_ids
    assert all(document.element_with("*", "id", helper_id) is not None for helper_id in helper_ids)
    linked_help = " ".join(document.text_for_id(helper_id) for helper_id in helper_ids)
    assert "Use YYYY-MM-DD" in linked_help
    assert "browser may display the date in your local format" in linked_help.lower()


@pytest.mark.anyio
async def test_rendered_pages_keep_truthful_synthetic_and_local_boundaries_visible(
    web_client: httpx.AsyncClient,
) -> None:
    gate = await web_client.get("/")
    assert "LOCAL RESEARCH BUILD" in gate.text
    assert "SYNTHETIC ONLY" in gate.text
    assert "No real profiles" in gate.text
    assert "No real messages" in gate.text
    assert "No location collection" in gate.text

    await web_client.post("/age-gate", data={"birth_date": "2000-01-01"})
    discover = await web_client.get("/discover")
    assert "SYNTHETIC ONLY" in discover.text
    assert "Local synthetic research build" in discover.text
    assert "No real users" in discover.text


@pytest.mark.anyio
async def test_discovery_profile_visual_is_a_named_image(
    web_client: httpx.AsyncClient,
) -> None:
    await web_client.get("/")
    await web_client.post("/age-gate", data={"birth_date": "2000-01-01"})

    discover = await web_client.get("/discover")
    document = RenderedHtml(discover.text)
    profile_visuals = document.elements_with_class("*", "profile-visual")

    assert len(profile_visuals) == 1
    assert profile_visuals[0].get("role") == "img"
    accessible_name = profile_visuals[0].get("aria-label") or ""
    assert "synthetic profile" in accessible_name.lower()
    assert "Alex" in accessible_name


@pytest.mark.anyio
async def test_age_gate_is_clear_fail_closed_and_session_scoped(
    web_client: httpx.AsyncClient,
) -> None:
    gate = await web_client.get("/")
    assert gate.status_code == 200
    assert "Adults 18+ only" in gate.text
    assert "YYYY-MM-DD" in gate.text

    invalid = await web_client.post("/age-gate", data={"birth_date": "01/01/2000"})
    assert invalid.status_code == 400
    assert "Use YYYY-MM-DD" in invalid.text

    accepted = await web_client.post("/age-gate", data={"birth_date": "2000-01-01"})
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/discover"

    discover = await web_client.get("/discover")
    assert discover.status_code == 200
    assert "Alex" in discover.text
    assert "SYNTHETIC ONLY" in discover.text


@pytest.mark.anyio
async def test_report_vote_contain_appeal_restore_and_match_web_flow(
    web_client: httpx.AsyncClient,
) -> None:
    await web_client.get("/")
    await web_client.post("/age-gate", data={"birth_date": "2000-01-01"})

    reported = await web_client.post(
        "/discover/report",
        data={"candidate_id": "p1", "reason": "automation_pattern"},
    )
    assert reported.status_code == 303
    assert reported.headers["location"].startswith("/community")

    community = await web_client.get("/community")
    community_document = RenderedHtml(community.text)
    community_avatars = community_document.elements_with_class("span", "mini-avatar")
    assert community.status_code == 200
    assert "Alex" in community.text
    assert "0 / 3 trusted votes" in community.text
    assert "reviewer-ava" in community.text
    assert community_avatars
    assert all(avatar.get("aria-hidden") == "true" for avatar in community_avatars)

    for reviewer_id, choice in (
        ("reviewer-ava", "suspicious"),
        ("reviewer-noah", "likely_human"),
        ("reviewer-sam", "suspicious"),
    ):
        voted = await web_client.post(
            "/community/bot-case-1/vote",
            data={"reviewer_id": reviewer_id, "choice": choice},
        )
        assert voted.status_code == 303

    contained = await web_client.get("/community")
    assert "Temporarily buried" in contained.text
    assert "3 / 3 trusted votes" in contained.text
    discover = await web_client.get("/discover")
    assert "Alex" not in discover.text

    appealed = await web_client.post("/community/bot-case-1/appeal")
    assert appealed.status_code == 303
    adjudicated = await web_client.post("/community/bot-case-1/adjudicate")
    assert adjudicated.status_code == 303

    adjudicated_page = await web_client.get("/community")
    adjudicated_document = RenderedHtml(adjudicated_page.text)
    assert "Synthetic human restored" in adjudicated_page.text
    assert not adjudicated_document.elements_with_class("div", "case-actions")

    restored = await web_client.get("/discover")
    assert "Alex" in restored.text
    matched = await web_client.post(
        "/discover/interest",
        data={"candidate_id": "p1"},
    )
    assert matched.status_code == 303
    assert matched.headers["location"].startswith("/matches")
    matches = await web_client.get("/matches")
    matches_document = RenderedHtml(matches.text)
    match_avatars = matches_document.elements_with_class("span", "mini-avatar")
    assert "It’s a match" in matches.text
    assert "Alex" in matches.text
    assert match_avatars
    assert all(avatar.get("aria-hidden") == "true" for avatar in match_avatars)


@pytest.mark.anyio
async def test_browser_sessions_are_isolated_and_pass_advances_only_one_queue() -> None:
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
        await first.get("/")
        await first.post("/age-gate", data={"birth_date": "2000-01-01"})
        passed = await first.post("/discover/pass", data={"candidate_id": "p1"})
        assert passed.status_code == 303
        first_queue = await first.get("/discover")
        assert "Alex" not in first_queue.text

        blocked = await second.get("/discover")
        assert blocked.status_code == 303
        assert blocked.headers["location"] == "/"
        await second.get("/")
        await second.post("/age-gate", data={"birth_date": "2000-01-01"})
        second_queue = await second.get("/discover")
        assert "Alex" in second_queue.text

"""Headless browser acceptance flow for the local synthetic web app."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

from swipe_dating.web.run import normalize_loopback_origin

DEFAULT_BASE_URL = "http://127.0.0.1:8081"
DEFAULT_SCREENSHOT_DIR = Path(tempfile.gettempdir()) / "swipe-web"
SCREENSHOT_DIR = Path(os.environ.get("SWIPE_WEB_SCREENSHOTS", str(DEFAULT_SCREENSHOT_DIR)))
DESKTOP_VIEWPORT = {"width": 1440, "height": 1000}
RESPONSIVE_VIEWPORTS = (
    ("mobile", {"width": 390, "height": 844}),
    ("tablet", {"width": 768, "height": 1024}),
)


def review_as(page: Page, reviewer_id: str, button_name: str) -> None:
    row = page.locator(".reviewer-row", has_text=reviewer_id)
    row.get_by_role("button", name=button_name).click()
    page.wait_for_load_state("networkidle")


def verify_skip_link(page: Page) -> None:
    skip_link = page.get_by_role("link", name="Skip to main content", exact=True)
    if skip_link.count() != 1:
        raise AssertionError("expected exactly one skip link")

    page.keyboard.press("Tab")
    expect(skip_link).to_be_visible()
    box = skip_link.bounding_box()
    viewport = page.viewport_size
    if (
        box is None
        or viewport is None
        or box["width"] <= 0
        or box["height"] <= 0
        or box["x"] >= viewport["width"]
        or box["x"] + box["width"] <= 0
        or box["y"] >= viewport["height"]
        or box["y"] + box["height"] <= 0
    ):
        raise AssertionError(
            f"first Tab did not reveal the skip link in the viewport: box={box}, "
            f"viewport={viewport}"
        )
    if not skip_link.evaluate("(element) => element === document.activeElement"):
        raise AssertionError("first Tab did not focus the skip link")

    page.keyboard.press("Enter")
    page.wait_for_function("window.location.hash === '#main-content'")
    if page.locator(":target").get_attribute("id") != "main-content":
        raise AssertionError("skip link did not target the main content")


def verify_no_horizontal_overflow(page: Page, screen_name: str) -> None:
    dimensions = page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
        })"""
    )
    if dimensions["scrollWidth"] > dimensions["clientWidth"]:
        raise AssertionError(
            f"{screen_name} has horizontal overflow "
            f"({dimensions['scrollWidth']}px > {dimensions['clientWidth']}px)"
        )


def verify_lone_match_centered(page: Page) -> None:
    match_cards = page.locator(".match-card")
    expect(match_cards).to_have_count(1)
    match_box = match_cards.first.bounding_box()
    grid_box = page.locator(".match-grid").bounding_box()
    if match_box is None or grid_box is None:
        raise AssertionError(f"missing match geometry: match={match_box}, grid={grid_box}")

    match_center = match_box["x"] + match_box["width"] / 2
    grid_center = grid_box["x"] + grid_box["width"] / 2
    tolerance = 4
    if abs(match_center - grid_center) > tolerance:
        raise AssertionError(
            f"lone match is not centered: match_center={match_center}, "
            f"grid_center={grid_center}, tolerance={tolerance}"
        )


def verify_age_gate_disclosures(page: Page) -> None:
    expect(page.get_by_text("LOCAL RESEARCH BUILD", exact=True)).to_be_visible()
    expect(page.get_by_text("PYTHON · SYNTHETIC ONLY", exact=True)).to_be_visible()
    expect(page.get_by_text("No real profiles", exact=True)).to_be_visible()
    expect(page.get_by_text("No real messages", exact=True)).to_be_visible()
    expect(page.get_by_text("No location collection", exact=True)).to_be_visible()


def verify_discover_disclosures(page: Page) -> None:
    expect(page.get_by_text("PYTHON · SYNTHETIC ONLY", exact=True)).to_be_visible()
    expect(page.get_by_text("SYNTHETIC PROFILE", exact=True)).to_be_visible()
    expect(page.get_by_text("Local synthetic research build", exact=False)).to_be_visible()
    expect(page.get_by_text("No real users", exact=False)).to_be_visible()


def enter_synthetic_app(page: Page, base_url: str) -> None:
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="Adults 18+ only.").wait_for()
    verify_age_gate_disclosures(page)
    verify_no_horizontal_overflow(page, "age gate at 1440px")
    page.screenshot(path=SCREENSHOT_DIR / "age-gate.png", full_page=True)
    verify_skip_link(page)

    page.get_by_label("Birth date").fill("2000-01-01")
    page.get_by_role("button", name="Enter synthetic app").click()
    page.wait_for_url(f"{base_url}/discover")


def capture_discover_and_open_review(page: Page) -> None:
    page.get_by_role("heading", name="Alex").wait_for()
    verify_discover_disclosures(page)
    verify_no_horizontal_overflow(page, "discover at 1440px")
    page.screenshot(path=SCREENSHOT_DIR / "discover.png", full_page=True)

    page.get_by_role("button", name="Report suspected bot").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("0 / 3 trusted votes").wait_for()


def complete_community_review(page: Page, base_url: str) -> None:
    review_as(page, "reviewer-ava", "Bot-like")
    review_as(page, "reviewer-noah", "Likely human")
    review_as(page, "reviewer-sam", "Bot-like")
    page.get_by_text("Temporarily buried").wait_for()
    verify_no_horizontal_overflow(page, "contained community at 1440px")
    page.screenshot(path=SCREENSHOT_DIR / "contained.png", full_page=True)
    capture_responsive_community(
        page,
        base_url,
        screenshot_stem="community-contained",
        expected_text="Temporarily buried",
        expected_reviewer_rows=0,
        expected_actions=("Simulate subject appeal", "Run synthetic adjudication"),
    )

    page.get_by_role("button", name="Simulate subject appeal").click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Run synthetic adjudication").click()
    page.wait_for_load_state("networkidle")
    page.get_by_text("Synthetic human restored").wait_for()


def create_reciprocal_match(page: Page) -> None:
    page.get_by_role("link", name="Swipe").click()
    page.get_by_role("heading", name="Alex").wait_for()
    page.get_by_role("button", name="Like").click()
    page.wait_for_load_state("networkidle")
    page.locator(".match-card").get_by_text("a match", exact=False).wait_for()
    verify_no_horizontal_overflow(page, "match at 1440px")
    verify_lone_match_centered(page)
    page.screenshot(path=SCREENSHOT_DIR / "match.png", full_page=True)


def navigate_to_community(page: Page, base_url: str) -> None:
    response = page.goto(f"{base_url}/community")
    if response is None:
        raise AssertionError("community navigation returned no HTTP response")
    if not response.ok:
        raise AssertionError(f"community navigation returned HTTP {response.status}")

    page.wait_for_load_state("networkidle")
    expect(page).to_have_url(f"{base_url}/community")
    expect(
        page.get_by_role("heading", name="Trusted community review.", exact=True)
    ).to_be_visible()


def verify_community_state(
    page: Page,
    *,
    expected_text: str,
    expected_reviewer_rows: int | None = None,
    expected_actions: tuple[str, ...] = (),
) -> None:
    expect(page.get_by_text(expected_text, exact=True)).to_be_visible()
    if expected_reviewer_rows is not None:
        expect(page.locator(".reviewer-row")).to_have_count(expected_reviewer_rows)
    for action_name in expected_actions:
        expect(page.get_by_role("button", name=action_name, exact=True)).to_be_visible()


def capture_responsive_community(
    page: Page,
    base_url: str,
    *,
    screenshot_stem: str,
    expected_text: str,
    expected_reviewer_rows: int | None = None,
    expected_actions: tuple[str, ...] = (),
) -> None:
    for viewport_name, viewport in RESPONSIVE_VIEWPORTS:
        page.set_viewport_size(viewport)
        navigate_to_community(page, base_url)
        verify_community_state(
            page,
            expected_text=expected_text,
            expected_reviewer_rows=expected_reviewer_rows,
            expected_actions=expected_actions,
        )
        verify_no_horizontal_overflow(
            page,
            f"{screenshot_stem} community at {viewport['width']}px",
        )
        page.screenshot(
            path=SCREENSHOT_DIR / f"{screenshot_stem}-{viewport_name}.png",
            full_page=True,
        )

    page.set_viewport_size(DESKTOP_VIEWPORT)
    navigate_to_community(page, base_url)
    verify_community_state(
        page,
        expected_text=expected_text,
        expected_reviewer_rows=expected_reviewer_rows,
        expected_actions=expected_actions,
    )
    verify_no_horizontal_overflow(page, f"{screenshot_stem} community restored at 1440px")


def main() -> None:
    base_url = normalize_loopback_origin(os.environ.get("SWIPE_WEB_URL", DEFAULT_BASE_URL))
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    browser_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=DESKTOP_VIEWPORT)
        page.on("pageerror", lambda error: browser_errors.append(f"page error: {error}"))
        page.on(
            "console",
            lambda message: (
                browser_errors.append(f"console error: {message.text}")
                if message.type == "error"
                else None
            ),
        )

        enter_synthetic_app(page, base_url)
        capture_discover_and_open_review(page)
        capture_responsive_community(
            page,
            base_url,
            screenshot_stem="community-open",
            expected_text="0 / 3 trusted votes",
            expected_reviewer_rows=3,
        )
        complete_community_review(page, base_url)
        create_reciprocal_match(page)
        capture_responsive_community(
            page,
            base_url,
            screenshot_stem="community",
            expected_text="Synthetic human restored",
            expected_reviewer_rows=0,
        )
        browser.close()

    if browser_errors:
        raise AssertionError(f"browser errors: {browser_errors}")
    print(f"Browser acceptance passed; screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()

"""Headless browser acceptance flow for the canonical synthetic web app."""

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


def verify_skip_link(page: Page) -> None:
    skip_link = page.get_by_role("link", name="Skip to main content", exact=True)
    expect(skip_link).to_have_count(1)
    page.keyboard.press("Tab")
    expect(skip_link).to_be_visible()
    page.keyboard.press("Enter")
    page.wait_for_function("window.location.hash === '#main-content'")
    expect(page.locator("#main-content")).to_be_focused()


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


def enter_synthetic_app(page: Page, base_url: str) -> None:
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    expect(page.get_by_role("heading", name="Adults 18+ only.")).to_be_visible()
    expect(page.get_by_text("LOCAL RESEARCH BUILD", exact=True)).to_be_visible()
    expect(page.get_by_text("SYNTHETIC ONLY", exact=True)).to_be_visible()
    expect(page.get_by_text("No real profiles", exact=True)).to_be_visible()
    expect(page.get_by_text("No real messages", exact=True)).to_be_visible()
    expect(page.get_by_text("No location collection", exact=True)).to_be_visible()
    verify_no_horizontal_overflow(page, "age gate desktop")
    page.screenshot(path=SCREENSHOT_DIR / "age-gate.png", full_page=True)
    verify_skip_link(page)

    page.locator("input[name='birth_month'][value='01']").check()
    page.locator("input[name='birth_day'][value='01']").check()
    page.locator("input[name='birth_year'][value='2000']").check()
    page.get_by_role("button", name="Enter synthetic app").click()
    page.wait_for_url(f"{base_url}/discover")


def verify_swipe(page: Page) -> None:
    expect(page.get_by_role("img", name="Synthetic profile placeholder for Alex")).to_be_visible()
    expect(page.locator(".alignment-badge")).to_contain_text("% aligned")
    expect(page.get_by_role("button", name="Pass Alex")).to_be_visible()
    expect(page.get_by_role("button", name="Like Alex")).to_be_visible()
    expect(page.get_by_role("link", name="Open profile")).to_be_visible()
    expect(page.get_by_role("link", name="Open filters")).to_be_visible()
    verify_no_horizontal_overflow(page, "swipe desktop")
    page.screenshot(path=SCREENSHOT_DIR / "swipe.png", full_page=True)


def open_report(page: Page) -> None:
    page.get_by_text("•••", exact=True).click()
    page.get_by_label("Optional note").fill("Synthetic acceptance report note")
    page.get_by_role("button", name="Send private report").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("0 / 7 trusted votes", exact=True)).to_be_visible()


def complete_community_review(page: Page) -> None:
    choices = (
        "Bot-like",
        "Bot-like",
        "Likely human",
        "Bot-like",
        "Bot-like",
        "Likely human",
        "Bot-like",
    )
    for index, button_name in enumerate(choices, start=1):
        row = page.locator(".reviewer-row", has_text=f"reviewer-{index}")
        row.get_by_role("button", name=button_name).click()
        page.wait_for_load_state("networkidle")

    expect(page.get_by_text("7 / 7 trusted votes", exact=True)).to_be_visible()
    expect(page.get_by_text("Temporarily buried", exact=True)).to_be_visible()
    page.screenshot(path=SCREENSHOT_DIR / "community-contained.png", full_page=True)
    page.get_by_role("button", name="Simulate subject appeal").click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Run synthetic adjudication").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Synthetic human restored", exact=True)).to_be_visible()


def create_match_and_open_chat(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/discover")
    page.wait_for_load_state("networkidle")
    page.get_by_role("button", name="Like Alex").click()
    page.wait_for_url(f"{base_url}/matches?*")
    expect(page.get_by_text("People who chose you too.", exact=True)).to_be_visible()
    expect(page.locator(".match-bubble")).to_have_count(1)
    page.locator(".match-bubble").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("No automatic message was sent.", exact=True)).to_be_visible()
    expect(page.get_by_text("Plan a meetup", exact=True)).to_be_visible()
    page.get_by_label("Message Alex").fill("Coffee this week?")
    page.get_by_role("button", name="Send message").click()
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text("Coffee this week?", exact=True)).to_be_visible()
    page.screenshot(path=SCREENSHOT_DIR / "chat.png", full_page=True)


def verify_responsive_swipe(page: Page, base_url: str) -> None:
    for name, viewport in RESPONSIVE_VIEWPORTS:
        page.set_viewport_size(viewport)
        page.goto(f"{base_url}/discover")
        page.wait_for_load_state("networkidle")
        verify_no_horizontal_overflow(page, f"swipe {name}")
        page.screenshot(path=SCREENSHOT_DIR / f"swipe-{name}.png", full_page=True)
    page.set_viewport_size(DESKTOP_VIEWPORT)


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
        verify_swipe(page)
        open_report(page)
        complete_community_review(page)
        verify_responsive_swipe(page, base_url)
        create_match_and_open_chat(page, base_url)
        browser.close()

    if browser_errors:
        raise AssertionError(f"browser errors: {browser_errors}")
    print(f"Browser acceptance passed; screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()

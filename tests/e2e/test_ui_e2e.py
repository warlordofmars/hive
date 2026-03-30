"""
Playwright E2E tests for the Hive management UI.
Requires:
  HIVE_UI_URL   — deployed UI URL (CloudFront)
  HIVE_API_URL  — deployed API URL (used to issue a fresh token)
"""

from __future__ import annotations

import os

import pytest

from tests.e2e.conftest import issue_token_sync

UI_URL = os.environ.get("HIVE_UI_URL", "")

pytestmark = pytest.mark.skipif(
    not UI_URL,
    reason="HIVE_UI_URL not set — skipping UI e2e tests",
)


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import sync_playwright

    token = issue_token_sync()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Inject token into localStorage before navigating
        page.goto(UI_URL)
        page.evaluate(f"localStorage.setItem('hive_token', '{token}')")
        page.reload()

        yield page
        browser.close()


class TestUIE2E:
    def test_memories_tab_visible(self, browser_page):
        page = browser_page
        page.goto(UI_URL)
        assert page.locator("nav button:has-text('Memories')").is_visible()

    def test_create_and_see_memory(self, browser_page):
        page = browser_page
        page.goto(UI_URL)

        page.locator("button:has-text('+ New')").click()
        page.locator("input[placeholder='unique-key']").fill("ui-e2e-key")
        page.locator("textarea").fill("UI e2e test value")
        page.locator("input[placeholder='tag1, tag2']").fill("e2e")
        page.locator("button:has-text('Save')").click()

        page.wait_for_selector("text=ui-e2e-key")
        assert page.locator("text=ui-e2e-key").first.is_visible()

    def test_clients_tab(self, browser_page):
        page = browser_page
        page.locator("nav button:has-text('OAuth Clients')").click()
        assert page.locator("text=Register Client").first.is_visible()

    def test_activity_tab(self, browser_page):
        page = browser_page
        page.locator("nav button:has-text('Activity Log')").click()
        assert page.locator("nav button:has-text('Activity Log')").is_visible()

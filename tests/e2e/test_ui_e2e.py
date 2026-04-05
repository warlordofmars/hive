# Copyright (c) 2026 John Carter. All rights reserved.
"""
Playwright E2E tests for the Hive management UI.
Requires:
  HIVE_UI_URL   — deployed UI URL (CloudFront)
  HIVE_API_URL  — deployed API URL (used to prime the session via bypass login)
"""

from __future__ import annotations

import os

import pytest

UI_URL = os.environ.get("HIVE_UI_URL", "")
API_URL = os.environ.get("HIVE_API_URL", "")

pytestmark = pytest.mark.skipif(
    not UI_URL,
    reason="HIVE_UI_URL not set — skipping UI e2e tests",
)


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # Navigate to the bypass login endpoint via CloudFront (same origin as
        # the UI) so the mgmt JWT lands in the correct localStorage origin.
        # HIVE_BYPASS_GOOGLE_AUTH=1 causes /auth/login to issue a mgmt JWT,
        # write it to localStorage as hive_mgmt_token, and redirect to /.
        page.goto(f"{UI_URL}/auth/login", timeout=30_000, wait_until="networkidle")

        # Should now be at UI_URL root with hive_mgmt_token in localStorage.
        page.wait_for_url(f"{UI_URL}**", timeout=10_000)

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

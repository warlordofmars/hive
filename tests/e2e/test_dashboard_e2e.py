# Copyright (c) 2026 John Carter. All rights reserved.
"""
Playwright E2E tests for the Hive Dashboard UI (admin-only).
Must run in its own pytest invocation — mixing with async test files causes
pytest-asyncio to start an event loop that blocks sync_playwright().
Requires:
  HIVE_UI_URL        — deployed UI URL (CloudFront)
  HIVE_ADMIN_EMAIL   — admin email for Google auth bypass
"""

from __future__ import annotations

import os

import pytest

UI_URL = os.environ.get("HIVE_UI_URL", "")
ADMIN_EMAIL = os.environ.get("HIVE_ADMIN_EMAIL", "")

pytestmark = pytest.mark.skipif(
    not UI_URL,
    reason="HIVE_UI_URL not set — skipping dashboard e2e tests",
)


@pytest.fixture(scope="module")
def admin_browser_page():
    """Browser page logged in as an admin user via the Google auth bypass."""
    if not ADMIN_EMAIL:
        pytest.skip("HIVE_ADMIN_EMAIL not set — skipping admin UI e2e tests")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        page.goto(
            f"{UI_URL}/auth/login?test_email={ADMIN_EMAIL}",
            timeout=30_000,
            wait_until="networkidle",
        )
        page.goto(f"{UI_URL}/app", timeout=30_000, wait_until="networkidle")

        yield page
        browser.close()


class TestDashboardE2E:
    def test_dashboard_tab_visible_for_admin(self, admin_browser_page):
        page = admin_browser_page
        page.goto(f"{UI_URL}/app", timeout=30_000, wait_until="networkidle")
        assert page.locator("nav button:has-text('Dashboard')").is_visible()

    def test_dashboard_renders_without_error(self, admin_browser_page):
        page = admin_browser_page
        page.locator("nav button:has-text('Dashboard')").click()
        page.wait_for_load_state("networkidle")
        # No error banner should be present after metrics load
        assert not page.locator("text=Failed to load metrics").is_visible()
        assert not page.locator("text=Failed to load costs").is_visible()

    def test_dashboard_period_selector(self, admin_browser_page):
        page = admin_browser_page
        page.locator("nav button:has-text('Dashboard')").click()
        page.wait_for_load_state("networkidle")
        # Switch through all period options — none should trigger an error banner
        for period in ("1h", "7d", "30d", "24h"):
            page.locator(f"button:has-text('{period}')").click()
            page.wait_for_load_state("networkidle")
            assert not page.locator("text=Failed to load metrics").is_visible(), (
                f"Error banner appeared after switching to {period}"
            )

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
ADMIN_EMAIL = os.environ.get("HIVE_ADMIN_EMAIL", "")

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

        # Token is now in localStorage. Navigate directly to /app — the
        # HomeRoute would also redirect there, but client-side redirects can
        # race with wait_for_url so we go straight to the destination.
        page.goto(f"{UI_URL}/app", timeout=30_000, wait_until="networkidle")

        yield page
        browser.close()


class TestUIE2E:
    def test_memories_tab_visible(self, browser_page):
        page = browser_page
        page.goto(UI_URL)
        assert page.locator("nav button:has-text('Memories')").is_visible()

    def test_create_and_see_memory(self, browser_page):
        import time

        page = browser_page
        # Use a unique key so stale data from previous runs never causes a
        # ownership conflict (404) in the multi-tenant API.
        memory_key = f"ui-e2e-{int(time.time())}"

        page.goto(UI_URL)
        page.wait_for_load_state("networkidle")  # wait for initial memories load
        # Ensure we're on Memories tab regardless of first-run redirect
        page.locator("nav button:has-text('Memories')").click()
        page.wait_for_load_state("networkidle")

        page.locator("button:has-text('+ New')").click()
        page.locator("input[placeholder='unique-key']").fill(memory_key)
        page.locator("textarea").fill("UI e2e test value")
        page.locator("input[placeholder='tag1, tag2']").fill("e2e")

        with page.expect_response(
            lambda r: "/api/memories" in r.url and r.request.method == "POST",
            timeout=30_000,
        ) as resp_info:
            page.locator("button:has-text('Save')").click()
        assert resp_info.value.ok, f"POST /api/memories failed: {resp_info.value.status}"

        page.wait_for_selector(f"text={memory_key}", timeout=30_000)
        assert page.locator(f"text={memory_key}").first.is_visible()

    def test_clients_tab(self, browser_page):
        page = browser_page
        page.locator("nav button:has-text('OAuth Clients')").click()
        assert page.locator("text=Register Client").first.is_visible()

    def test_activity_tab(self, browser_page):
        page = browser_page
        page.locator("nav button:has-text('Activity Log')").click()
        assert page.locator("nav button:has-text('Activity Log')").is_visible()


@pytest.fixture()
async def admin_browser_page():
    """Browser page logged in as an admin user via the Google auth bypass.

    Uses the async Playwright API to avoid conflicts with pytest-asyncio's
    event loop (sync_playwright() raises if a loop is already running).
    """
    if not ADMIN_EMAIL:
        pytest.skip("HIVE_ADMIN_EMAIL not set — skipping admin UI e2e tests")

    from playwright.async_api import async_playwright

    # Use .start() instead of the context-manager form — async_playwright() as a
    # context manager creates its own asyncio Runner, which raises when a loop
    # is already running (pytest-asyncio asyncio_mode=auto keeps one live).
    p = await async_playwright().start()
    browser = await p.chromium.launch()
    page = await browser.new_page()

    await page.goto(
        f"{UI_URL}/auth/login?test_email={ADMIN_EMAIL}",
        timeout=30_000,
        wait_until="networkidle",
    )
    await page.goto(f"{UI_URL}/app", timeout=30_000, wait_until="networkidle")

    yield page
    await browser.close()
    await p.stop()


class TestDashboardE2E:
    async def test_dashboard_tab_visible_for_admin(self, admin_browser_page):
        page = admin_browser_page
        await page.goto(f"{UI_URL}/app", timeout=30_000, wait_until="networkidle")
        assert await page.locator("nav button:has-text('Dashboard')").is_visible()

    async def test_dashboard_renders_without_error(self, admin_browser_page):
        page = admin_browser_page
        await page.locator("nav button:has-text('Dashboard')").click()
        await page.wait_for_load_state("networkidle")
        # No error banner should be present after metrics load
        assert not await page.locator("text=Failed to load metrics").is_visible()
        assert not await page.locator("text=Failed to load costs").is_visible()

    async def test_dashboard_period_selector(self, admin_browser_page):
        page = admin_browser_page
        await page.locator("nav button:has-text('Dashboard')").click()
        await page.wait_for_load_state("networkidle")
        # Switch through all period options — none should trigger an error banner
        for period in ("1h", "7d", "24h"):
            await page.locator(f"button:has-text('{period}')").click()
            await page.wait_for_load_state("networkidle")
            assert not await page.locator("text=Failed to load metrics").is_visible(), (
                f"Error banner appeared after switching to {period}"
            )

# Copyright (c) 2026 John Carter. All rights reserved.
"""
Playwright E2E tests for the Hive VitePress docs site.
Requires:
  HIVE_UI_URL — deployed UI URL (CloudFront), e.g. https://hive.warlordofmars.net
"""

from __future__ import annotations

import os

import pytest

UI_URL = os.environ.get("HIVE_UI_URL", "")

pytestmark = pytest.mark.skipif(
    not UI_URL,
    reason="HIVE_UI_URL not set — skipping docs e2e tests",
)


@pytest.fixture(scope="module")
def docs_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        yield page
        browser.close()


class TestDocsE2E:
    def test_docs_home_loads(self, docs_page):
        """GET /docs/ returns the VitePress home page, not the React app."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        # VitePress home has a hero heading; the React app has a Login button
        assert page.locator("text=Hive").first.is_visible()
        # Must NOT be the React app (which has a Sign in / Sign out button)
        assert not page.locator("button:has-text('Sign in')").is_visible()

    def test_docs_home_title(self, docs_page):
        """Page title contains 'Hive Docs'."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        assert "Hive" in page.title()

    def test_docs_subpage_loads(self, docs_page):
        """A nested doc page loads without redirecting to the React app."""
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start",
            timeout=30_000,
            wait_until="networkidle",
        )
        assert page.locator("h1").first.is_visible()
        assert not page.locator("button:has-text('Sign in')").is_visible()

    def test_docs_trailing_slash_page_loads(self, docs_page):
        """Trailing slash on a content page resolves correctly (CloudFront Function)."""
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start/",
            timeout=30_000,
            wait_until="networkidle",
        )
        assert page.locator("h1").first.is_visible()
        assert not page.locator("button:has-text('Sign in')").is_visible()

    def test_docs_logo_not_broken(self, docs_page):
        """Logo image loads successfully (not a broken image).

        Uses a doc page (not home) so the VitePress navbar logo is always rendered.
        """
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start",
            timeout=30_000,
            wait_until="networkidle",
        )
        logo = page.locator("img[alt='Hive']")
        assert logo.is_visible()
        natural_width = page.evaluate("el => el.naturalWidth", logo.element_handle())
        assert natural_width > 0, "Logo image failed to load (naturalWidth == 0)"

    def test_docs_sidebar_navigation(self, docs_page):
        """Sidebar section headings are visible on a doc page."""
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start",
            timeout=30_000,
            wait_until="networkidle",
        )
        # Sidebar is only rendered on doc pages (not the home layout)
        assert page.locator(".VPSidebar").is_visible()

    def test_docs_search_present(self, docs_page):
        """Local search button is present."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        assert (
            page.locator("button.DocSearch").is_visible()
            or page.locator("[aria-label='Search']").is_visible()
        )

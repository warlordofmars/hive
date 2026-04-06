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

# Expected navbar background — #1a1a2e in RGB
_NAVBAR_BG = "rgb(26, 26, 46)"
# Minimum luminance ratio considered "light enough" for white-on-dark text
# rgb(255,255,255) on rgb(26,26,46) is ~12:1, well above 4.5:1 WCAG AA
_MIN_ALPHA = 0.6  # channel value 0–1 for rgba text colours


@pytest.fixture(scope="module")
def docs_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        yield page
        browser.close()


@pytest.fixture(scope="module")
def docs_page_mobile():
    """Separate page at 375×812 (iPhone viewport) for mobile tests."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 375, "height": 812})
        yield page
        browser.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bg(page, selector: str) -> str:
    return page.evaluate(
        f"() => window.getComputedStyle(document.querySelector('{selector}')).backgroundColor"
    )


def _color(page, selector: str) -> str:
    return page.evaluate(
        f"() => window.getComputedStyle(document.querySelector('{selector}')).color"
    )


def _parse_rgb(css: str) -> tuple[int, int, int, float]:
    """Parse rgb(...) or rgba(...) → (r, g, b, a)."""
    import re

    nums = [float(x) for x in re.findall(r"[\d.]+", css)]
    r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
    a = float(nums[3]) if len(nums) > 3 else 1.0
    return r, g, b, a


# ---------------------------------------------------------------------------
# General docs routing tests
# ---------------------------------------------------------------------------


class TestDocsRouting:
    def test_docs_home_loads(self, docs_page):
        """GET /docs/ returns the VitePress home page, not the React app."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        assert page.locator("text=Hive").first.is_visible()
        assert not page.locator("button:has-text('Sign in')").is_visible()

    def test_docs_home_title(self, docs_page):
        """Page title contains 'Hive'."""
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
        """Logo image loads successfully (not a broken image)."""
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
        assert page.locator(".VPSidebar").is_visible()

    def test_docs_search_present(self, docs_page):
        """Local search button is present."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        assert (
            page.locator("button.DocSearch").is_visible()
            or page.locator("[aria-label='Search']").is_visible()
        )


# ---------------------------------------------------------------------------
# Navbar appearance and behaviour tests
# ---------------------------------------------------------------------------


class TestDocsNavbar:
    def test_navbar_dark_on_doc_page(self, docs_page):
        """Navbar background is dark navy on a doc page (sidebar layout)."""
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start",
            timeout=30_000,
            wait_until="networkidle",
        )
        bg = _bg(page, ".VPNavBar")
        assert bg == _NAVBAR_BG, (
            f"Expected navbar bg {_NAVBAR_BG!r} on doc page, got {bg!r}. "
            "Check .VPNavBar and .content-body CSS overrides."
        )

    def test_navbar_dark_on_home_page(self, docs_page):
        """Navbar background is dark navy on the home page."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        bg = _bg(page, ".VPNavBar")
        assert bg == _NAVBAR_BG, (
            f"Expected navbar bg {_NAVBAR_BG!r} on home page, got {bg!r}. "
            "Check .VPNavBar.home.top CSS override."
        )

    def test_navbar_dark_after_scroll(self, docs_page):
        """Navbar stays dark navy after scrolling down on a doc page."""
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start",
            timeout=30_000,
            wait_until="networkidle",
        )
        page.evaluate("window.scrollBy(0, 300)")
        page.wait_for_timeout(400)  # allow transition
        bg = _bg(page, ".VPNavBar")
        assert bg == _NAVBAR_BG, (
            f"Navbar bg changed after scroll: {bg!r}. "
            "Check .VPNavBar:not(.home) desktop media-query override."
        )

    def test_navbar_title_is_light(self, docs_page):
        """Site title text is light (readable on dark navbar)."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        color = _color(page, ".VPNavBarTitle .title")
        r, g, b, _ = _parse_rgb(color)
        # All channels should be high (near white)
        assert r > 200 and g > 200 and b > 200, (
            f"Navbar title text {color!r} is too dark for dark background. "
            "Check .VPNavBarTitle .title color override."
        )

    def test_nav_links_are_light(self, docs_page):
        """Navigation menu links are light-coloured (readable on dark navbar)."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        # Get first nav menu link
        link = page.locator(".VPNavBarMenuLink").first
        if not link.is_visible():
            pytest.skip("No nav menu links visible (may be mobile viewport)")
        color = page.evaluate(
            "el => window.getComputedStyle(el).color",
            link.element_handle(),
        )
        r, g, b, a = _parse_rgb(color)
        # Text should be at least 60% bright (alpha of rgba or high rgb values)
        assert r > 150 and g > 150 and b > 150, (
            f"Nav link color {color!r} is too dark for dark navbar. "
            "Check .VPNavBarMenuLink color override."
        )

    def test_content_body_dark_on_sidebar_page(self, docs_page):
        """The content-body (right navbar section) is dark on a sidebar page."""
        page = docs_page
        page.goto(
            f"{UI_URL}/docs/getting-started/quick-start",
            timeout=30_000,
            wait_until="networkidle",
        )
        content_body = page.locator(".VPNavBar .content-body")
        if not content_body.is_visible():
            pytest.skip(".content-body not visible (may be mobile viewport)")
        bg = page.evaluate(
            "el => window.getComputedStyle(el).backgroundColor",
            content_body.element_handle(),
        )
        assert bg == _NAVBAR_BG, (
            f"Expected .content-body bg {_NAVBAR_BG!r} on sidebar page, got {bg!r}. "
            "Check .VPNavBar .content-body CSS override."
        )

    def test_docs_nav_link_no_double_prefix(self, docs_page):
        """Docs nav link href is '/docs/' — VitePress base must not be double-applied.

        config.mjs must use link: '/' (not '/docs/') so that VitePress prepends
        the base once, producing '/docs/', not '/docs/docs/'.
        """
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        docs_link = page.locator(".VPNavBarMenuLink", has_text="Docs")
        if not docs_link.is_visible():
            pytest.skip("Docs nav link not visible")
        href = docs_link.get_attribute("href")
        assert href == "/docs/", (
            f"Docs nav link href {href!r} is not '/docs/'. "
            "Check that config.mjs uses link: '/' — VitePress prepends the base automatically."
        )
        assert "/docs/docs" not in href, (
            f"Docs nav link has double prefix: {href!r}. "
            "Set link: '/' in config.mjs nav, not link: '/docs/'."
        )

    def test_docs_nav_link_click(self, docs_page):
        """Clicking Docs nav link stays on /docs/ — no double redirect."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        docs_link = page.locator(".VPNavBarMenuLink", has_text="Docs")
        if not docs_link.is_visible():
            pytest.skip("Docs nav link not visible")
        with page.expect_navigation(timeout=15_000):
            docs_link.click()
        assert "/docs/docs" not in page.url, (
            f"Docs link navigated to {page.url!r} — double prefix detected."
        )
        assert page.url.rstrip("/").endswith("/docs"), (
            f"Docs link navigated to {page.url!r} — expected to stay at '/docs/'."
        )

    def test_home_nav_link_click(self, docs_page):
        """Clicking Home nav link stays within the site (no broken redirect)."""
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        home_link = page.locator(".VPNavBarMenuLink", has_text="Home")
        if not home_link.is_visible():
            pytest.skip("Home nav link not visible")
        with page.expect_navigation(timeout=15_000):
            home_link.click()
        # Home link (link: '/') gets base prepended → /docs/ (docs home page)
        assert UI_URL in page.url, f"Home link navigated outside the site: {page.url!r}."

    def test_signin_nav_link_click(self, docs_page):
        """Clicking Sign in nav link reaches the React app (/app).

        The CloudFront Function redirects /docs/app → /app so the user lands
        on the correct sign-in page, not a 404 or docs page.
        """
        page = docs_page
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        signin_link = page.locator(".VPNavBarMenuLink", has_text="Sign in")
        if not signin_link.is_visible():
            pytest.skip("Sign in nav link not visible")
        with page.expect_navigation(timeout=15_000):
            signin_link.click()
        assert page.url.rstrip("/").endswith("/app"), (
            f"Sign in link navigated to {page.url!r} — expected URL ending in '/app'."
        )

    def test_navbar_hamburger_visible_mobile(self, docs_page_mobile):
        """Hamburger menu button is visible on mobile viewport."""
        page = docs_page_mobile
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        hamburger = page.locator(".VPNavBarHamburger")
        assert hamburger.is_visible(), "Hamburger button not visible on mobile viewport"

    def test_navbar_mobile_menu_toggle(self, docs_page_mobile):
        """Clicking the hamburger opens the mobile nav screen."""
        page = docs_page_mobile
        page.goto(f"{UI_URL}/docs/", timeout=30_000, wait_until="networkidle")
        hamburger = page.locator(".VPNavBarHamburger")
        hamburger.click()
        page.wait_for_timeout(300)
        screen = page.locator(".VPNavScreen")
        assert screen.is_visible(), "Mobile nav screen did not open after hamburger click"

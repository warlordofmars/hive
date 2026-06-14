# Copyright (c) 2026 John Carter. All rights reserved.
"""
Playwright E2E tests for the Hive management UI.
Requires:
  HIVE_UI_URL   — deployed UI URL (CloudFront)
  HIVE_API_URL  — deployed API URL (used to prime the session via bypass login)
"""

from __future__ import annotations

import os
from urllib.parse import quote

import pytest

UI_URL = os.environ.get("HIVE_UI_URL", "")
API_URL = os.environ.get("HIVE_API_URL", "")

pytestmark = pytest.mark.skipif(
    not UI_URL,
    reason="HIVE_UI_URL not set — skipping UI e2e tests",
)


@pytest.fixture(scope="module")
def _chromium():
    """One shared Chromium for the module.

    Both the admin (``browser_page``) and non-admin (``nonadmin_page``) fixtures
    open a context on this single browser. They must share one
    ``sync_playwright`` instance — two simultaneously-open sync-Playwright
    contexts collide with pytest-asyncio's running loop ("Sync API inside the
    asyncio loop").
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def _open_authenticated_page(browser, test_email):
    """Open a Chromium context on ``browser`` authenticated as ``test_email``.

    Returns ``(context, page)``; the caller owns context teardown.
    """
    context = browser.new_context()

    # #619 shipped an OnboardingTour that renders a full-viewport
    # backdrop with pointer-events-auto on first visit — its
    # "click outside to dismiss" behaviour intercepts every
    # nav-tab click until it's dismissed. An `add_init_script`
    # pre-sets the dismissed flag on every page that loads in
    # this context so e2e tests never see the overlay.
    #
    # `hive_first_memory_skipped=1` pre-disables the post-create
    # "first memory probe" in MemoryBrowser.handleCreate (#645).
    # The probe itself no longer clobbers the filtered list — the
    # underlying race was fixed in the same PR (loadRef +
    # dropping the optimistic setMemories shortcut) — but skipping
    # it puts the e2e fixture in the same steady state real users
    # experience after their first save: one POST + one filtered
    # GET, no spare unfiltered round trip racing the assertion.
    context.add_init_script(
        "localStorage.setItem('hive_tour_dismissed', '1');"
        "localStorage.setItem('hive_first_memory_skipped', '1');"
    )
    page = context.new_page()

    # Navigate to the bypass login endpoint via CloudFront (same origin as
    # the UI) so the mgmt JWT lands in the correct localStorage origin.
    # test_email is required — HIVE_BYPASS_GOOGLE_AUTH only triggers the
    # synthetic path when test_email is explicitly supplied (#140).
    page.goto(
        # Encode the whole value — '+' (plus-addressing) would otherwise decode
        # to a space server-side and flip the email to a different identity.
        f"{UI_URL}/auth/login?test_email={quote(test_email, safe='')}",
        timeout=30_000,
        wait_until="networkidle",
    )

    # Token is now in localStorage. Navigate directly to /app — the
    # HomeRoute would also redirect there, but client-side redirects can
    # race with wait_for_url so we go straight to the destination.
    page.goto(f"{UI_URL}/app", timeout=30_000, wait_until="networkidle")
    return context, page


@pytest.fixture(scope="module")
def browser_page(_chromium):
    # e2e@example.com is on the dev admin allowlist, so this is an admin session
    # (the tab set / "see all" behaviour most UI tests exercise).
    context, page = _open_authenticated_page(_chromium, "e2e@example.com")
    yield page
    context.close()


@pytest.fixture(scope="module")
def nonadmin_page(_chromium):
    """Authenticated page for a NON-admin user, where read-your-writes holds.

    The default ``browser_page`` user (``e2e@example.com``) is an admin: the
    management API's ``_user_filter`` returns ``None`` for admins ("see all"),
    so a tag-filtered list cannot use the per-user strongly-consistent USERTAG
    path (#568) and falls back to the eventually-consistent TagIndex GSI — a
    just-created memory can lag the filtered GET (#679). A non-allowlisted
    ``test_email`` registers as ``role="user"``, so its reads are scoped to its
    own ``owner_user_id`` and served from the consistent USERTAG path: a fresh
    write is visible the instant the POST returns. Use this fixture for any
    test that asserts a newly-created memory is immediately readable.
    """
    context, page = _open_authenticated_page(_chromium, "e2e-nonadmin@example.com")
    yield page
    context.close()


class TestMarketingNav:
    def test_signin_btn_border_is_visible(self, _chromium):
        """Sign in button on marketing navbar has a visible border (not transparent).

        Asserts the computed border-color so CSS regressions can't sneak past a
        class-name check.  The nav variant bakes border-white/60 into the variant
        itself — no className override needed.

        Uses the shared ``_chromium`` browser (its own fresh page, no auth needed
        for the marketing root) so the module holds exactly one ``sync_playwright``
        instance — a second one could overlap with it and trip pytest-asyncio's
        "Sync API inside the asyncio loop" guard.
        """
        page = _chromium.new_page()
        try:
            page.goto(f"{UI_URL}/", timeout=30_000, wait_until="networkidle")
            signin_btn = page.locator(".marketing-signin-btn")
            if not signin_btn.is_visible():
                pytest.skip("Sign in button not visible (may be mobile viewport)")
            border_color = signin_btn.evaluate("el => getComputedStyle(el).borderColor")
            import re

            nums = [float(x) for x in re.findall(r"[\d.]+", border_color)]
            assert len(nums) >= 4 and nums[3] > 0, (
                f"Sign in button border is transparent: {border_color!r}. "
                "Check that the nav variant in button.jsx applies border-white/60."
            )
        finally:
            page.close()


class TestUIE2E:
    def test_memories_tab_visible(self, browser_page):
        page = browser_page
        page.goto(UI_URL)
        assert page.locator("nav button:has-text('Memories')").is_visible()

    def test_create_and_see_memory(self, nonadmin_page):
        import time

        # Runs as a NON-admin user so the tag-filtered read is owner-scoped and
        # served from the strongly-consistent USERTAG path — read-your-writes
        # holds and the assertion below is deterministic. As an admin (the
        # default browser_page user) this read would come from the eventually-
        # consistent GSI and intermittently miss the just-created memory (#679).
        page = nonadmin_page
        # Use a unique key AND a unique tag per run.  The key avoids ownership
        # conflicts; the tag is used to filter the list immediately after create
        # so we never depend on the new memory appearing on page 1 of an
        # unfiltered list (accumulated test data from past runs can push it off).
        ts = int(time.time())
        memory_key = f"ui-e2e-{ts}"
        unique_tag = f"e2e-{ts}"

        page.goto(UI_URL)
        page.wait_for_load_state("networkidle")  # wait for initial memories load
        # Ensure we're on Memories tab regardless of first-run redirect
        page.locator("nav button:has-text('Memories')").click()
        page.wait_for_load_state("networkidle")

        page.locator("button:has-text('+ New')").first.click()
        page.locator("input[placeholder='unique-key']").fill(memory_key)
        page.locator("textarea").fill("UI e2e test value")
        page.locator("input[placeholder='tag1, tag2']").fill(unique_tag)

        with page.expect_response(
            lambda r: "/api/memories" in r.url and r.request.method == "POST",
            timeout=30_000,
        ) as resp_info:
            page.locator("button:has-text('Save')").click()
        assert resp_info.value.ok, f"POST /api/memories failed: {resp_info.value.status}"

        # Wait for the list to reload after save.
        page.wait_for_load_state("networkidle")

        # Apply tag filter. The USERTAG strongly-consistent path (#568) means
        # the memory is visible to the GET as soon as the POST returns — but
        # the previous wait_for_load_state("networkidle") + manual retry
        # pattern raced the React useEffect that fires the tag-filtered GET
        # (#645): networkidle returns immediately when the page is already
        # loaded, so the assertion runs before the in-flight GET resolves.
        # Use Playwright's auto-waiting expect() instead — it polls until the
        # locator becomes visible or the timeout elapses.
        from playwright.sync_api import expect

        tag_input = page.locator("input[placeholder='Filter by tag']")
        tag_input.fill(unique_tag)
        tag_input.press("Enter")
        expect(page.locator(f"text={memory_key}").first).to_be_visible(timeout=15_000)

    def test_clients_tab(self, browser_page):
        page = browser_page
        page.locator("nav button:has-text('OAuth Clients')").click()
        assert page.locator("text=Register Client").first.is_visible()

    def test_activity_tab(self, browser_page):
        page = browser_page
        page.locator("nav button:has-text('Activity Log')").click()
        assert page.locator("nav button:has-text('Activity Log')").is_visible()

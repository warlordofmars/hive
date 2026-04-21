// Copyright (c) 2026 John Carter. All rights reserved.
import React, { useEffect, useState } from "react";
import { Button } from "./ui/button.jsx";

const DISMISSED_KEY = "hive_tour_dismissed";

// Each step pairs a tab id (matched against `data-tab-id` on the
// nav buttons) with a short blurb. The component finds the tab's
// bounding rect at render time so we don't have to forwardRef
// through the tab nav.
const BASE_STEPS = [
  {
    tabId: "memories",
    title: "Your memory store",
    body: "Every memory your agent remembers lives here. Browse, search, and edit anything in this tab.",
  },
  {
    tabId: "setup",
    title: "Connect your first agent",
    body: "Setup walks you through wiring Hive into Claude Code, ChatGPT, or any MCP client — start here on day one.",
  },
  {
    tabId: "activity",
    title: "See your agents at work",
    body: "Every tool call lands here, with the agent name and timestamp, so you can audit what your agents are doing.",
  },
  {
    tabId: "clients",
    title: "Manage OAuth clients",
    body: "Each MCP client registers an OAuth client here. Revoke access at any time.",
  },
];

const ADMIN_STEP = {
  tabId: "dashboard",
  title: "Admin dashboard",
  body: "CloudWatch metrics, cost data, and system health — only admins see this tab.",
};

export function _isDismissed() {
  return !!localStorage.getItem(DISMISSED_KEY);
}

export function _markDismissed() {
  localStorage.setItem(DISMISSED_KEY, "1");
}

export default function OnboardingTour({ isAdmin = false }) {
  const [dismissed, setDismissed] = useState(_isDismissed);
  const [stepIndex, setStepIndex] = useState(0);
  const [tick, setTick] = useState(0);

  // Re-measure the spotlight rect on resize so the tooltip stays
  // anchored to its tab when the viewport changes.
  useEffect(() => {
    if (dismissed) return undefined;
    function onResize() { setTick((t) => t + 1); }
    globalThis.addEventListener("resize", onResize);
    return () => globalThis.removeEventListener("resize", onResize);
  }, [dismissed]);

  if (dismissed) return null;

  const steps = isAdmin ? [...BASE_STEPS, ADMIN_STEP] : BASE_STEPS;
  const step = steps[stepIndex];
  // `tick` is read here to keep the dependency array honest — the
  // resize listener bumps it to force a re-measure.
  void tick;
  const target = globalThis.document?.querySelector(
    `[data-tab-id="${step.tabId}"]`,
  );
  const rect = target?.getBoundingClientRect();

  function dismiss() {
    _markDismissed();
    setDismissed(true);
  }

  function next() {
    if (stepIndex >= steps.length - 1) {
      dismiss();
      return;
    }
    setStepIndex(stepIndex + 1);
  }

  function back() {
    if (stepIndex > 0) setStepIndex(stepIndex - 1);
  }

  // Position the tooltip below the highlighted tab. Falls back to
  // top-of-viewport when the tab can't be found (e.g. mobile drawer
  // closed) so the user still sees the overlay.
  const tooltipStyle = rect
    ? { top: rect.bottom + 12, left: Math.max(12, rect.left) }
    : { top: 80, left: 16 };

  return (
    <div
      data-testid="onboarding-tour"
      className="fixed inset-0 z-[60] pointer-events-none"
    >
      {/* Backdrop — click anywhere outside the tooltip to dismiss. */}
      <button
        type="button"
        aria-label="Dismiss onboarding tour"
        onClick={dismiss}
        className="absolute inset-0 bg-black/40 pointer-events-auto cursor-pointer border-0 p-0"
      />
      {/* Spotlight outline around the highlighted tab. */}
      {rect && (
        <div
          aria-hidden="true"
          className="absolute pointer-events-none rounded"
          style={{
            top: rect.top - 4,
            left: rect.left - 4,
            width: rect.width + 8,
            height: rect.height + 8,
            boxShadow: "0 0 0 9999px rgba(0,0,0,0.4), 0 0 0 3px var(--accent)",
          }}
        />
      )}
      {/* Tooltip card. */}
      <div
        role="dialog"
        aria-labelledby="onboarding-tour-title"
        data-testid="onboarding-tour-card"
        className="absolute pointer-events-auto bg-[var(--surface)] border border-[var(--border)] rounded-md shadow-lg p-4 max-w-[320px]"
        style={tooltipStyle}
      >
        <p
          className="text-[11px] font-semibold tracking-[1px] text-[var(--text-muted)] uppercase mb-1"
          aria-hidden="true"
        >
          Step {stepIndex + 1} of {steps.length}
        </p>
        <h3 id="onboarding-tour-title" className="text-base font-bold mb-2">
          {step.title}
        </h3>
        <p className="text-[13px] text-[var(--text-muted)] mb-4">{step.body}</p>
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            onClick={dismiss}
            className="text-[12px] text-[var(--text-muted)] underline cursor-pointer bg-transparent border-0 p-0"
          >
            Skip
          </button>
          <div className="flex gap-2">
            {stepIndex > 0 && (
              <Button variant="outline" size="sm" onClick={back}>
                Back
              </Button>
            )}
            <Button size="sm" onClick={next}>
              {stepIndex >= steps.length - 1 ? "Got it" : "Next"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

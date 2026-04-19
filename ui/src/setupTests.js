// Copyright (c) 2026 John Carter. All rights reserved.
import "@testing-library/jest-dom";

// jsdom does not implement scrollIntoView; stub it so components that call it
// do not throw and coverage branches are reachable.
globalThis.HTMLElement.prototype.scrollIntoView = function () {};

// useTheme reads `matchMedia("(prefers-color-scheme: dark)")` on first render.
// jsdom doesn't ship matchMedia, so stub a default-light response. Individual
// tests that need a different value (e.g. the useTheme suite) can override
// with `vi.stubGlobal("matchMedia", ...)`.
if (typeof globalThis.matchMedia === "undefined") {
  globalThis.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

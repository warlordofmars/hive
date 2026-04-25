// Copyright (c) 2026 John Carter. All rights reserved.
import "@testing-library/jest-dom";

// URL.createObjectURL and URL.revokeObjectURL are not implemented in jsdom.
// Stub them as vi.fn() so components that call them don't throw.
// Individual tests can call .mockReturnValue(...) to control the return.
globalThis.URL.createObjectURL = vi.fn(() => "blob:test-url");
globalThis.URL.revokeObjectURL = vi.fn();

// jsdom does not implement scrollIntoView; stub it so components that call it
// do not throw and coverage branches are reachable.
globalThis.HTMLElement.prototype.scrollIntoView = function () {};

// Node.js v22+ ships a built-in localStorage stub that is missing standard
// methods (removeItem, setItem, etc.) that jsdom 24.x does not fully override.
// Replace it with a complete in-memory implementation so tests that call any
// Storage method don't throw on Node v22+.
if (typeof globalThis.localStorage?.removeItem !== "function") {
  const _store = Object.create(null);
  globalThis.localStorage = {
    getItem: (k) => Object.prototype.hasOwnProperty.call(_store, k) ? _store[k] : null,
    setItem: (k, v) => { _store[String(k)] = String(v); },
    removeItem: (k) => { delete _store[String(k)]; },
    clear: () => { Object.keys(_store).forEach((k) => delete _store[k]); },
    get length() { return Object.keys(_store).length; },
    key: (i) => Object.keys(_store)[i] ?? null,
  };
}

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

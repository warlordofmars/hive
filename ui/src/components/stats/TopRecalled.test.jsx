// Copyright (c) 2026 John Carter. All rights reserved.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TopRecalled, { openMemory } from "./TopRecalled.jsx";

// Recharts uses ResponsiveContainer which needs ResizeObserver in jsdom.
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

const _data = [
  { memory_id: "m1", key: "top-key", recall_count: 10 },
  { memory_id: "m2", key: "next-key", recall_count: 4 },
];

describe("TopRecalled", () => {
  let dispatchSpy;

  beforeEach(() => {
    dispatchSpy = vi.spyOn(globalThis, "dispatchEvent");
  });

  afterEach(() => {
    dispatchSpy.mockRestore();
  });

  it("renders empty state when data is missing", () => {
    render(<TopRecalled />);
    expect(screen.getByText(/no recalls yet/i)).toBeTruthy();
  });

  it("renders empty state when data is empty array", () => {
    render(<TopRecalled data={[]} />);
    expect(screen.getByText(/no recalls yet/i)).toBeTruthy();
  });

  it("renders a chart container when data is present", () => {
    const { container } = render(<TopRecalled data={_data} />);
    expect(screen.queryByText(/no recalls yet/i)).toBeNull();
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });

  it("openMemory dispatches memory-browser then switch-tab", () => {
    openMemory({ memory_id: "m1", key: "top-key", recall_count: 10 });
    const types = dispatchSpy.mock.calls.map((c) => c[0].type);
    expect(types).toContain("hive:memory-browser");
    expect(types).toContain("hive:switch-tab");
    const browserEvent = dispatchSpy.mock.calls.find(
      (c) => c[0].type === "hive:memory-browser",
    )[0];
    expect(browserEvent.detail).toEqual({ search: "top-key" });
    const switchEvent = dispatchSpy.mock.calls.find(
      (c) => c[0].type === "hive:switch-tab",
    )[0];
    expect(switchEvent.detail).toBe("memories");
  });

  it("openMemory is a no-op without a dispatchEvent global", () => {
    const original = globalThis.dispatchEvent;
    // @ts-expect-error — deliberately break the dispatch for this test
    globalThis.dispatchEvent = undefined;
    // Should not throw.
    expect(() => openMemory({ memory_id: "m1", key: "k", recall_count: 1 })).not.toThrow();
    globalThis.dispatchEvent = original;
  });
});

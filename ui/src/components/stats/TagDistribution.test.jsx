// Copyright (c) 2026 John Carter. All rights reserved.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TagDistribution, { buildSlices, filterByTag } from "./TagDistribution.jsx";

global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

describe("buildSlices", () => {
  it("returns empty for missing/empty data", () => {
    expect(buildSlices()).toEqual([]);
    expect(buildSlices([])).toEqual([]);
  });

  it("sorts by count descending", () => {
    const slices = buildSlices([
      { tag: "a", count: 2 },
      { tag: "b", count: 5 },
    ]);
    expect(slices.map((s) => s.tag)).toEqual(["b", "a"]);
  });

  it("bundles anything past the top N into an 'Other' slice", () => {
    const data = Array.from({ length: 12 }, (_, i) => ({
      tag: `t${i}`,
      count: 12 - i,
    }));
    const slices = buildSlices(data);
    // Top 8 + one Other slice = 9 entries.
    expect(slices).toHaveLength(9);
    const other = slices[slices.length - 1];
    expect(other.tag).toBe("Other");
    expect(other.isOther).toBe(true);
    // Other count = sum of tags 9–12 = 4 + 3 + 2 + 1 = 10.
    expect(other.count).toBe(10);
  });

  it("does not add an 'Other' slice when count <= top N", () => {
    const data = Array.from({ length: 4 }, (_, i) => ({ tag: `t${i}`, count: i + 1 }));
    const slices = buildSlices(data);
    expect(slices).toHaveLength(4);
    expect(slices.every((s) => !s.isOther)).toBe(true);
  });
});

describe("TagDistribution", () => {
  it("renders empty state when data is empty", () => {
    render(<TagDistribution data={[]} />);
    expect(screen.getByText(/no tags yet/i)).toBeTruthy();
  });

  it("renders the pie chart when data is present", () => {
    const { container } = render(
      <TagDistribution data={[{ tag: "work", count: 5 }, { tag: "home", count: 3 }]} />,
    );
    expect(screen.queryByText(/no tags yet/i)).toBeNull();
    expect(container.querySelector(".recharts-responsive-container")).toBeTruthy();
  });
});

describe("filterByTag", () => {
  let dispatchSpy;
  beforeEach(() => {
    dispatchSpy = vi.spyOn(globalThis, "dispatchEvent");
  });
  afterEach(() => {
    dispatchSpy.mockRestore();
  });

  it("dispatches memory-browser with tag + switch-tab", () => {
    filterByTag("work");
    const types = dispatchSpy.mock.calls.map((c) => c[0].type);
    expect(types).toContain("hive:memory-browser");
    expect(types).toContain("hive:switch-tab");
    const browserEvent = dispatchSpy.mock.calls.find(
      (c) => c[0].type === "hive:memory-browser",
    )[0];
    expect(browserEvent.detail).toEqual({ tag: "work" });
  });

  it("is a no-op without a dispatchEvent global", () => {
    const original = globalThis.dispatchEvent;
    globalThis.dispatchEvent = undefined;
    expect(() => filterByTag("x")).not.toThrow();
    globalThis.dispatchEvent = original;
  });
});

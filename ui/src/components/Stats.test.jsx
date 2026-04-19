// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Stats, { GraphCard } from "./Stats.jsx";

vi.mock("../api.js", () => ({
  api: {
    getAccountStats: vi.fn(),
  },
}));

import { api } from "../api.js";

const MINIMAL_STATS = {
  window_days: 90,
  activity_heatmap: Array.from({ length: 90 }, (_, i) => ({
    date: `2026-${String((i % 12) + 1).padStart(2, "0")}-01`,
    count: i === 0 ? 3 : 0,
  })),
  top_recalled: [{ memory_id: "m1", key: "top-key", recall_count: 5 }],
  tag_distribution: [{ tag: "work", count: 4 }],
  memory_growth: Array.from({ length: 90 }, (_, i) => ({
    date: `2026-${String((i % 12) + 1).padStart(2, "0")}-01`,
    cumulative: i,
  })),
  quota: { memory_count: 12, memory_limit: 100 },
  freshness: [
    { memory_id: "m1", days_since_created: 10, days_since_accessed: 2 },
  ],
  client_contribution: [{ date: "2026-04-01", client_id: "c1", count: 2 }],
  tag_cooccurrence: [{ source: "a", target: "b", weight: 3 }],
};

describe("GraphCard", () => {
  it("renders children when data is present", () => {
    render(
      <GraphCard title="T" data={[1]}>
        <div>body</div>
      </GraphCard>,
    );
    expect(screen.getByText("body")).toBeTruthy();
  });

  it("renders empty message when data is empty array", () => {
    render(
      <GraphCard title="T" data={[]} empty="nope">
        <div>body</div>
      </GraphCard>,
    );
    expect(screen.getByText("nope")).toBeTruthy();
  });

  it("falls back to default empty copy when no empty prop", () => {
    render(
      <GraphCard title="T" data={[]}>
        <div>body</div>
      </GraphCard>,
    );
    expect(screen.getByText("No data yet.")).toBeTruthy();
  });

  it("renders description when provided", () => {
    render(<GraphCard title="T" description="sub" data={[1]}>body</GraphCard>);
    expect(screen.getByText("sub")).toBeTruthy();
  });

  it("treats object data as present when non-empty", () => {
    render(
      <GraphCard title="T" data={{ foo: 1 }}>
        <div>body</div>
      </GraphCard>,
    );
    expect(screen.getByText("body")).toBeTruthy();
  });

  it("treats empty object as no data", () => {
    render(
      <GraphCard title="T" data={{}}>
        <div>body</div>
      </GraphCard>,
    );
    expect(screen.getByText("No data yet.")).toBeTruthy();
  });

  it("treats undefined data as no data (falls through both type checks)", () => {
    render(
      <GraphCard title="T">
        <div>body</div>
      </GraphCard>,
    );
    expect(screen.getByText("No data yet.")).toBeTruthy();
  });
});

describe("Stats", () => {
  beforeEach(() => {
    api.getAccountStats.mockResolvedValue(MINIMAL_STATS);
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("shows loading state before data arrives", async () => {
    let resolveFn;
    api.getAccountStats.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );
    await act(async () => render(<Stats />));
    expect(screen.getByText("Loading…")).toBeTruthy();
    await act(async () => resolveFn(MINIMAL_STATS));
  });

  it("renders all eight graph-card titles once data arrives", async () => {
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("Activity heatmap")).toBeTruthy());
    for (const title of [
      "Top recalled",
      "Tag distribution",
      "Memory growth",
      "Quota",
      "Freshness",
      "Client contribution",
      "Tag co-occurrence",
    ]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
  });

  it("renders Quota as 'count / limit'", async () => {
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("Quota")).toBeTruthy());
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("100")).toBeTruthy();
  });

  it("renders Quota without limit when memory_limit is null (exempt/admin)", async () => {
    api.getAccountStats.mockResolvedValueOnce({
      ...MINIMAL_STATS,
      quota: { memory_count: 7, memory_limit: null },
    });
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("Quota")).toBeTruthy());
    const count = screen.getByText("7");
    expect(count).toBeTruthy();
    // The divider "/" shouldn't appear when there's no limit. React renders
    // "{count}{' / '}{limit}" as three separate text nodes, so querying for
    // the combined string always returns null regardless — assert against
    // the parent element's full textContent instead, which is a genuine
    // check that no slash exists alongside the count.
    expect(count.parentElement.textContent).not.toContain("/");
  });

  it("top-level empty state when user has no memories", async () => {
    api.getAccountStats.mockResolvedValueOnce({
      ...MINIMAL_STATS,
      quota: { memory_count: 0, memory_limit: 100 },
    });
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("No data yet")).toBeTruthy());
    // Graph cards should NOT render in the empty-shell state.
    expect(screen.queryByText("Activity heatmap")).toBeNull();
  });

  it("re-fetches with new window when a window button is clicked", async () => {
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("Activity heatmap")).toBeTruthy());
    expect(api.getAccountStats).toHaveBeenLastCalledWith("90");
    await act(async () => {
      fireEvent.click(screen.getByText("Last 30 days"));
    });
    await waitFor(() =>
      expect(api.getAccountStats).toHaveBeenLastCalledWith("30"),
    );
  });

  it("shows error banner when API call fails", async () => {
    api.getAccountStats.mockRejectedValueOnce(new Error("boom"));
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("boom")).toBeTruthy());
    // No graph cards rendered in the error branch.
    expect(screen.queryByText("Activity heatmap")).toBeNull();
  });

  it("renders empty card body for activity_heatmap when all counts are zero", async () => {
    api.getAccountStats.mockResolvedValueOnce({
      ...MINIMAL_STATS,
      activity_heatmap: MINIMAL_STATS.activity_heatmap.map((d) => ({
        ...d,
        count: 0,
      })),
    });
    await act(async () => render(<Stats />));
    await waitFor(() => expect(screen.getByText("Activity heatmap")).toBeTruthy());
    expect(screen.getByText("No activity in this window yet.")).toBeTruthy();
  });
});

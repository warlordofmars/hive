// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard.jsx";

// Recharts renders SVG; jsdom doesn't support ResizeObserver
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

vi.mock("../api.js", () => ({
  api: {
    getStats: vi.fn(),
    getMetrics: vi.fn(),
    getCosts: vi.fn(),
  },
}));

import { api } from "../api.js";
import { formatCostTick, formatCostTooltip, CustomTooltip, CustomCostTooltip } from "./Dashboard.jsx";

const STATS = {
  total_memories: 42,
  total_clients: 3,
  total_users: 7,
  events_today: 10,
  events_last_7_days: 88,
};

const METRICS = {
  period: "24h",
  environment: "test",
  metrics: {
    inv_remember: { timestamps: ["2026-04-01T12:00:00Z"], values: [5] },
    err_remember: { timestamps: ["2026-04-01T12:00:00Z"], values: [1] },
    p99_remember: { timestamps: ["2026-04-01T12:00:00Z"], values: [120] },
    inv_recall: { timestamps: [], values: [] },
    err_recall: { timestamps: [], values: [] },
    p99_recall: { timestamps: [], values: [] },
    inv_forget: { timestamps: [], values: [] },
    err_forget: { timestamps: [], values: [] },
    p99_forget: { timestamps: [], values: [] },
    inv_listmemories: { timestamps: [], values: [] },
    err_listmemories: { timestamps: [], values: [] },
    p99_listmemories: { timestamps: [], values: [] },
    inv_summarizecontext: { timestamps: [], values: [] },
    err_summarizecontext: { timestamps: [], values: [] },
    p99_summarizecontext: { timestamps: [], values: [] },
    inv_searchmemories: { timestamps: [], values: [] },
    err_searchmemories: { timestamps: [], values: [] },
    p99_searchmemories: { timestamps: [], values: [] },
    tokens_issued: { timestamps: ["2026-04-01T12:00:00Z"], values: [7] },
    token_failures: { timestamps: ["2026-04-01T12:00:00Z"], values: [2] },
  },
};

const COSTS = {
  environment: "dev",
  currency: "USD",
  note: "Cost data lags ~24 h. Cached for 24 h.",
  monthly: [
    {
      period: "2026-03-01",
      total: 0.62,
      by_service: { "AWS Lambda": 0.5, "Amazon DynamoDB": 0.12 },
    },
  ],
  daily: [
    { date: "2026-04-01", total: 0.02 },
    { date: "2026-04-02", total: 0.03 },
  ],
};

describe("CustomTooltip", () => {
  it("returns null when not active", () => {
    const { container } = render(<CustomTooltip active={false} payload={[]} label="x" />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null when payload is empty", () => {
    const { container } = render(<CustomTooltip active={true} payload={[]} label="x" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders label and payload entries when active", () => {
    const payload = [{ dataKey: "remember", value: 5, color: "#e8a020" }];
    render(<CustomTooltip active={true} payload={payload} label="2026-04-01 12:00" />);
    expect(screen.getByText("2026-04-01 12:00")).toBeTruthy();
    expect(screen.getByText("remember:")).toBeTruthy();
    expect(screen.getByText("5")).toBeTruthy();
  });
});

describe("CustomCostTooltip", () => {
  it("returns null when not active", () => {
    const { container } = render(<CustomCostTooltip active={false} payload={[]} label="x" />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null when payload is empty", () => {
    const { container } = render(<CustomCostTooltip active={true} payload={[]} label="x" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders label and formatted cost entries when active", () => {
    const payload = [{ dataKey: "AWS Lambda", value: 0.5, color: "#1a1a2e" }];
    render(<CustomCostTooltip active={true} payload={payload} label="2026-03" />);
    expect(screen.getByText("2026-03")).toBeTruthy();
    expect(screen.getByText("AWS Lambda:")).toBeTruthy();
    expect(screen.getByText("$0.5000")).toBeTruthy();
  });
});

describe("formatters", () => {
  it("formatCostTick formats to 2 decimal places with $", () => {
    expect(formatCostTick(1.5)).toBe("$1.50");
    expect(formatCostTick(0)).toBe("$0.00");
  });

  it("formatCostTooltip formats to 4 decimal places with $", () => {
    expect(formatCostTooltip(0.1234)).toBe("$0.1234");
    expect(formatCostTooltip("0.5")).toBe("$0.5000");
  });
});

describe("Dashboard", () => {
  beforeEach(() => {
    api.getStats.mockResolvedValue(STATS);
    api.getMetrics.mockResolvedValue(METRICS);
    api.getCosts.mockResolvedValue(COSTS);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders the Dashboard heading", async () => {
    await act(async () => render(<Dashboard />));
    expect(screen.getByText("Dashboard")).toBeTruthy();
  });

  it("renders period selector buttons including 30d", async () => {
    await act(async () => render(<Dashboard />));
    expect(screen.getByText("1h")).toBeTruthy();
    expect(screen.getByText("24h")).toBeTruthy();
    expect(screen.getByText("7d")).toBeTruthy();
    expect(screen.getByText("30d")).toBeTruthy();
  });

  it("selected period button has orange background", async () => {
    await act(async () => render(<Dashboard />));
    const btn = screen.getByText("24h");
    expect(btn.style.background).toBe("rgb(232, 160, 32)");
  });

  it("renders summary stat cards after load", async () => {
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText("42")).toBeTruthy());
    expect(screen.getByText("Total Memories")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getByText("Total Clients")).toBeTruthy();
    expect(screen.getByText("10")).toBeTruthy();
    expect(screen.getByText("Events Today")).toBeTruthy();
    expect(screen.getByText("88")).toBeTruthy();
    expect(screen.getByText("Events (7d)")).toBeTruthy();
  });

  it("renders Total Users stat card from stats.total_users", async () => {
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText("Total Users")).toBeTruthy());
    // total_users = 7 appears multiple times (also tokens_issued); confirm at least one
    expect(screen.getAllByText("7").length).toBeGreaterThanOrEqual(1);
  });

  it("renders — for Total Users when total_users is null", async () => {
    api.getStats.mockResolvedValue({ ...STATS, total_users: null });
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText("Total Users")).toBeTruthy());
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("renders MTD cost stat card", async () => {
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText("AWS Cost (MTD)")).toBeTruthy());
    expect(screen.getByText("$0.62")).toBeTruthy();
  });

  it("does not render MTD cost card when no cost data", async () => {
    api.getCosts.mockResolvedValue({ environment: "dev", currency: "USD", note: "x", monthly: [], daily: [] });
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.queryByText("AWS Cost (MTD)")).toBeFalsy());
  });

  it("renders section headers", async () => {
    await act(async () => render(<Dashboard />));
    expect(screen.getByText("Tool Invocations")).toBeTruthy();
    expect(screen.getByText("Tool Latency p99 (ms)")).toBeTruthy();
    expect(screen.getByText("Auth Events")).toBeTruthy();
    expect(screen.getByText("Daily AWS Spend (Last 30 Days)")).toBeTruthy();
    expect(screen.getByText("Monthly AWS Spend")).toBeTruthy();
  });

  it("renders auth stat cards from metric data", async () => {
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText("Tokens Issued")).toBeTruthy());
    expect(screen.getByText("Validation Failures")).toBeTruthy();
  });

  it("renders cost note", async () => {
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText(/Cost data lags/)).toBeTruthy());
  });

  it("shows last refreshed time after load", async () => {
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getByText(/Checked at/)).toBeTruthy());
  });

  it("switches period when a period button is clicked", async () => {
    await act(async () => render(<Dashboard />));
    fireEvent.click(screen.getByText("1h"));
    await waitFor(() => expect(api.getMetrics).toHaveBeenCalledWith("1h"));
  });

  it("clicking 7d calls getMetrics with 7d", async () => {
    await act(async () => render(<Dashboard />));
    fireEvent.click(screen.getByText("7d"));
    await waitFor(() => expect(api.getMetrics).toHaveBeenCalledWith("7d"));
  });

  it("clicking 30d calls getMetrics with 30d", async () => {
    await act(async () => render(<Dashboard />));
    fireEvent.click(screen.getByText("30d"));
    await waitFor(() => expect(api.getMetrics).toHaveBeenCalledWith("30d"));
  });

  it("clicking Refresh reloads all data", async () => {
    await act(async () => render(<Dashboard />));
    const count = api.getStats.mock.calls.length;
    fireEvent.click(screen.getByText("Refresh"));
    await waitFor(() => expect(api.getStats.mock.calls.length).toBeGreaterThan(count));
  });

  it("auto-refreshes after 60 seconds", async () => {
    vi.useFakeTimers();
    await act(async () => render(<Dashboard />));
    const count = api.getStats.mock.calls.length;
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(api.getStats.mock.calls.length).toBeGreaterThan(count);
    vi.useRealTimers();
  });

  it("shows empty state when no invocation data", async () => {
    api.getMetrics.mockResolvedValue({ period: "24h", environment: "test", metrics: {} });
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("No invocation data for this period.")).toBeTruthy()
    );
    expect(screen.getByText("No latency data for this period.")).toBeTruthy();
  });

  it("shows empty state when no monthly cost data", async () => {
    api.getCosts.mockResolvedValue({
      environment: "dev",
      currency: "USD",
      note: "Cost data lags ~24 h.",
      monthly: [],
      daily: [],
    });
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("No cost data available yet.")).toBeTruthy()
    );
  });

  it("shows empty state when no daily cost data", async () => {
    api.getCosts.mockResolvedValue({
      environment: "dev",
      currency: "USD",
      note: "Cost data lags ~24 h.",
      monthly: [{ period: "2026-03-01", total: 0.62, by_service: { "AWS Lambda": 0.62 } }],
      daily: [],
    });
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("No daily cost data available yet.")).toBeTruthy()
    );
  });

  it("shows metrics error banner when getMetrics rejects", async () => {
    api.getMetrics.mockRejectedValue(new Error("CloudWatch unavailable"));
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("CloudWatch unavailable")).toBeTruthy()
    );
  });

  it("shows costs error banner when getCosts rejects", async () => {
    api.getCosts.mockRejectedValue(new Error("Cost Explorer unavailable"));
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("Cost Explorer unavailable")).toBeTruthy()
    );
  });

  it("handles getMetrics rejection with no message", async () => {
    api.getMetrics.mockRejectedValue({});
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("Failed to load metrics")).toBeTruthy()
    );
  });

  it("handles getCosts rejection with no message", async () => {
    api.getCosts.mockRejectedValue({});
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("Failed to load costs")).toBeTruthy()
    );
  });

  it("renders loading indicator during fetch", async () => {
    let resolve;
    api.getStats.mockReturnValue(new Promise((r) => { resolve = r; }));
    api.getMetrics.mockReturnValue(new Promise(() => {}));
    api.getCosts.mockReturnValue(new Promise(() => {}));

    await act(async () => render(<Dashboard />));
    expect(screen.getByText("Loading…")).toBeTruthy();
    resolve(STATS);
  });

  it("renders dash for undefined StatCard value", async () => {
    api.getStats.mockResolvedValue({
      total_memories: null,
      total_clients: 3,
      total_users: null,
      events_today: 10,
      events_last_7_days: 88,
    });
    await act(async () => render(<Dashboard />));
    await waitFor(() => expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1));
  });

  it("handles metrics response missing metrics key", async () => {
    api.getMetrics.mockResolvedValue({ period: "24h", environment: "test" });
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("No invocation data for this period.")).toBeTruthy()
    );
  });

  it("handles costs response missing monthly key", async () => {
    api.getCosts.mockResolvedValue({ environment: "dev", currency: "USD", note: "Cost data lags ~24 h." });
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("No cost data available yet.")).toBeTruthy()
    );
  });

  it("handles costs response missing daily key", async () => {
    api.getCosts.mockResolvedValue({
      environment: "dev",
      currency: "USD",
      note: "Cost data lags ~24 h.",
      monthly: [{ period: "2026-03-01", total: 0.62, by_service: { "AWS Lambda": 0.62 } }],
    });
    await act(async () => render(<Dashboard />));
    await waitFor(() =>
      expect(screen.getByText("No daily cost data available yet.")).toBeTruthy()
    );
  });

  it("handles sparse values array (values[i] undefined)", async () => {
    api.getMetrics.mockResolvedValue({
      period: "24h",
      environment: "test",
      metrics: {
        inv_remember: { timestamps: ["2026-04-01T12:00:00Z", "2026-04-01T13:00:00Z"], values: [5] },
        p99_remember: { timestamps: ["2026-04-01T12:00:00Z", "2026-04-01T13:00:00Z"], values: [120] },
        tokens_issued: { timestamps: [], values: [] },
        token_failures: { timestamps: [], values: [] },
      },
    });
    await act(async () => render(<Dashboard />));
    expect(screen.getByText("Tool Invocations")).toBeTruthy();
  });
});

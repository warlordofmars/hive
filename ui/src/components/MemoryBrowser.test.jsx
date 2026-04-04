// Copyright (c) 2026 John Carter. All rights reserved.
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import MemoryBrowser from "./MemoryBrowser.jsx";

vi.mock("../api.js", () => ({
  api: {
    listMemories: vi.fn().mockResolvedValue([]),
  },
}));

describe("MemoryBrowser", () => {
  it("renders without crashing", () => {
    render(<MemoryBrowser />);
    expect(screen.getByText("Memories")).toBeTruthy();
  });

  it("renders the New button", () => {
    render(<MemoryBrowser />);
    expect(screen.getByText("+ New")).toBeTruthy();
  });

  it("renders empty state message after load", async () => {
    render(<MemoryBrowser />);
    expect(await screen.findByText("No memories found.")).toBeTruthy();
  });
});

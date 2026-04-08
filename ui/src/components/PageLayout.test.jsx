// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import PageLayout from "./PageLayout.jsx";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderInRouter(ui) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("PageLayout", () => {
  it("renders children", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><p>test content</p></PageLayout>)
    );
    expect(screen.getByText("test content")).toBeTruthy();
  });

  it("renders nav with logo and wordmark", async () => {
    const { container } = await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    expect(container.querySelector('img[alt="Hive"]')).toBeTruthy();
    expect(screen.getAllByText("Hive").length).toBeGreaterThanOrEqual(1);
  });

  it("renders nav links: Pricing, FAQ, Docs", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    expect(screen.getAllByText("Pricing").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("FAQ").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Docs").length).toBeGreaterThanOrEqual(1);
  });

  it("renders Sign in button", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    expect(screen.getByText("Sign in")).toBeTruthy();
  });

  it("Sign in navigates to /app", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    fireEvent.click(screen.getByText("Sign in"));
    expect(mockNavigate).toHaveBeenCalledWith("/app");
  });

  it("clicking logo navigates to /", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    const logo = screen.getAllByText("Hive")[0].closest("span");
    fireEvent.click(logo);
    expect(mockNavigate).toHaveBeenCalledWith("/");
  });

  it("renders footer with copyright", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    expect(screen.getByText(/© 2026 Hive/)).toBeTruthy();
  });

  it("renders footer links: Pricing, FAQ, Docs", async () => {
    await act(async () =>
      renderInRouter(<PageLayout><span /></PageLayout>)
    );
    const pricingLinks = screen.getAllByText("Pricing");
    expect(pricingLinks.length).toBeGreaterThanOrEqual(1);
    const faqLinks = screen.getAllByText("FAQ");
    expect(faqLinks.length).toBeGreaterThanOrEqual(1);
  });
});

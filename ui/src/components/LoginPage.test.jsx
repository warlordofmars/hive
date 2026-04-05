// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import LoginPage from "./LoginPage.jsx";

describe("LoginPage", () => {
  beforeEach(() => {
    vi.stubGlobal("location", {
      ...window.location,
      href: "",
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the Hive heading and sign-in button", async () => {
    await act(async () => render(<LoginPage />));
    expect(screen.getByText("Hive")).toBeTruthy();
    expect(screen.getByText("Sign in with Google")).toBeTruthy();
  });

  it("renders the tagline", async () => {
    await act(async () => render(<LoginPage />));
    expect(screen.getByText(/Shared persistent memory/)).toBeTruthy();
  });

  it("redirects to /auth/login when button is clicked", async () => {
    await act(async () => render(<LoginPage />));
    fireEvent.click(screen.getByText("Sign in with Google"));
    expect(window.location.href).toBe("/auth/login");
  });
});

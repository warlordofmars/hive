// Copyright (c) 2026 John Carter. All rights reserved.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AlertDialog } from "./alert-dialog.jsx";

// Capture the latest onOpenChange handler the component passes to Dialog.Root
// so a test can drive both the open (isOpen=true) and close (isOpen=false)
// branches of the inline handler directly. The real Radix Root is preserved.
const captured = { onOpenChange: undefined };
vi.mock("@radix-ui/react-dialog", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    Root: (props) => {
      captured.onOpenChange = props.onOpenChange;
      return actual.Root(props);
    },
  };
});

describe("AlertDialog", () => {
  it("renders title and description when open", () => {
    render(
      <AlertDialog
        open
        title="Delete item?"
        description="This cannot be undone."
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("Delete item?")).toBeTruthy();
    expect(screen.getByText("This cannot be undone.")).toBeTruthy();
  });

  it("does not render when closed", () => {
    render(
      <AlertDialog
        open={false}
        title="Delete item?"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.queryByText("Delete item?")).toBeNull();
  });

  it("calls onConfirm when confirm button clicked", async () => {
    const onConfirm = vi.fn();
    render(
      <AlertDialog
        open
        title="Sure?"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />,
    );
    await act(async () => fireEvent.click(screen.getByText("Delete")));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("calls onCancel when cancel button clicked", async () => {
    const onCancel = vi.fn();
    render(
      <AlertDialog
        open
        title="Sure?"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    );
    await act(async () => fireEvent.click(screen.getByText("Cancel")));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("renders custom button labels", () => {
    render(
      <AlertDialog
        open
        title="Confirm"
        confirmLabel="Yes, proceed"
        cancelLabel="No thanks"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByText("Yes, proceed")).toBeTruthy();
    expect(screen.getByText("No thanks")).toBeTruthy();
  });

  it("renders without description", () => {
    render(
      <AlertDialog open title="Confirm" onConfirm={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText("Confirm")).toBeTruthy();
  });

  it("calls onCancel when Escape key pressed (onOpenChange path)", async () => {
    const onCancel = vi.fn();
    render(
      <AlertDialog open title="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );
    expect(screen.getByText("Sure?")).toBeTruthy();
    // Radix Dialog listens for Escape on the document and fires onOpenChange(false)
    await act(async () => fireEvent.keyDown(document, { key: "Escape" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("does not call onCancel when onOpenChange fires with isOpen=true", () => {
    // Radix fires onOpenChange(true) when the dialog opens. The component's
    // handler only calls onCancel on close (isOpen=false), so the open path
    // (the `if (!isOpen)` false branch) must NOT invoke onCancel.
    const onCancel = vi.fn();
    render(
      <AlertDialog open title="Sure?" onConfirm={vi.fn()} onCancel={onCancel} />,
    );

    // Open path: isOpen=true → onCancel not called.
    act(() => captured.onOpenChange(true));
    expect(onCancel).not.toHaveBeenCalled();

    // Close path: isOpen=false → onCancel called.
    act(() => captured.onOpenChange(false));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("merges extra className on content", () => {
    render(
      <AlertDialog
        open
        title="Test"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        className="my-extra"
      />,
    );
    const content = screen.getByText("Test").closest("[class*='my-extra']");
    expect(content).toBeTruthy();
  });
});

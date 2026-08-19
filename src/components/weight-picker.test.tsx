import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WeightWheel } from "./weight-picker";

// The wheel is driven by scroll position in a real browser, which jsdom has no
// layout to produce. These tests exercise the other two paths into the same
// onChange — clicking a row and the arrow keys — which is where the value
// arithmetic lives. Snapping itself is left to an end-to-end suite.

function renderWheel(value: number, options: { disabled?: boolean } = {}) {
  const onChange = vi.fn();
  render(<WeightWheel value={value} onChange={onChange} disabled={options.disabled ?? false} />);
  return { onChange };
}

/** The listbox for whole kilograms or for the decimal fraction. */
function column(name: "Kilograms" | "Decimal fraction of a kilogram") {
  return screen.getByRole("listbox", { name });
}

describe("WeightWheel", () => {
  it("announces the current value to screen readers", () => {
    renderWheel(82.4);
    expect(screen.getByText("82.4 kilograms")).toBeInTheDocument();
  });

  it("marks the whole and decimal parts of the value as selected", () => {
    renderWheel(82.4);

    expect(within(column("Kilograms")).getByRole("option", { selected: true })).toHaveTextContent(
      "82",
    );
    expect(
      within(column("Decimal fraction of a kilogram")).getByRole("option", { selected: true }),
    ).toHaveTextContent("4");
  });

  // Guards the rounding in WeightWheel: (82.3 - 82) * 10 is 2.9999…, which
  // truncated would select the wrong decimal row.
  it("selects the right decimal row for a value with floating-point error", () => {
    renderWheel(82.3);

    expect(
      within(column("Decimal fraction of a kilogram")).getByRole("option", { selected: true }),
    ).toHaveTextContent("3");
  });

  it("reports a new whole number while keeping the decimal", async () => {
    const user = userEvent.setup();
    const { onChange } = renderWheel(82.4);

    await user.click(within(column("Kilograms")).getByRole("option", { name: "85" }));

    expect(onChange).toHaveBeenCalledWith(85.4);
  });

  it("reports a new decimal while keeping the whole number", async () => {
    const user = userEvent.setup();
    const { onChange } = renderWheel(82.4);

    await user.click(
      within(column("Decimal fraction of a kilogram")).getByRole("option", { name: "7" }),
    );

    expect(onChange).toHaveBeenCalledWith(82.7);
  });

  describe("keyboard", () => {
    it("steps the whole column down with ArrowDown", async () => {
      const user = userEvent.setup();
      const { onChange } = renderWheel(82.4);

      column("Kilograms").focus();
      await user.keyboard("{ArrowDown}");

      expect(onChange).toHaveBeenCalledWith(83.4);
    });

    it("steps the whole column up with ArrowUp", async () => {
      const user = userEvent.setup();
      const { onChange } = renderWheel(82.4);

      column("Kilograms").focus();
      await user.keyboard("{ArrowUp}");

      expect(onChange).toHaveBeenCalledWith(81.4);
    });

    it("steps the decimal column", async () => {
      const user = userEvent.setup();
      const { onChange } = renderWheel(82.4);

      column("Decimal fraction of a kilogram").focus();
      await user.keyboard("{ArrowDown}");

      expect(onChange).toHaveBeenCalledWith(82.5);
    });

    // At either end the index is clamped, so the value does not move. Note that
    // onChange still fires, with the unchanged value — step() has no
    // "did it actually change" guard, where handleScroll does. Harmless (the
    // parent sets identical state) but inconsistent; see docs/backlog.md.
    it("does not move past the top of a column", async () => {
      const user = userEvent.setup();
      // 20 kg is the first whole value offered.
      const { onChange } = renderWheel(20.4);

      column("Kilograms").focus();
      await user.keyboard("{ArrowUp}");

      expect(onChange).toHaveBeenCalledWith(20.4);
    });

    it("does not move past the bottom of a column", async () => {
      const user = userEvent.setup();
      const { onChange } = renderWheel(82.9);

      column("Decimal fraction of a kilogram").focus();
      await user.keyboard("{ArrowDown}");

      expect(onChange).toHaveBeenCalledWith(82.9);
    });
  });

  describe("when disabled", () => {
    it("reports nothing on a key press", async () => {
      const user = userEvent.setup();
      const { onChange } = renderWheel(82.4, { disabled: true });

      column("Kilograms").focus();
      await user.keyboard("{ArrowDown}");

      expect(onChange).not.toHaveBeenCalled();
    });

    it("marks the columns as disabled and removes them from the tab order", () => {
      renderWheel(82.4, { disabled: true });

      expect(column("Kilograms")).toHaveAttribute("aria-disabled", "true");
      expect(column("Kilograms")).toHaveAttribute("tabindex", "-1");
    });
  });
});

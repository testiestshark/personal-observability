import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WeightCalendar } from "./weight-calendar";
import type { DayWeight } from "@/lib/weight/weight.functions";

const AUGUST_DAYS: DayWeight[] = [
  { id: "entry-6", day: "2026-08-06", weightKg: 82.4 },
  { id: "entry-7", day: "2026-08-07", weightKg: 82.15 },
];

function renderCalendar(overrides: Partial<Parameters<typeof WeightCalendar>[0]> = {}) {
  const onMonthChange = vi.fn();
  const onDelete = vi.fn<(id: string) => Promise<string | null>>().mockResolvedValue(null);

  render(
    <WeightCalendar
      month="2026-08"
      days={AUGUST_DAYS}
      today="2026-08-07"
      onMonthChange={onMonthChange}
      onDelete={onDelete}
      {...overrides}
    />,
  );

  return { onMonthChange, onDelete };
}

/** Recorded days are the only interactive cells, so they are the buttons. */
function dayCells() {
  return screen.getAllByRole("button").filter((element) => {
    const label = element.getAttribute("aria-label") ?? "";
    return label.includes("kilograms");
  });
}

describe("WeightCalendar", () => {
  it("names the month being shown", () => {
    renderCalendar();
    expect(screen.getByRole("heading", { name: /August 2026/ })).toBeInTheDocument();
  });

  it("shows the weight recorded on each day, to one decimal place", () => {
    renderCalendar();

    expect(screen.getByText("82.4")).toBeInTheDocument();
    // 82.15 is stored at greater precision than the cell shows.
    expect(screen.getByText("82.2")).toBeInTheDocument();
  });

  it("makes only recorded days interactive", () => {
    renderCalendar();
    expect(dayCells()).toHaveLength(2);
  });

  it("labels a recorded day with its date and weight", () => {
    renderCalendar();

    expect(
      screen.getByRole("button", { name: /Thu.*06.*Aug.*2026.*82\.4 kilograms/ }),
    ).toBeInTheDocument();
  });

  describe("month grid", () => {
    // The grid renders one numbered cell per day, so counting the day numbers
    // checks the calendar arithmetic — including the leap-year case.
    function dayNumbersShown() {
      return screen.getAllByText(/^\d{1,2}$/).length;
    }

    it("renders 31 cells for a 31-day month", () => {
      renderCalendar();
      expect(dayNumbersShown()).toBe(31);
    });

    it("renders 28 cells for a non-leap February", () => {
      renderCalendar({ month: "2026-02", days: [], today: "2026-02-10" });
      expect(dayNumbersShown()).toBe(28);
    });

    it("renders 29 cells for a leap February", () => {
      renderCalendar({ month: "2028-02", days: [], today: "2028-02-10" });
      expect(dayNumbersShown()).toBe(29);
    });

    it("renders 30 cells for a 30-day month", () => {
      renderCalendar({ month: "2026-09", days: [], today: "2026-09-10" });
      expect(dayNumbersShown()).toBe(30);
    });
  });

  describe("navigation", () => {
    it("moves to the previous month", async () => {
      const user = userEvent.setup();
      const { onMonthChange } = renderCalendar();

      await user.click(screen.getByRole("button", { name: "Previous month" }));

      expect(onMonthChange).toHaveBeenCalledWith("2026-07");
    });

    it("moves to the next month", async () => {
      const user = userEvent.setup();
      const { onMonthChange } = renderCalendar();

      await user.click(screen.getByRole("button", { name: "Next month" }));

      expect(onMonthChange).toHaveBeenCalledWith("2026-09");
    });

    it("blocks forward navigation when the caller disallows it", () => {
      renderCalendar({ canGoForward: false });
      expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
    });
  });

  describe("deleting a weigh-in", () => {
    /** Open a recorded day and click through to the confirmation dialog. */
    async function openConfirmation(user: ReturnType<typeof userEvent.setup>) {
      await user.click(screen.getByRole("button", { name: /06.*Aug.*2026/ }));
      await user.click(await screen.findByRole("button", { name: "Delete" }));
      return screen.findByRole("alertdialog");
    }

    it("shows the day's details when a recorded day is opened", async () => {
      const user = userEvent.setup();
      renderCalendar();

      await user.click(screen.getByRole("button", { name: /06.*Aug.*2026/ }));

      expect(await screen.findByText("82.4 kg")).toBeInTheDocument();
    });

    it("asks for confirmation before deleting", async () => {
      const user = userEvent.setup();
      renderCalendar();

      const dialog = await openConfirmation(user);

      expect(dialog).toHaveTextContent(/permanently deleted/);
      expect(dialog).toHaveTextContent(/82\.4 kg/);
    });

    it("does not delete anything until the dialog is confirmed", async () => {
      const user = userEvent.setup();
      const { onDelete } = renderCalendar();

      await openConfirmation(user);

      expect(onDelete).not.toHaveBeenCalled();
    });

    it("deletes the entry that was opened", async () => {
      const user = userEvent.setup();
      const { onDelete } = renderCalendar();

      const dialog = await openConfirmation(user);
      await user.click(within(dialog).getByRole("button", { name: "Delete" }));

      await waitFor(() => expect(onDelete).toHaveBeenCalledWith("entry-6"));
    });

    it("keeps the dialog open and shows the message when the delete fails", async () => {
      const user = userEvent.setup();
      const onDelete = vi
        .fn<(id: string) => Promise<string | null>>()
        .mockResolvedValue("Could not reach the server.");
      renderCalendar({ onDelete });

      const dialog = await openConfirmation(user);
      await user.click(within(dialog).getByRole("button", { name: "Delete" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the server.");
      expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    });

    it("closes the dialog once the delete succeeds", async () => {
      const user = userEvent.setup();
      renderCalendar();

      const dialog = await openConfirmation(user);
      await user.click(within(dialog).getByRole("button", { name: "Delete" }));

      await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    });

    it("abandons the delete when cancelled", async () => {
      const user = userEvent.setup();
      const { onDelete } = renderCalendar();

      const dialog = await openConfirmation(user);
      await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

      await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
      expect(onDelete).not.toHaveBeenCalled();
    });
  });
});

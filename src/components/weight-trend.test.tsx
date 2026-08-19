// Smoke tests only. jsdom has no layout engine, so recharts' ResponsiveContainer
// measures zero and draws nothing — the SVG cannot be asserted against here (see
// docs/TESTING.md § jsdom's limits). What these cover is that the component mounts
// without throwing and that the text around the chart, which is plain DOM, is right.
// The arithmetic behind it is tested directly in lib/weight/trend.test.ts.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WeightTrend } from "./weight-trend";
import type { WeightEntry } from "@/lib/weight/weight.functions";

function entry(day: string, weightKg: number): WeightEntry {
  return {
    id: day,
    recordedAt: `${day}T12:00:00.000Z`,
    weightKg,
    unit: "kg",
  };
}

/** A fortnight of daily readings, drifting down from 84 to 82.7. */
function fortnight(): WeightEntry[] {
  return Array.from({ length: 14 }, (_, i) =>
    entry(`2026-08-${String(i + 1).padStart(2, "0")}`, 84 - i * 0.1),
  );
}

describe("WeightTrend", () => {
  it("renders a summary from a run of readings", () => {
    render(<WeightTrend entries={fortnight()} />);

    expect(screen.getByRole("heading", { name: "Trend" })).toBeInTheDocument();
    expect(screen.getByText("14 readings over 14 days")).toBeInTheDocument();
  });

  it("reports a fall as a downward change", () => {
    // A flat week at 84 then a flat week at 82, so the first and last 7-day
    // averages are exactly 84.0 and 82.0 and the change cannot be a rounding
    // artefact of the fixture.
    const stepped = Array.from({ length: 14 }, (_, i) =>
      entry(`2026-08-${String(i + 1).padStart(2, "0")}`, i < 7 ? 84 : 82),
    );

    render(<WeightTrend entries={stepped} />);

    expect(screen.getByText(/↓ 2\.0 kg/)).toBeInTheDocument();
  });

  it("calls a flat run steady rather than inventing a direction", () => {
    const flat = Array.from({ length: 10 }, (_, i) =>
      entry(`2026-08-${String(i + 1).padStart(2, "0")}`, 82.4),
    );

    render(<WeightTrend entries={flat} />);

    expect(screen.getByText("Holding steady")).toBeInTheDocument();
  });

  it("says so rather than drawing a chart of one point", () => {
    render(<WeightTrend entries={[entry("2026-08-01", 82.4)]} />);

    expect(screen.getByText(/One reading so far/)).toBeInTheDocument();
  });

  it("has something to say with no readings at all", () => {
    render(<WeightTrend entries={[]} />);

    expect(screen.getByText(/Nothing recorded in this range yet/)).toBeInTheDocument();
  });

  it("narrows the summary when a shorter range is picked", async () => {
    const user = userEvent.setup();
    render(<WeightTrend entries={fortnight()} />);

    expect(screen.getByText("14 readings over 14 days")).toBeInTheDocument();

    // 30d still covers the whole fortnight; the point is that the control works
    // and the summary recomputes rather than going stale.
    await user.click(screen.getByRole("button", { name: "30d" }));

    expect(screen.getByRole("button", { name: "30d" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("14 readings over 14 days")).toBeInTheDocument();
  });

  it("defaults to 90 days", () => {
    render(<WeightTrend entries={fortnight()} />);

    expect(screen.getByRole("button", { name: "90d" })).toHaveAttribute("aria-pressed", "true");
  });
});

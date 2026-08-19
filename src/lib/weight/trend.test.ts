import { describe, expect, it } from "vitest";

import {
  buildTrend,
  dailySeries,
  summarise,
  withinRange,
  withMovingAverage,
  type DayPoint,
} from "./trend";

/** Weigh-ins are stored at noon UTC (see londonDayToInstant), so tests match that. */
function entry(day: string, weightKg: number, time = "12:00:00") {
  return { recordedAt: `${day}T${time}.000Z`, weightKg };
}

function points(...pairs: [string, number][]): DayPoint[] {
  return pairs.map(([day, weightKg]) => ({ day, weightKg }));
}

describe("dailySeries", () => {
  it("returns one point per day, oldest first", () => {
    const series = dailySeries([
      entry("2026-08-03", 82.4),
      entry("2026-08-01", 83.0),
      entry("2026-08-02", 82.7),
    ]);

    expect(series).toEqual(
      points(["2026-08-01", 83.0], ["2026-08-02", 82.7], ["2026-08-03", 82.4]),
    );
  });

  it("keeps the earliest reading when a day has several", () => {
    const series = dailySeries([
      entry("2026-08-01", 84.0, "19:00:00"),
      entry("2026-08-01", 82.5, "07:00:00"),
      entry("2026-08-01", 83.2, "13:00:00"),
    ]);

    // The morning one, matching what the calendar shows for that day.
    expect(series).toEqual(points(["2026-08-01", 82.5]));
  });

  it("buckets by London day, not UTC day", () => {
    // 23:30 UTC on 10 August is already 00:30 on the 11th in London (BST).
    const series = dailySeries([entry("2026-08-10", 82.4, "23:30:00")]);

    expect(series[0]?.day).toBe("2026-08-11");
  });

  it("has nothing to say about no entries", () => {
    expect(dailySeries([])).toEqual([]);
  });
});

describe("withMovingAverage", () => {
  it("averages over the trailing window", () => {
    const result = withMovingAverage(
      points(["2026-08-01", 84.0], ["2026-08-02", 82.0], ["2026-08-03", 83.0]),
      7,
    );

    expect(result[0]?.averageKg).toBeNull(); // one reading is not an average
    expect(result[1]?.averageKg).toBe(83.0); // (84 + 82) / 2
    expect(result[2]?.averageKg).toBe(83.0); // (84 + 82 + 83) / 3
  });

  it("drops readings that fall out of the window", () => {
    // A 3-day window on four consecutive days: the last average must exclude day 1.
    const result = withMovingAverage(
      points(
        ["2026-08-01", 90.0],
        ["2026-08-02", 80.0],
        ["2026-08-03", 80.0],
        ["2026-08-04", 80.0],
      ),
      3,
    );

    expect(result[3]?.averageKg).toBe(80.0);
  });

  // The point of averaging over calendar days rather than over readings. Two
  // readings a month apart are not a 7-day average of anything.
  it("does not reach across a gap longer than the window", () => {
    const result = withMovingAverage(points(["2026-08-01", 84.0], ["2026-09-15", 80.0]), 7);

    expect(result[1]?.averageKg).toBeNull();
  });

  it("counts the window in days, so a sparse week still averages", () => {
    // Three readings inside seven days, with days missing between them.
    const result = withMovingAverage(
      points(["2026-08-01", 84.0], ["2026-08-04", 83.0], ["2026-08-07", 82.0]),
      7,
    );

    expect(result[2]?.averageKg).toBe(83.0); // (84 + 83 + 82) / 3
  });

  it("treats the window edge as inclusive", () => {
    // Exactly 7 days apart: 1 Aug is the oldest day a window ending 7 Aug covers.
    const result = withMovingAverage(points(["2026-08-01", 84.0], ["2026-08-07", 82.0]), 7);
    expect(result[1]?.averageKg).toBe(83.0);

    // One day further out and it falls off.
    const beyond = withMovingAverage(points(["2026-08-01", 84.0], ["2026-08-08", 82.0]), 7);
    expect(beyond[1]?.averageKg).toBeNull();
  });

  // Day arithmetic done through a timezone would make this span 24.04 days.
  it("is not disturbed by a DST boundary", () => {
    // BST ends on 25 October 2026.
    const result = withMovingAverage(points(["2026-10-24", 84.0], ["2026-10-26", 82.0]), 7);

    expect(result[1]?.averageKg).toBe(83.0);
  });
});

describe("withinRange", () => {
  const series = withMovingAverage(
    points(["2026-08-01", 84.0], ["2026-08-08", 83.0], ["2026-08-15", 82.0]),
  );

  it("counts back from the newest reading, not from today", () => {
    const ranged = withinRange(series, 8);

    expect(ranged.map((point) => point.day)).toEqual(["2026-08-08", "2026-08-15"]);
  });

  it("keeps everything when the range is null", () => {
    expect(withinRange(series, null)).toHaveLength(3);
  });

  it("survives an empty series", () => {
    expect(withinRange([], 30)).toEqual([]);
  });
});

describe("summarise", () => {
  it("reports the change average-to-average", () => {
    const series = withMovingAverage(
      points(
        ["2026-08-01", 84.0],
        ["2026-08-02", 84.0],
        ["2026-08-03", 82.0],
        ["2026-08-04", 82.0],
      ),
      2,
    );

    const summary = summarise(series);

    expect(summary?.latestKg).toBe(82.0);
    expect(summary?.latestAverageKg).toBe(82.0);
    expect(summary?.changeKg).toBe(-2.0); // 82 - 84
    expect(summary?.count).toBe(4);
    expect(summary?.spanDays).toBe(4);
  });

  it("reports no change from a single reading", () => {
    const summary = summarise(withMovingAverage(points(["2026-08-01", 82.4])));

    expect(summary?.latestKg).toBe(82.4);
    expect(summary?.latestAverageKg).toBeNull();
    expect(summary?.changeKg).toBeNull();
    expect(summary?.spanDays).toBe(1);
  });

  it("has nothing to summarise from nothing", () => {
    expect(summarise([])).toBeNull();
  });
});

describe("buildTrend", () => {
  it("averages across the full history before cutting to the range", () => {
    // Readings on eight consecutive days, asking for the last two.
    const entries = [
      entry("2026-08-01", 84.0),
      entry("2026-08-02", 84.0),
      entry("2026-08-03", 84.0),
      entry("2026-08-04", 84.0),
      entry("2026-08-05", 84.0),
      entry("2026-08-06", 84.0),
      entry("2026-08-07", 84.0),
      entry("2026-08-08", 84.0),
    ];

    const { points: shown } = buildTrend(entries, { rangeDays: 2 });

    expect(shown).toHaveLength(2);
    // Both carry a settled average — the range cut did not restart the smoothing.
    expect(shown[0]?.averageKg).toBe(84.0);
    expect(shown[1]?.averageKg).toBe(84.0);
  });

  it("takes unsorted entries", () => {
    const { points: shown } = buildTrend([entry("2026-08-03", 82.0), entry("2026-08-01", 84.0)]);

    expect(shown.map((point) => point.day)).toEqual(["2026-08-01", "2026-08-03"]);
  });

  it("returns an empty result for no entries", () => {
    expect(buildTrend([])).toEqual({ points: [], summary: null });
  });
});

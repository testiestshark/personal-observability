import { describe, expect, it } from "vitest";

import { formatActivityTime, formatActivityType } from "./format";
import {
  formatAveragePace,
  formatAverageSpeed,
  garminActivityHeader,
  isFootActivity,
} from "./garmin-activity";
import type { GarminActivityDetail } from "./health.functions";

const run: GarminActivityDetail = {
  id: "0d6c4d0e-8a43-4f8e-9d0a-2f1a8c3f4b77",
  source: "garmin",
  name: "Morning Run",
  type: "running",
  localDay: "2026-10-09",
  startedAt: "2026-10-09T06:30:00Z",
  durationSeconds: 1_800,
  distanceMeters: 5_000,
  caloriesKcal: 340,
  averageHeartRateBpm: 152,
  totalSets: null,
  totalReps: null,
};

describe("isFootActivity", () => {
  it.each(["running", "trail_running", "treadmill_running", "walking", "hiking", "casual_walking"])(
    "treats %s as a foot activity, which is read as pace",
    (type) => {
      expect(isFootActivity(type)).toBe(true);
    },
  );

  it.each(["cycling", "indoor_cycling", "lap_swimming", "yoga", "strength_training"])(
    "treats %s as not a foot activity, which is read as speed",
    (type) => {
      expect(isFootActivity(type)).toBe(false);
    },
  );
});

describe("formatAveragePace", () => {
  it("is duration over distance, in minutes and seconds per km", () => {
    // 1 800 s over 5 km is 360 s per km.
    expect(formatAveragePace(1_800, 5_000)).toBe("6:00 /km");
    expect(formatAveragePace(1_650, 5_000)).toBe("5:30 /km");
  });

  it("pads seconds to two digits", () => {
    expect(formatAveragePace(1_525, 5_000)).toBe("5:05 /km");
  });

  it("carries a rounded-up sixty seconds into the minute rather than showing 5:60", () => {
    // 359.6 s per km rounds to 360 s, which is 6:00.
    expect(formatAveragePace(1_798, 5_000)).toBe("6:00 /km");
  });

  it("is a dash under 100 m, the same threshold as the day card", () => {
    expect(formatAveragePace(600, 99)).toBe("—");
    expect(formatAveragePace(600, 0)).toBe("—");
  });

  it("is shown at exactly 100 m", () => {
    expect(formatAveragePace(36, 100)).toBe("6:00 /km");
  });

  it("is a dash when distance or duration is missing", () => {
    expect(formatAveragePace(1_800, null)).toBe("—");
    expect(formatAveragePace(null, 5_000)).toBe("—");
  });

  it("is a dash for a zero duration rather than a 0:00 pace", () => {
    expect(formatAveragePace(0, 5_000)).toBe("—");
  });
});

describe("formatAverageSpeed", () => {
  it("is distance over duration, in km/h to one decimal", () => {
    // 20 km in 1 h.
    expect(formatAverageSpeed(3_600, 20_000)).toBe("20.0 km/h");
    // 10 km in 40 min is 15 km/h.
    expect(formatAverageSpeed(2_400, 10_000)).toBe("15.0 km/h");
  });

  it("is a dash under 100 m, the same threshold as pace", () => {
    expect(formatAverageSpeed(600, 99)).toBe("—");
  });

  it("is a dash when distance or duration is missing or zero", () => {
    expect(formatAverageSpeed(null, 10_000)).toBe("—");
    expect(formatAverageSpeed(3_600, null)).toBe("—");
    expect(formatAverageSpeed(0, 10_000)).toBe("—");
  });
});

describe("garminActivityHeader", () => {
  it("titles the page with the activity name", () => {
    expect(garminActivityHeader(run).title).toBe("Morning Run");
  });

  it("falls back to the humanised type when the name is missing or blank", () => {
    expect(garminActivityHeader({ ...run, name: null }).title).toBe(formatActivityType("running"));
    expect(garminActivityHeader({ ...run, name: "   " }).title).toBe(formatActivityType("running"));
  });

  it("takes the day from the stored local_day, so the back link lands where the card was listed", () => {
    // 23:30 UTC in BST is 00:30 the next London day; the stored day wins.
    const late = { ...run, startedAt: "2026-07-01T23:30:00Z", localDay: "2026-07-02" };
    expect(garminActivityHeader(late).localDay).toBe("2026-07-02");
  });

  it("shows the London start time, as the Workout page does", () => {
    expect(garminActivityHeader(run).startTime).toBe(formatActivityTime(run.startedAt));
  });

  it("has four headline tiles in a fixed order", () => {
    expect(garminActivityHeader(run).tiles.map((tile) => tile.label)).toEqual([
      "Distance",
      "Time",
      "Avg pace",
      "Avg HR",
    ]);
  });

  it("fills the tiles from a run", () => {
    const values = garminActivityHeader(run).tiles.map((tile) => tile.value);
    expect(values).toEqual(["5 km", "30 min", "6:00 /km", "152 bpm"]);
  });

  it("shows Time as the stored duration, in hours and minutes from an hour up", () => {
    const long = { ...run, durationSeconds: 3_900 };
    expect(garminActivityHeader(long).tiles[1]!.value).toBe("1h 05m");
  });

  it("shows a dash for each missing value rather than dropping the tile or showing 0", () => {
    const bare = {
      ...run,
      distanceMeters: null,
      durationSeconds: null,
      averageHeartRateBpm: null,
    };
    const tiles = garminActivityHeader(bare).tiles;
    expect(tiles).toHaveLength(4);
    expect(tiles.map((tile) => tile.value)).toEqual(["—", "—", "—", "—"]);
  });

  it("keeps a true zero distance as 0 km: zero was recorded, a null was not", () => {
    expect(garminActivityHeader({ ...run, distanceMeters: 0 }).tiles[0]!.value).toBe("0 km");
  });

  it("reads a non-foot activity as speed, with the tile labelled to match", () => {
    const ride = {
      ...run,
      type: "cycling",
      durationSeconds: 3_600,
      distanceMeters: 20_000,
    };
    const tile = garminActivityHeader(ride).tiles[2]!;
    expect(tile.label).toBe("Avg speed");
    expect(tile.value).toBe("20.0 km/h");
  });

  it("shows a dash for pace on a short foot activity", () => {
    const short = { ...run, distanceMeters: 60 };
    expect(garminActivityHeader(short).tiles[2]!.value).toBe("—");
  });
});

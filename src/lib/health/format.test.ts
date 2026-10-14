import { describe, expect, it } from "vitest";

import {
  caloriesEatenNote,
  formatActivitySummary,
  formatActivityType,
  formatCalories,
  formatSleep,
  formatSleepWindow,
  formatSyncStatus,
  goalProgress,
  missingCaloriesEatenNote,
} from "./format";

describe("health presentation", () => {
  it("formats daily health measurements", () => {
    expect(formatCalories(1234)).toBe("1,234 kcal");
    expect(formatSleep(27_300)).toBe("7h 35m");
    expect(formatSleepWindow("2026-09-06T22:30:00Z", "2026-09-07T06:15:00Z")).toBe("23:30–07:15");
  });

  it("formats an activity into a compact readable summary", () => {
    expect(
      formatActivitySummary({
        id: "1",
        source: "garmin",
        name: "Morning Run",
        type: "trail_running",
        startedAt: "2026-09-07T06:00:00Z",
        durationSeconds: 1_805,
        distanceMeters: 5_020,
        caloriesKcal: 401,
        averageHeartRateBpm: 151,
        totalSets: null,
        totalReps: null,
      }),
    ).toBe("30 min · 5.02 km · 401 kcal · 151 bpm avg");
    expect(formatActivityType("strength_training")).toBe("Strength training");
  });

  it("uses an em dash for missing measurements", () => {
    expect(formatCalories(null)).toBe("—");
    expect(formatSleep(undefined)).toBe("—");
  });
});

describe("missing calories eaten note", () => {
  it("explains days before MyFitnessPal was linked", () => {
    expect(missingCaloriesEatenNote("2026-09-27", "2026-09-30")).toBe("Before MFP was linked");
  });

  it("treats the link date itself as a logged day", () => {
    expect(missingCaloriesEatenNote("2026-09-28", "2026-09-30")).toBe("Nothing logged");
  });

  it("says today has not been logged yet rather than that nothing was logged", () => {
    expect(missingCaloriesEatenNote("2026-09-30", "2026-09-30")).toBe("Not logged yet");
  });
});

describe("calories eaten note", () => {
  it("shows the goal when there is one", () => {
    expect(caloriesEatenNote(1_800, 2_500, "2026-09-30", "2026-09-30")).toBe("of 2,500");
  });

  it("shows no note when eaten is known but there is no goal for the day", () => {
    expect(caloriesEatenNote(1_800, null, "2026-09-30", "2026-09-30")).toBeUndefined();
  });

  it("explains a missing value instead of showing the goal", () => {
    expect(caloriesEatenNote(null, 2_500, "2026-09-30", "2026-09-30")).toBe("Not logged yet");
  });
});

describe("goal progress", () => {
  it("is the fraction of the goal eaten, capped at a full bar", () => {
    expect(goalProgress(1_250, 2_500)).toBe(0.5);
    expect(goalProgress(3_000, 2_500)).toBe(1);
  });

  it("has no bar without both a value and a positive goal", () => {
    expect(goalProgress(null, 2_500)).toBeNull();
    expect(goalProgress(1_250, null)).toBeNull();
    expect(goalProgress(1_250, 0)).toBeNull();
  });
});

describe("sync status", () => {
  it("shows the London time a sync last ran, across the BST/GMT change", () => {
    expect(formatSyncStatus("2026-10-06T18:05:00Z")).toContain("19:05");
    expect(formatSyncStatus("2026-12-06T18:05:00Z")).toContain("18:05");
  });

  it("prefixes the time so the row reads as a status", () => {
    expect(formatSyncStatus("2026-10-06T18:05:00Z")).toMatch(/^Last synced .*Oct/);
  });

  it("asks for setup when the source has never synced", () => {
    expect(formatSyncStatus(null)).toBe("Setup required");
    expect(formatSyncStatus(undefined)).toBe("Setup required");
  });
});

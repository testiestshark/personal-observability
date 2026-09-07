import { describe, expect, it } from "vitest";

import {
  formatActivitySummary,
  formatActivityType,
  formatCalories,
  formatSleep,
  formatSleepWindow,
  formatVo2Max,
} from "./format";

describe("health presentation", () => {
  it("formats daily health measurements", () => {
    expect(formatCalories(1234)).toBe("1,234 kcal");
    expect(formatSleep(27_300)).toBe("7h 35m");
    expect(formatVo2Max(51.27)).toBe("51.3");
    expect(formatSleepWindow("2026-09-06T22:30:00Z", "2026-09-07T06:15:00Z")).toBe("23:30–07:15");
  });

  it("formats an activity into a compact readable summary", () => {
    expect(
      formatActivitySummary({
        id: "1",
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

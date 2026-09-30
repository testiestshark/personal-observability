import { describe, expect, it } from "vitest";

import {
  caloriesEatenNote,
  energyBalance,
  energyBalanceNote,
  formatActivitySummary,
  formatActivityType,
  formatCalories,
  formatSleep,
  formatSleepWindow,
  formatVo2Max,
  goalProgress,
  isCompleteDay,
  missingCaloriesEatenNote,
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

describe("complete day", () => {
  it("is complete once Garmin has synced after the London midnight ending it (BST)", () => {
    // 28 Sep is BST, so the day ends at 23:00 UTC.
    expect(isCompleteDay("2026-09-28", "2026-09-30", "2026-09-28T23:00:00Z")).toBe(true);
    expect(isCompleteDay("2026-09-28", "2026-09-30", "2026-09-28T22:59:59Z")).toBe(false);
  });

  it("uses midnight UTC as the end of a GMT day, not the BST offset", () => {
    // 10 Nov is GMT: 23:30 UTC is still 10 Nov in London.
    expect(isCompleteDay("2026-11-10", "2026-11-12", "2026-11-10T23:30:00Z")).toBe(false);
    expect(isCompleteDay("2026-11-10", "2026-11-12", "2026-11-11T00:00:00Z")).toBe(true);
  });

  it("is not complete without a Garmin sync time", () => {
    expect(isCompleteDay("2026-09-28", "2026-09-30", null)).toBe(false);
    expect(isCompleteDay("2026-09-28", "2026-09-30", undefined)).toBe(false);
  });

  it("is never complete for today, whatever the sync time says", () => {
    expect(isCompleteDay("2026-09-30", "2026-09-30", "2026-10-01T09:00:00Z")).toBe(false);
  });
});

describe("energy balance", () => {
  it("is calories eaten minus total calories, negative for a deficit", () => {
    expect(energyBalance(2_100, 2_600, true)).toBe(-500);
    expect(energyBalance(2_800, 2_600, true)).toBe(200);
  });

  it("is undefined for a day that is not complete", () => {
    expect(energyBalance(2_100, 2_600, false)).toBeNull();
  });

  it("is undefined when either side is missing", () => {
    expect(energyBalance(null, 2_600, true)).toBeNull();
    expect(energyBalance(2_100, null, true)).toBeNull();
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

describe("energy balance note", () => {
  it("says the balance is pending while the day is not complete", () => {
    expect(energyBalanceNote(false, 2_100, 2_600)).toBe("Final once the day is synced");
  });

  it("names the missing side on a complete day rather than blaming the sync", () => {
    expect(energyBalanceNote(true, null, 2_600)).toBe("No calories eaten");
    expect(energyBalanceNote(true, 2_100, null)).toBe("No total calories");
  });

  it("has no note once the balance is shown", () => {
    expect(energyBalanceNote(true, 2_100, 2_600)).toBeUndefined();
  });
});

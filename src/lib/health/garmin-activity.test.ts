import { describe, expect, it } from "vitest";

import { formatActivityTime, formatActivityType } from "./format";
import {
  formatAveragePace,
  formatAverageSpeed,
  garminActivityHeader,
  garminActivitySections,
  garminSplits,
  humaniseTrainingEffectLabel,
  isFootActivity,
  SPLIT_BAR_MIN_SHARE,
  type GarminSection,
  type SplitRow,
} from "./garmin-activity";
import type { GarminActivityDetail, GarminLap } from "./health.functions";

/** A run with only the day-view fields; every secondary metric is null. */
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
  movingDurationSeconds: null,
  elapsedDurationSeconds: null,
  maximumHeartRateBpm: null,
  elevationGainMeters: null,
  elevationLossMeters: null,
  averageSpeedMps: null,
  maximumSpeedMps: null,
  averageCadenceSpm: null,
  maximumCadenceSpm: null,
  averagePowerWatts: null,
  maximumPowerWatts: null,
  normalizedPowerWatts: null,
  aerobicTrainingEffect: null,
  anaerobicTrainingEffect: null,
  trainingLoad: null,
  trainingEffectLabel: null,
  laps: [],
};

/** A run with every secondary metric the worker stores today (power and load stay null). */
const fullRun: GarminActivityDetail = {
  ...run,
  movingDurationSeconds: 1_740,
  elapsedDurationSeconds: 1_860,
  maximumHeartRateBpm: 178,
  elevationGainMeters: 42.4,
  elevationLossMeters: 40.1,
  averageSpeedMps: 2.78,
  maximumSpeedMps: 4,
  averageCadenceSpm: 164.6,
  maximumCadenceSpm: 181,
  aerobicTrainingEffect: 3.24,
  anaerobicTrainingEffect: 0.5,
  trainingEffectLabel: "AEROBIC_BASE",
};

function sectionTitles(activity: GarminActivityDetail): string[] {
  return garminActivitySections(activity).map((section) => section.title);
}

function section(activity: GarminActivityDetail, title: string): GarminSection {
  const found = garminActivitySections(activity).find((candidate) => candidate.title === title);
  if (!found) throw new Error(`No "${title}" section`);
  return found;
}

function rowsOf(activity: GarminActivityDetail, title: string): [string, string][] {
  return section(activity, title).rows.map((row) => [row.label, row.value]);
}

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

describe("humaniseTrainingEffectLabel", () => {
  it("turns Garmin's upper-case key into a sentence", () => {
    expect(humaniseTrainingEffectLabel("AEROBIC_BASE")).toBe("Aerobic base");
    expect(humaniseTrainingEffectLabel("TEMPO")).toBe("Tempo");
    expect(humaniseTrainingEffectLabel("ANAEROBIC_CAPACITY")).toBe("Anaerobic capacity");
  });

  it("keeps a word with a digit in capitals, so VO2MAX is not read as Vo2max", () => {
    expect(humaniseTrainingEffectLabel("VO2MAX")).toBe("VO2MAX");
  });

  it("is null for a missing or blank label", () => {
    expect(humaniseTrainingEffectLabel(null)).toBeNull();
    expect(humaniseTrainingEffectLabel("  ")).toBeNull();
  });
});

describe("garminActivitySections", () => {
  it("has no sections for a run with no secondary metrics, except the calories it does have", () => {
    // `run` carries calories, which is part of Effort; everything else is null.
    expect(sectionTitles(run)).toEqual(["Effort"]);
    expect(sectionTitles({ ...run, caloriesKcal: null })).toEqual([]);
  });

  it("lists the sections that have data, in a fixed order", () => {
    expect(sectionTitles(fullRun)).toEqual([
      "Effort",
      "Elevation",
      "Pace and speed",
      "Running form",
      "Training effect",
      "Time",
    ]);
  });

  describe("Effort", () => {
    it("shows max HR and calories", () => {
      expect(rowsOf(fullRun, "Effort")).toEqual([
        ["Max HR", "178 bpm"],
        ["Calories", "340 kcal"],
      ]);
    });

    it("drops the row that is null and keeps the other", () => {
      expect(rowsOf({ ...fullRun, caloriesKcal: null }, "Effort")).toEqual([["Max HR", "178 bpm"]]);
      expect(rowsOf({ ...fullRun, maximumHeartRateBpm: null }, "Effort")).toEqual([
        ["Calories", "340 kcal"],
      ]);
    });
  });

  describe("Elevation", () => {
    it("shows gain and loss in whole metres", () => {
      expect(rowsOf(fullRun, "Elevation")).toEqual([
        ["Gain", "42 m"],
        ["Loss", "40 m"],
      ]);
    });

    it("keeps a recorded zero as 0 m: a flat run is data, a null is not", () => {
      const flat = { ...fullRun, elevationGainMeters: 0, elevationLossMeters: 0 };
      expect(rowsOf(flat, "Elevation")).toEqual([
        ["Gain", "0 m"],
        ["Loss", "0 m"],
      ]);
    });

    it("is absent when both are null", () => {
      const none = { ...fullRun, elevationGainMeters: null, elevationLossMeters: null };
      expect(sectionTitles(none)).not.toContain("Elevation");
    });

    it("shows the one that is present", () => {
      expect(rowsOf({ ...fullRun, elevationLossMeters: null }, "Elevation")).toEqual([
        ["Gain", "42 m"],
      ]);
    });
  });

  describe("Pace and speed", () => {
    it("gives a foot activity its best pace, from max speed", () => {
      // 4 m/s is 250 s per km.
      expect(rowsOf(fullRun, "Pace and speed")).toEqual([["Best pace", "4:10 /km"]]);
    });

    it("gives a non-foot activity avg and max speed in km/h instead of a pace", () => {
      const ride = { ...fullRun, type: "cycling", averageSpeedMps: 5, maximumSpeedMps: 12.5 };
      expect(rowsOf(ride, "Pace and speed")).toEqual([
        ["Avg speed", "18.0 km/h"],
        ["Max speed", "45.0 km/h"],
      ]);
    });

    it("does not show speeds for a foot activity or a pace for a ride", () => {
      const labels = (activity: GarminActivityDetail) =>
        rowsOf(activity, "Pace and speed").map(([label]) => label);
      expect(labels(fullRun)).not.toContain("Avg speed");
      expect(labels({ ...fullRun, type: "cycling" })).not.toContain("Best pace");
    });

    it("is absent when max speed is null, zero or not finite", () => {
      for (const maximumSpeedMps of [null, 0, Number.NaN]) {
        const bare = { ...fullRun, maximumSpeedMps };
        expect(sectionTitles(bare)).not.toContain("Pace and speed");
      }
    });

    it("shows the speed that is present when only one of avg and max is", () => {
      const ride = { ...fullRun, type: "cycling", averageSpeedMps: null, maximumSpeedMps: 10 };
      expect(rowsOf(ride, "Pace and speed")).toEqual([["Max speed", "36.0 km/h"]]);
    });
  });

  describe("Running form", () => {
    it("shows avg and max cadence in steps per minute", () => {
      expect(rowsOf(fullRun, "Running form")).toEqual([
        ["Avg cadence", "165 spm"],
        ["Max cadence", "181 spm"],
      ]);
    });

    it("is absent when both are null", () => {
      const none = { ...fullRun, averageCadenceSpm: null, maximumCadenceSpm: null };
      expect(sectionTitles(none)).not.toContain("Running form");
    });

    it("reads a bike's cadence in rpm under its own title, not as running form", () => {
      const ride = { ...fullRun, type: "cycling", averageCadenceSpm: 88, maximumCadenceSpm: 112 };
      expect(sectionTitles(ride)).not.toContain("Running form");
      expect(rowsOf(ride, "Cadence")).toEqual([
        ["Avg cadence", "88 rpm"],
        ["Max cadence", "112 rpm"],
      ]);
    });
  });

  describe("Training effect", () => {
    it("shows aerobic and anaerobic to one decimal, with the humanised label", () => {
      expect(rowsOf(fullRun, "Training effect")).toEqual([
        ["Aerobic", "3.2"],
        ["Anaerobic", "0.5"],
        ["Primary benefit", "Aerobic base"],
      ]);
    });

    it("pads a whole value to one decimal", () => {
      const whole = { ...fullRun, aerobicTrainingEffect: 4, anaerobicTrainingEffect: 0 };
      expect(rowsOf(whole, "Training effect").slice(0, 2)).toEqual([
        ["Aerobic", "4.0"],
        ["Anaerobic", "0.0"],
      ]);
    });

    it("shows the label alone when the values are null", () => {
      const labelOnly = { ...fullRun, aerobicTrainingEffect: null, anaerobicTrainingEffect: null };
      expect(rowsOf(labelOnly, "Training effect")).toEqual([["Primary benefit", "Aerobic base"]]);
    });

    it("is absent when the values and the label are all null", () => {
      const none = {
        ...fullRun,
        aerobicTrainingEffect: null,
        anaerobicTrainingEffect: null,
        trainingEffectLabel: null,
      };
      expect(sectionTitles(none)).not.toContain("Training effect");
    });
  });

  describe("Time", () => {
    it("shows moving and elapsed time when they differ from the headline Time", () => {
      expect(rowsOf(fullRun, "Time")).toEqual([
        ["Moving", "29:00"],
        ["Elapsed", "31:00"],
      ]);
    });

    it("counts from an hour up as h:mm:ss", () => {
      const long = {
        ...fullRun,
        durationSeconds: 3_900,
        movingDurationSeconds: 3_725,
        elapsedDurationSeconds: 4_000,
      };
      expect(rowsOf(long, "Time")).toEqual([
        ["Moving", "1:02:05"],
        ["Elapsed", "1:06:40"],
      ]);
    });

    it("hides a line within a few seconds of the headline Time, and keeps one beyond", () => {
      const close = { ...fullRun, movingDurationSeconds: 1_805, elapsedDurationSeconds: 1_806 };
      // 5 s apart is not "more than a few seconds"; 6 s is.
      expect(rowsOf(close, "Time")).toEqual([["Elapsed", "30:06"]]);
    });

    it("hides a line equal to the headline Time", () => {
      const same = { ...fullRun, movingDurationSeconds: 1_800, elapsedDurationSeconds: 1_800 };
      expect(sectionTitles(same)).not.toContain("Time");
    });

    it("measures the difference either way round", () => {
      const shorter = { ...fullRun, movingDurationSeconds: 1_700, elapsedDurationSeconds: null };
      expect(rowsOf(shorter, "Time")).toEqual([["Moving", "28:20"]]);
    });

    it("is absent when both are null", () => {
      const none = { ...fullRun, movingDurationSeconds: null, elapsedDurationSeconds: null };
      expect(sectionTitles(none)).not.toContain("Time");
    });

    it("shows them when the headline Time is itself missing, since there is nothing to repeat", () => {
      const noHeadline = { ...fullRun, durationSeconds: null };
      expect(rowsOf(noHeadline, "Time")).toEqual([
        ["Moving", "29:00"],
        ["Elapsed", "31:00"],
      ]);
    });
  });

  describe("Power and training load", () => {
    const powered: GarminActivityDetail = {
      ...fullRun,
      averagePowerWatts: 245.4,
      maximumPowerWatts: 410,
      normalizedPowerWatts: 262,
      trainingLoad: 87.6,
    };

    it("appears once the worker populates it", () => {
      expect(rowsOf(powered, "Power and training load")).toEqual([
        ["Avg power", "245 W"],
        ["Max power", "410 W"],
        ["Normalized power", "262 W"],
        ["Training load", "88"],
      ]);
    });

    it("is the last section", () => {
      expect(sectionTitles(powered).at(-1)).toBe("Power and training load");
    });

    it("is absent for a run with none of it, as every real row is today", () => {
      expect(sectionTitles(fullRun)).not.toContain("Power and training load");
    });

    it("shows training load alone when there is no power", () => {
      const loadOnly = { ...fullRun, trainingLoad: 120 };
      expect(rowsOf(loadOnly, "Power and training load")).toEqual([["Training load", "120"]]);
    });

    it("keeps a recorded zero rather than hiding it as if it were null", () => {
      const zero = { ...fullRun, averagePowerWatts: 0 };
      expect(rowsOf(zero, "Power and training load")).toEqual([["Avg power", "0 W"]]);
    });
  });

  it("renders nothing at all for a run whose metrics are all null, rather than zeros", () => {
    expect(garminActivitySections({ ...run, caloriesKcal: null })).toEqual([]);
  });

  it("has no section without rows", () => {
    for (const activity of [run, fullRun]) {
      for (const s of garminActivitySections(activity)) expect(s.rows.length).toBeGreaterThan(0);
    }
  });
});

/** A 1 km lap at 5:30 /km; override what a case is about. */
function lap(position: number, overrides: Partial<GarminLap> = {}): GarminLap {
  return {
    position,
    distanceMeters: 1_000,
    durationSeconds: 330,
    averageHeartRateBpm: 148,
    elevationGainMeters: 6,
    elevationLossMeters: 3,
    ...overrides,
  };
}

function withLaps(laps: GarminLap[], overrides: Partial<GarminActivityDetail> = {}) {
  return { ...run, laps, ...overrides };
}

/** A row by index, failing the test with a clear message rather than on `undefined`. */
function at(rows: SplitRow[], index: number): SplitRow {
  const row = rows[index];
  if (!row) throw new Error(`No split row ${index}; there are ${rows.length}`);
  return row;
}

describe("garminSplits", () => {
  it("is empty for a run with no stored laps, as every run before the backfill is", () => {
    expect(garminSplits(run)).toEqual([]);
  });

  it("is empty for a single lap, which would only repeat the headline", () => {
    expect(garminSplits(withLaps([lap(0)]))).toEqual([]);
  });

  it("is empty for an activity read as speed rather than pace, whatever laps it has", () => {
    const ride = withLaps([lap(0), lap(1)], { type: "cycling" });
    expect(garminSplits(ride)).toEqual([]);
  });

  it("shows each lap's number, time, pace, heart rate and net elevation", () => {
    const rows = garminSplits(
      withLaps([
        lap(0),
        lap(1, {
          durationSeconds: 345.4,
          averageHeartRateBpm: 151.2,
          elevationGainMeters: 2,
          elevationLossMeters: 10,
        }),
      ]),
    );

    expect(at(rows, 0)).toMatchObject({
      label: "1",
      time: "5:30",
      pace: "5:30",
      heartRate: "148",
      elevation: "+3 m",
    });
    expect(at(rows, 1)).toMatchObject({
      label: "2",
      time: "5:45",
      pace: "5:45",
      heartRate: "151",
      elevation: "-8 m",
    });
  });

  it("shows a lap that climbed as much as it fell as 0 m, not as a gap", () => {
    const rows = garminSplits(
      withLaps([lap(0, { elevationGainMeters: 4, elevationLossMeters: 4 }), lap(1)]),
    );
    expect(at(rows, 0).elevation).toBe("0 m");
  });

  it("orders laps by position whatever order they arrive in", () => {
    const rows = garminSplits(
      withLaps([lap(2, { durationSeconds: 360 }), lap(0), lap(1, { durationSeconds: 340 })]),
    );
    expect(rows.map((row) => [row.label, row.time])).toEqual([
      ["1", "5:30"],
      ["2", "5:40"],
      ["3", "6:00"],
    ]);
  });

  it("reads a measurement Garmin did not report as a dash, never as zero", () => {
    const bare = at(
      garminSplits(
        withLaps([
          lap(0, {
            distanceMeters: null,
            averageHeartRateBpm: null,
            elevationGainMeters: null,
            elevationLossMeters: null,
          }),
          lap(1),
        ]),
      ),
      0,
    );

    expect(bare).toMatchObject({ pace: "—", heartRate: "—", elevation: "—", barShare: null });
    expect(bare.time).toBe("5:30");
  });

  it("needs both gain and loss for an elevation change", () => {
    const gainOnly = at(garminSplits(withLaps([lap(0, { elevationLossMeters: null }), lap(1)])), 0);
    expect(gainOnly.elevation).toBe("—");
  });

  it("notes the distance only of a lap shorter than the rest, such as the last", () => {
    const rows = garminSplits(withLaps([lap(0), lap(1), lap(2, { distanceMeters: 340 })]));
    expect(rows.map((row) => row.distanceNote)).toEqual([null, null, "0.34 km"]);
  });

  it("gives no pace to a lap under the minimum shown distance", () => {
    const rows = garminSplits(
      withLaps([lap(0), lap(1), lap(2, { distanceMeters: 60, durationSeconds: 20 })]),
    );
    expect(at(rows, 2)).toMatchObject({ pace: "—", barShare: null, distanceNote: "0.06 km" });
  });

  describe("pace bars", () => {
    it("makes the fastest lap the longest bar and the slowest the shortest", () => {
      const rows = garminSplits(
        withLaps([
          lap(0, { durationSeconds: 330 }),
          lap(1, { durationSeconds: 345 }),
          lap(2, { durationSeconds: 360 }),
        ]),
      );

      expect(at(rows, 0).barShare).toBe(1);
      expect(at(rows, 2).barShare).toBe(SPLIT_BAR_MIN_SHARE);
      expect(at(rows, 1).barShare).toBeGreaterThan(SPLIT_BAR_MIN_SHARE);
      expect(at(rows, 1).barShare).toBeLessThan(1);
    });

    it("draws equal bars when every lap is equally fast", () => {
      const rows = garminSplits(withLaps([lap(0), lap(1), lap(2)]));
      expect(rows.map((row) => row.barShare)).toEqual([1, 1, 1]);
    });

    it("does not let a short sprint finish rescale the full laps", () => {
      const rows = garminSplits(
        withLaps([
          lap(0, { durationSeconds: 330 }),
          lap(1, { durationSeconds: 340 }),
          lap(2, { distanceMeters: 200, durationSeconds: 40 }),
        ]),
      );

      // The sprint is faster than either full lap but only 200 m long.
      expect(at(rows, 0).barShare).toBe(1);
      expect(at(rows, 1).barShare).toBe(SPLIT_BAR_MIN_SHARE);
      expect(at(rows, 2).barShare).toBe(1);
    });
  });
});

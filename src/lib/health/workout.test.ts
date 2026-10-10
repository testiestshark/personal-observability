import { describe, expect, it } from "vitest";

import type { FitnessActivity, FitnessActivityDetail, FitnessExercise } from "./health.functions";
import {
  activityDetailKind,
  formatKg,
  formatWorkoutDuration,
  isActivityLinked,
  UNTITLED_EXERCISE,
  workoutExercises,
  workoutHeader,
} from "./workout";

const exercise = (overrides: Partial<FitnessExercise> & { position: number }): FitnessExercise => ({
  id: `exercise-${overrides.position}`,
  title: "Bench Press (Barbell)",
  notes: null,
  supersetId: null,
  sets: [],
  ...overrides,
});

const hevyStrength: FitnessActivityDetail = {
  id: "5b0f7c1e-6f3a-4d34-9c5e-0f7f6a1c2b11",
  source: "hevy",
  name: "Push day",
  type: "strength_training",
  localDay: "2026-10-08",
  startedAt: "2026-10-08T17:42:00Z",
  durationSeconds: 3_900,
  distanceMeters: null,
  caloriesKcal: null,
  averageHeartRateBpm: null,
  totalSets: 14,
  activeSets: 12,
  totalReps: 96,
  totalVolumeKg: 5_432.5,
  exercises: [],
};

describe("formatKg", () => {
  it("drops trailing zeros: whole numbers have no decimals", () => {
    expect(formatKg(60)).toBe("60 kg");
    expect(formatKg(60.0)).toBe("60 kg");
  });

  it("keeps up to two decimals, trimmed", () => {
    expect(formatKg(62.5)).toBe("62.5 kg");
    expect(formatKg(61.25)).toBe("61.25 kg");
  });

  it("rounds to two decimals rather than showing float noise", () => {
    expect(formatKg(0.1 + 0.2)).toBe("0.3 kg");
    expect(formatKg(62.499)).toBe("62.5 kg");
  });

  it("groups thousands so a large volume stays readable", () => {
    expect(formatKg(12_450)).toContain("12,450");
  });

  it("shows bodyweight-only sets as 0 kg", () => {
    expect(formatKg(0)).toBe("0 kg");
  });
});

describe("formatWorkoutDuration", () => {
  it("shows minutes under an hour", () => {
    expect(formatWorkoutDuration(2_700)).toBe("45 min");
  });

  it("shows hours and zero-padded minutes from an hour up", () => {
    expect(formatWorkoutDuration(3_900)).toBe("1h 05m");
    expect(formatWorkoutDuration(7_200)).toBe("2h 00m");
  });

  it("rounds to the nearest minute, carrying into the hour", () => {
    expect(formatWorkoutDuration(3_570)).toBe("1h 00m");
  });

  it("uses an em dash when the duration is unknown", () => {
    expect(formatWorkoutDuration(null)).toBe("—");
  });
});

describe("workoutHeader", () => {
  it("builds every header field from the stored totals, in the formats the page shows", () => {
    const header = workoutHeader(hevyStrength);
    expect(header.title).toBe("Push day");
    expect(header.duration).toBe("1h 05m");
    expect(header.activeSets).toBe("12");
    expect(header.totalReps).toBe("96");
    expect(header.volume).toContain("5,432.5");
    expect(header.localDay).toBe("2026-10-08");
  });

  it("shows the start time in London, not UTC (BST)", () => {
    // 8 Oct is BST: 17:42 UTC is 18:42 in London.
    expect(workoutHeader(hevyStrength).startTime).toContain("18:42");
  });

  it("shows the start time in London during GMT", () => {
    const winter = { ...hevyStrength, startedAt: "2026-12-08T17:42:00Z", localDay: "2026-12-08" };
    expect(workoutHeader(winter).startTime).toContain("17:42");
  });

  it("labels the date from the stored local day, not the UTC date of the start", () => {
    // 00:30 BST on the 9th is 23:30 UTC on the 8th; the local day is the 9th.
    const lateNight = {
      ...hevyStrength,
      startedAt: "2026-10-08T23:30:00Z",
      localDay: "2026-10-09",
    };
    const header = workoutHeader(lateNight);
    expect(header.dateLabel).toContain("09");
    expect(header.dateLabel).toContain("Oct");
    expect(header.localDay).toBe("2026-10-09");
  });

  it("falls back to the activity type when the workout is untitled", () => {
    expect(workoutHeader({ ...hevyStrength, name: null }).title).toBe("Strength training");
    expect(workoutHeader({ ...hevyStrength, name: "  " }).title).toBe("Strength training");
  });

  it("uses an em dash for totals the sync did not store", () => {
    const header = workoutHeader({
      ...hevyStrength,
      durationSeconds: null,
      activeSets: null,
      totalReps: null,
      totalVolumeKg: null,
    });
    expect(header.duration).toBe("—");
    expect(header.activeSets).toBe("—");
    expect(header.totalReps).toBe("—");
    expect(header.volume).toBe("—");
  });
});

describe("workoutExercises", () => {
  it("lists exercises in the order they were done, whatever order they arrive in", () => {
    const shuffled = [
      exercise({ position: 2, title: "Triceps Pushdown" }),
      exercise({ position: 0, title: "Bench Press (Barbell)" }),
      exercise({ position: 1, title: "Incline Press (Dumbbell)" }),
    ];
    expect(workoutExercises(shuffled).map((item) => item.title)).toEqual([
      "Bench Press (Barbell)",
      "Incline Press (Dumbbell)",
      "Triceps Pushdown",
    ]);
  });

  it("orders by position as a number, not as text (10 comes after 2)", () => {
    const positions = [10, 2, 0, 1].map((position) =>
      exercise({ position, title: `Exercise ${position}` }),
    );
    expect(workoutExercises(positions).map((item) => item.title)).toEqual([
      "Exercise 0",
      "Exercise 1",
      "Exercise 2",
      "Exercise 10",
    ]);
  });

  it("does not reorder the array it was given", () => {
    const input = [exercise({ position: 1 }), exercise({ position: 0 })];
    workoutExercises(input);
    expect(input.map((item) => item.position)).toEqual([1, 0]);
  });

  it("falls back to 'Untitled exercise' when Hevy sent no title", () => {
    const [item] = workoutExercises([exercise({ position: 0, title: null })]);
    expect(item?.title).toBe(UNTITLED_EXERCISE);
    expect(UNTITLED_EXERCISE).toBe("Untitled exercise");
  });

  it("treats a blank title as untitled too", () => {
    const [item] = workoutExercises([exercise({ position: 0, title: "   " })]);
    expect(item?.title).toBe(UNTITLED_EXERCISE);
  });

  it("carries an exercise's notes through, trimmed", () => {
    const [item] = workoutExercises([exercise({ position: 0, notes: "  Paused reps  " })]);
    expect(item?.notes).toBe("Paused reps");
  });

  it("has no notes when they are null or blank, so the page shows none", () => {
    const items = workoutExercises([
      exercise({ position: 0, notes: null }),
      exercise({ position: 1, notes: "  " }),
    ]);
    expect(items.map((item) => item.notes)).toEqual([null, null]);
  });

  it("returns an empty list for a workout with no exercises", () => {
    expect(workoutExercises([])).toEqual([]);
  });
});

describe("activityDetailKind", () => {
  it("renders Hevy strength training as a workout", () => {
    expect(activityDetailKind(hevyStrength)).toBe("hevy-strength");
  });

  it("has no detail view for a Garmin activity", () => {
    expect(activityDetailKind({ ...hevyStrength, source: "garmin", type: "running" })).toBe(
      "unsupported",
    );
  });

  it("has no detail view for a Hevy activity of another type", () => {
    expect(activityDetailKind({ ...hevyStrength, type: "running" })).toBe("unsupported");
  });
});

describe("isActivityLinked", () => {
  const card = (source: FitnessActivity["source"]) => ({ source });

  it("links Hevy cards on the day view", () => {
    expect(isActivityLinked(card("hevy"))).toBe(true);
  });

  it("leaves Garmin cards plain until #72", () => {
    expect(isActivityLinked(card("garmin"))).toBe(false);
  });
});

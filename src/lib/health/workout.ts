import type {
  FitnessActivity,
  FitnessExercise,
  FitnessSet,
  HevyActivityDetail,
} from "./health.functions";
import { formatActivityTime, formatActivityType } from "./format";
import { formatDayLabel } from "@/lib/weight/units";

/** Up to two decimals, trailing zeros trimmed, thousands grouped. */
const decimalNumber = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

/**
 * A weight in kilograms: up to two decimals, trailing zeros trimmed
 * ("60 kg", "62.5 kg"). kg only, whatever unit the weight page is set to:
 * Hevy stores kilograms and the workout view shows them as recorded.
 */
export function formatKg(kilograms: number): string {
  return `${decimalNumber.format(kilograms)} kg`;
}

/** "45 min" under an hour, "1h 05m" from an hour up; "—" when unknown. */
export function formatWorkoutDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 60) return `${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = String(totalMinutes % 60).padStart(2, "0");
  return `${hours}h ${minutes}m`;
}

function formatCount(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("en-GB");
}

export type WorkoutHeader = {
  title: string;
  /** The stored London day, "YYYY-MM-DD": the back link's target. */
  localDay: string;
  dateLabel: string;
  startTime: string;
  duration: string;
  activeSets: string;
  totalReps: string;
  volume: string;
};

/**
 * The detail page's header, ready to render.
 *
 * The date comes from the stored `local_day`, not from `startedAt`: the day is
 * decided once, in London, by the sync, and the day view filters on the same
 * column, so the back link always lands on the day the card was listed under.
 */
export function workoutHeader(activity: HevyActivityDetail): WorkoutHeader {
  return {
    title: activity.name?.trim() || formatActivityType(activity.type),
    localDay: activity.localDay,
    dateLabel: formatDayLabel(activity.localDay),
    startTime: formatActivityTime(activity.startedAt),
    duration: formatWorkoutDuration(activity.durationSeconds),
    activeSets: formatCount(activity.activeSets),
    totalReps: formatCount(activity.totalReps),
    volume: activity.totalVolumeKg === null ? "—" : formatKg(activity.totalVolumeKg),
  };
}

/** Shown for an exercise Hevy sent without a title. */
export const UNTITLED_EXERCISE = "Untitled exercise";

export type SetMarker = "W" | "D" | "F";

const SET_MARKERS = new Map<string, SetMarker>([
  ["warmup", "W"],
  ["dropset", "D"],
  ["failure", "F"],
]);

export type WorkoutSetRow = {
  id: string;
  /** "W", "D" or "F" for a marked set, otherwise the set's number: "1", "2"... */
  label: string;
  /** Null for a normal set, which carries a number instead. */
  marker: SetMarker | null;
  /**
   * What the set recorded, in reading order: weight x reps, distance, duration,
   * custom metric, RPE. Only the values it has; empty when it recorded nothing.
   */
  measurements: string[];
};

/** A number worth showing: not null, and not the NaN or Infinity a bad row could carry. */
function present(value: number | null): value is number {
  return value !== null && Number.isFinite(value);
}

/** "40 m" under a kilometre, "1.25 km" from a kilometre up. Hevy stores metres. */
function formatDistance(meters: number): string {
  return meters < 1_000
    ? `${decimalNumber.format(meters)} m`
    : `${decimalNumber.format(meters / 1_000)} km`;
}

/** "45 s", "2 min 5 s", "1 h 5 min": the non-zero parts, unit always shown. Hevy stores seconds. */
function formatSetDuration(seconds: number): string {
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  const secs = total % 60;
  const parts = [
    hours > 0 ? `${hours} h` : null,
    minutes > 0 ? `${minutes} min` : null,
    secs > 0 ? `${secs} s` : null,
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join(" ") : "0 s";
}

/** Weight x reps as Hevy shows them: "62.5 kg x 8", or whichever half was recorded. */
function formatWeightReps(weightKg: number | null, reps: number | null): string | null {
  if (present(weightKg) && present(reps)) return `${formatKg(weightKg)} x ${reps}`;
  if (present(weightKg)) return formatKg(weightKg);
  if (present(reps)) return `${reps} ${reps === 1 ? "rep" : "reps"}`;
  return null;
}

function setMeasurements(set: FitnessSet): string[] {
  return [
    formatWeightReps(set.weightKg, set.reps),
    present(set.distanceMeters) ? formatDistance(set.distanceMeters) : null,
    present(set.durationSeconds) ? formatSetDuration(set.durationSeconds) : null,
    // Hevy only uses this for floors or steps on stair machines, so it has no
    // unit worth guessing at: the bare number is what the owner logged.
    present(set.customMetric) ? decimalNumber.format(set.customMetric) : null,
    present(set.rpe) ? `RPE ${decimalNumber.format(set.rpe)}` : null,
  ].filter((value) => value !== null);
}

/**
 * An exercise's sets as rows, in the order they were done.
 *
 * Only normal sets are numbered. Warmup, dropset and failure sets show their
 * marker instead and do not take a number, so a warmup followed by two working
 * sets reads W, 1, 2. A set type this code does not know is numbered as a
 * normal set rather than hidden: the database limits the column to the four
 * Hevy types, so that is only a guard against Hevy adding a fifth.
 */
export function workoutSets(sets: readonly FitnessSet[]): WorkoutSetRow[] {
  let nextNumber = 1;
  return [...sets]
    .sort((a, b) => a.position - b.position)
    .map((set) => {
      const marker = SET_MARKERS.get(set.type) ?? null;
      return {
        id: set.id,
        label: marker ?? String(nextNumber++),
        marker,
        measurements: setMeasurements(set),
      };
    });
}

export type WorkoutExercise = {
  id: string;
  title: string;
  /** Null when absent or blank, so the page has one thing to check. */
  notes: string | null;
  /** Exercises that share a value, back to back, are one superset. Null when in none. */
  supersetId: number | null;
  sets: WorkoutSetRow[];
};

/**
 * The exercises as the page lists them: in the order they were done, with the
 * untitled fallback applied and each one's sets labelled. The server function
 * already returns them ordered; sorting here as well keeps the page right if
 * that ever changes.
 */
export function workoutExercises(exercises: readonly FitnessExercise[]): WorkoutExercise[] {
  return [...exercises]
    .sort((a, b) => a.position - b.position)
    .map((exercise) => ({
      id: exercise.id,
      title: exercise.title?.trim() || UNTITLED_EXERCISE,
      notes: exercise.notes?.trim() || null,
      supersetId: exercise.supersetId,
      sets: workoutSets(exercise.sets),
    }));
}

/** How many colours superset groups cycle through. */
export const SUPERSET_COLOUR_COUNT = 4;

export type WorkoutBlock =
  | { kind: "single"; exercise: WorkoutExercise }
  | {
      kind: "superset";
      /**
       * "Superset A", "Superset B"... in the order the groups appear, "AA" after
       * "Z". The letter carries the meaning; colour only reinforces it.
       */
      label: string;
      /** 0 to SUPERSET_COLOUR_COUNT - 1; the page maps it to a theme token. */
      colour: number;
      exercises: WorkoutExercise[];
    };

/** 0 is "A", 25 is "Z", 26 is "AA": the way a spreadsheet names its columns. */
function groupLetter(index: number): string {
  let letter = "";
  for (let rest = index; rest >= 0; rest = Math.floor(rest / 26) - 1) {
    letter = String.fromCharCode(65 + (rest % 26)) + letter;
  }
  return letter;
}

/**
 * The exercises as the page renders them: ungrouped ones on their own, and runs
 * of exercises that share a superset id as one labelled group.
 *
 * Only consecutive exercises group. Hevy ids supersets per workout and the same
 * id can sit either side of an exercise that is not part of it; that is two
 * supersets, not one group with a hole in it. A run of one is not a superset
 * either, so it stays ungrouped and takes no letter: Hevy can leave an id
 * behind when the other half is removed.
 *
 * Letters and colours follow the order groups appear, not the ids, which are
 * arbitrary numbers. Expects exercises already in workout order, as
 * `workoutExercises` returns them.
 */
export function groupSupersets(exercises: readonly WorkoutExercise[]): WorkoutBlock[] {
  const blocks: WorkoutBlock[] = [];
  let groupsSoFar = 0;
  let index = 0;
  while (index < exercises.length) {
    const first = exercises[index]!;
    let end = index + 1;
    if (first.supersetId !== null) {
      while (end < exercises.length && exercises[end]!.supersetId === first.supersetId) end++;
    }
    const run = exercises.slice(index, end);
    if (first.supersetId !== null && run.length > 1) {
      blocks.push({
        kind: "superset",
        label: `Superset ${groupLetter(groupsSoFar)}`,
        colour: groupsSoFar % SUPERSET_COLOUR_COUNT,
        exercises: run,
      });
      groupsSoFar++;
    } else {
      blocks.push(...run.map((exercise) => ({ kind: "single" as const, exercise })));
    }
    index = end;
  }
  return blocks;
}

export type ActivityDetailKind = "hevy-strength" | "garmin-activity" | "unsupported";

/**
 * Which detail view, if any, an activity gets. This one rule decides both
 * whether a day-view card is a link and which page it opens, so a card can
 * never lead to a page that has no view for it.
 */
export function activityDetailKind(
  activity: Pick<FitnessActivity, "source" | "type">,
): ActivityDetailKind {
  if (activity.source === "garmin") return "garmin-activity";
  if (activity.source === "hevy" && activity.type === "strength_training") return "hevy-strength";
  return "unsupported";
}

/** Whether the day view's card for this activity opens a detail page. */
export function isActivityLinked(activity: Pick<FitnessActivity, "source" | "type">): boolean {
  return activityDetailKind(activity) !== "unsupported";
}

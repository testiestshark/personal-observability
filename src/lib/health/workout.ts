import type { FitnessActivity, FitnessActivityDetail } from "./health.functions";
import { formatActivityTime, formatActivityType } from "./format";
import { formatDayLabel } from "@/lib/weight/units";

const kgNumber = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

/**
 * A weight in kilograms: up to two decimals, trailing zeros trimmed
 * ("60 kg", "62.5 kg"). kg only, whatever unit the weight page is set to:
 * Hevy stores kilograms and the workout view shows them as recorded.
 */
export function formatKg(kilograms: number): string {
  return `${kgNumber.format(kilograms)} kg`;
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
export function workoutHeader(activity: FitnessActivityDetail): WorkoutHeader {
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

export type ActivityDetailKind = "hevy-strength" | "unsupported";

/** Which detail view, if any, an activity gets. Garmin runs wait on #72. */
export function activityDetailKind(
  activity: Pick<FitnessActivity, "source" | "type">,
): ActivityDetailKind {
  return activity.source === "hevy" && activity.type === "strength_training"
    ? "hevy-strength"
    : "unsupported";
}

/** Whether the day view's card for this activity opens a detail page. */
export function isActivityLinked(activity: Pick<FitnessActivity, "source">): boolean {
  return activity.source === "hevy";
}

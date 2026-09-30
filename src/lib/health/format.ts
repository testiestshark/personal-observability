import { londonDayKey } from "@/lib/weight/units";

import type { FitnessActivity } from "./health.functions";

const londonTime = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/London",
});

export function formatCalories(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toLocaleString("en-GB")} kcal`;
}

export function formatSleep(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const totalMinutes = Math.round(value / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h ${minutes}m`;
}

export function formatSleepWindow(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) return "—";
  return `${londonTime.format(new Date(start))}–${londonTime.format(new Date(end))}`;
}

export function formatHeartRate(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value} bpm`;
}

export function formatVo2Max(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("en-GB", { maximumFractionDigits: 1 });
}

export function formatActivityType(value: string): string {
  return value.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

export function formatActivityTime(value: string): string {
  return londonTime.format(new Date(value));
}

export function formatActivitySummary(activity: FitnessActivity): string {
  const parts: string[] = [];
  if (activity.durationSeconds !== null)
    parts.push(`${Math.round(activity.durationSeconds / 60)} min`);
  if (activity.distanceMeters !== null && activity.distanceMeters >= 100) {
    parts.push(
      `${(activity.distanceMeters / 1000).toLocaleString("en-GB", { maximumFractionDigits: 2 })} km`,
    );
  }
  if (activity.caloriesKcal !== null) parts.push(`${activity.caloriesKcal} kcal`);
  if (activity.averageHeartRateBpm !== null) parts.push(`${activity.averageHeartRateBpm} bpm avg`);
  if (activity.totalSets !== null) parts.push(`${activity.totalSets} sets`);
  if (activity.totalReps !== null) parts.push(`${activity.totalReps} reps`);
  return parts.length ? parts.join(" · ") : formatActivityType(activity.type);
}

export function formatSyncTime(value: string | null | undefined): string | null {
  if (!value) return null;
  return `Updated ${londonTime.format(new Date(value))}`;
}

/** The first London day MyFitnessPal passed food to Garmin. See CONTEXT.md. */
export const MFP_LINK_DATE = "2026-09-28";

/**
 * Whether a day's Total calories is final: the day has ended in London, and
 * Garmin's last watch sync came after that end.
 *
 * "After the London midnight ending `day`" is the same as "the sync's London
 * day is later than `day`", which lets the day key do the BST/GMT offset work.
 * Day keys compare correctly as strings.
 */
export function isCompleteDay(
  day: string,
  today: string,
  sourceSyncedAt: string | null | undefined,
): boolean {
  if (!sourceSyncedAt || day >= today) return false;
  return londonDayKey(sourceSyncedAt) > day;
}

/** Calories eaten minus Total calories; null unless the day is complete. */
export function energyBalance(
  caloriesEaten: number | null | undefined,
  totalCalories: number | null | undefined,
  complete: boolean,
): number | null {
  if (!complete || caloriesEaten == null || totalCalories == null) return null;
  return caloriesEaten - totalCalories;
}

/** Why a day has no Calories eaten. */
export function missingCaloriesEatenNote(day: string, today: string): string {
  if (day < MFP_LINK_DATE) return "Before MFP was linked";
  if (day === today) return "Not logged yet";
  return "Nothing logged";
}

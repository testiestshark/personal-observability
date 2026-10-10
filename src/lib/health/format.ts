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

/** Under this distance an activity's distance and pace are noise, so neither is shown. */
export const MIN_SHOWN_DISTANCE_METERS = 100;

/** Kilometres, up to two decimals: "5 km", "5.02 km". "—" when unknown. */
export function formatKilometres(meters: number | null | undefined): string {
  if (meters === null || meters === undefined || !Number.isFinite(meters)) return "—";
  return `${(meters / 1000).toLocaleString("en-GB", { maximumFractionDigits: 2 })} km`;
}

export function formatActivitySummary(activity: FitnessActivity): string {
  const parts: string[] = [];
  if (activity.durationSeconds !== null)
    parts.push(`${Math.round(activity.durationSeconds / 60)} min`);
  if (activity.distanceMeters !== null && activity.distanceMeters >= MIN_SHOWN_DISTANCE_METERS) {
    parts.push(formatKilometres(activity.distanceMeters));
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
  if (!complete || isMissing(caloriesEaten) || isMissing(totalCalories)) return null;
  return caloriesEaten - totalCalories;
}

function isMissing(value: number | null | undefined): value is null | undefined {
  return value === null || value === undefined;
}

/** Why a day has no Calories eaten. */
export function missingCaloriesEatenNote(day: string, today: string): string {
  if (day < MFP_LINK_DATE) return "Before MFP was linked";
  if (day === today) return "Not logged yet";
  return "Nothing logged";
}

/** The Calories eaten tile's note: the goal, or why the value is missing. */
export function caloriesEatenNote(
  caloriesEaten: number | null | undefined,
  calorieGoal: number | null | undefined,
  day: string,
  today: string,
): string | undefined {
  if (isMissing(caloriesEaten)) return missingCaloriesEatenNote(day, today);
  if (isMissing(calorieGoal)) return undefined;
  return `of ${calorieGoal.toLocaleString("en-GB")}`;
}

/** How full the goal bar is, 0–1; null when there is no bar to draw. */
export function goalProgress(
  caloriesEaten: number | null | undefined,
  calorieGoal: number | null | undefined,
): number | null {
  if (isMissing(caloriesEaten) || isMissing(calorieGoal) || calorieGoal <= 0) return null;
  return Math.min(caloriesEaten / calorieGoal, 1);
}

/** Why there is no Energy balance to show, if there isn't one. */
export function energyBalanceNote(
  complete: boolean,
  caloriesEaten: number | null | undefined,
  totalCalories: number | null | undefined,
): string | undefined {
  if (!complete) return "Final once the day is synced";
  if (isMissing(caloriesEaten)) return "No calories eaten";
  if (isMissing(totalCalories)) return "No total calories";
  return undefined;
}

const syncTime = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Europe/London",
});

/** The Integrations page's per-source line: when a sync last ran, or that none has. */
export function formatSyncStatus(lastSyncedAt: string | null | undefined): string {
  return lastSyncedAt ? `Last synced ${syncTime.format(new Date(lastSyncedAt))}` : "Setup required";
}

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

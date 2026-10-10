import {
  formatActivityTime,
  formatActivityType,
  formatHeartRate,
  formatKilometres,
  MIN_SHOWN_DISTANCE_METERS,
} from "./format";
import type { GarminActivityDetail } from "./health.functions";
import { formatWorkoutDuration } from "./workout";
import { formatDayLabel } from "@/lib/weight/units";

const MISSING = "—";

/**
 * Whether the activity is read as pace (min/km) rather than speed (km/h).
 * Garmin type keys vary ("running", "trail_running", "casual_walking"), so this
 * matches on the word rather than listing keys: a type not seen yet still lands
 * on the right side.
 */
export function isFootActivity(type: string): boolean {
  return /running|walking|hiking/.test(type);
}

/** Distance and duration that can give a pace or speed, or null when they cannot. */
function rateInputs(
  durationSeconds: number | null,
  distanceMeters: number | null,
): { durationSeconds: number; distanceMeters: number } | null {
  if (durationSeconds === null || distanceMeters === null) return null;
  if (!Number.isFinite(durationSeconds) || !Number.isFinite(distanceMeters)) return null;
  if (durationSeconds <= 0 || distanceMeters < MIN_SHOWN_DISTANCE_METERS) return null;
  return { durationSeconds, distanceMeters };
}

/** Average pace as "5:30 /km": duration over distance. "—" when it cannot be worked out. */
export function formatAveragePace(
  durationSeconds: number | null,
  distanceMeters: number | null,
): string {
  const inputs = rateInputs(durationSeconds, distanceMeters);
  if (!inputs) return MISSING;
  // Round once, to whole seconds per km, then split: rounding minutes and
  // seconds separately would show 5:60.
  const secondsPerKm = Math.round(inputs.durationSeconds / (inputs.distanceMeters / 1_000));
  const minutes = Math.floor(secondsPerKm / 60);
  const seconds = String(secondsPerKm % 60).padStart(2, "0");
  return `${minutes}:${seconds} /km`;
}

/** Average speed as "15.0 km/h": distance over duration. "—" when it cannot be worked out. */
export function formatAverageSpeed(
  durationSeconds: number | null,
  distanceMeters: number | null,
): string {
  const inputs = rateInputs(durationSeconds, distanceMeters);
  if (!inputs) return MISSING;
  const kmPerHour = inputs.distanceMeters / 1_000 / (inputs.durationSeconds / 3_600);
  return `${kmPerHour.toFixed(1)} km/h`;
}

export type GarminHeadlineTile = { label: string; value: string };

export type GarminActivityHeader = {
  title: string;
  /** The stored London day, "YYYY-MM-DD": the back link's target. */
  localDay: string;
  dateLabel: string;
  startTime: string;
  /** Always four tiles, in this order; a value that is missing reads "—". */
  tiles: GarminHeadlineTile[];
};

/**
 * The Garmin detail page's header and headline grid, ready to render.
 *
 * Time is the stored `duration_seconds`, which is what the day-view card and
 * Garmin Connect show. Every tile is always present so the grid keeps its
 * shape; a missing value reads "—" and is never shown as 0.
 */
export function garminActivityHeader(activity: GarminActivityDetail): GarminActivityHeader {
  const isFoot = isFootActivity(activity.type);
  return {
    title: activity.name?.trim() || formatActivityType(activity.type),
    localDay: activity.localDay,
    dateLabel: formatDayLabel(activity.localDay),
    startTime: formatActivityTime(activity.startedAt),
    tiles: [
      { label: "Distance", value: formatKilometres(activity.distanceMeters) },
      { label: "Time", value: formatWorkoutDuration(activity.durationSeconds) },
      isFoot
        ? {
            label: "Avg pace",
            value: formatAveragePace(activity.durationSeconds, activity.distanceMeters),
          }
        : {
            label: "Avg speed",
            value: formatAverageSpeed(activity.durationSeconds, activity.distanceMeters),
          },
      { label: "Avg HR", value: formatHeartRate(activity.averageHeartRateBpm) },
    ],
  };
}

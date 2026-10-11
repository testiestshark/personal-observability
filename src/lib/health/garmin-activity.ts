import {
  formatActivityTime,
  formatActivityType,
  formatCalories,
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

/** Seconds per km as "5:30 /km". */
function formatPace(secondsPerKm: number): string {
  // Round once, to whole seconds per km, then split: rounding minutes and
  // seconds separately would show 5:60.
  const rounded = Math.round(secondsPerKm);
  const minutes = Math.floor(rounded / 60);
  const seconds = String(rounded % 60).padStart(2, "0");
  return `${minutes}:${seconds} /km`;
}

/** Average pace as "5:30 /km": duration over distance. "—" when it cannot be worked out. */
export function formatAveragePace(
  durationSeconds: number | null,
  distanceMeters: number | null,
): string {
  const inputs = rateInputs(durationSeconds, distanceMeters);
  if (!inputs) return MISSING;
  return formatPace(inputs.durationSeconds / (inputs.distanceMeters / 1_000));
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

export type GarminRow = { label: string; value: string };

/** A titled block of metrics below the headline grid; never empty. */
export type GarminSection = { title: string; rows: GarminRow[] };

/**
 * Moving and elapsed time are repeated lines of the headline Time, so they are
 * shown only when they differ from it by more than this: a few seconds of
 * stop-start noise is not information.
 */
export const SECONDARY_TIME_THRESHOLD_SECONDS = 5;

/** A metric Garmin reported. Null is "not reported" and a true 0 is kept. */
function isReported(value: number | null): value is number {
  return value !== null && Number.isFinite(value);
}

/** A row for a reported value, or nothing, so a section can drop what it lacks. */
function metricRow(
  label: string,
  value: number | null,
  format: (reported: number) => string,
): GarminRow[] {
  return isReported(value) ? [{ label, value: format(value) }] : [];
}

function wholeNumber(value: number): string {
  return Math.round(value).toLocaleString("en-GB");
}

function oneDecimal(value: number): string {
  return value.toFixed(1);
}

/** Metres per second as "18.0 km/h". */
function formatKmPerHour(metersPerSecond: number): string {
  return `${(metersPerSecond * 3.6).toFixed(1)} km/h`;
}

/** "28:42" under an hour, "1:02:05" from an hour up: seconds shown, so a small gap is visible. */
function formatClock(totalSeconds: number): string {
  const rounded = Math.round(totalSeconds);
  const hours = Math.floor(rounded / 3_600);
  const minutes = Math.floor((rounded % 3_600) / 60);
  const seconds = String(rounded % 60).padStart(2, "0");
  if (hours === 0) return `${minutes}:${seconds}`;
  return `${hours}:${String(minutes).padStart(2, "0")}:${seconds}`;
}

/**
 * Garmin's training-effect key as a sentence: "AEROBIC_BASE" is "Aerobic base".
 * A word with a digit stays in capitals ("VO2MAX"), which lower-casing would
 * turn into the unreadable "Vo2max". Null when there is nothing to show.
 */
export function humaniseTrainingEffectLabel(label: string | null): string | null {
  const words =
    label
      ?.trim()
      .split(/[_\s]+/)
      .filter(Boolean) ?? [];
  if (words.length === 0) return null;
  const text = words.map((word) => (/\d/.test(word) ? word : word.toLowerCase())).join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Moving or elapsed time, when it adds to the headline Time rather than repeating it. */
function secondaryTimeRow(
  label: string,
  seconds: number | null,
  headlineSeconds: number | null,
): GarminRow[] {
  if (!isReported(seconds)) return [];
  // With no headline Time there is nothing to repeat, so the line is the only
  // place the duration appears.
  const repeatsHeadline =
    isReported(headlineSeconds) &&
    Math.abs(seconds - headlineSeconds) <= SECONDARY_TIME_THRESHOLD_SECONDS;
  return repeatsHeadline ? [] : [{ label, value: formatClock(seconds) }];
}

/**
 * Pace and speed from the stored speeds. Foot activities get a best pace from
 * max speed (their average pace is already a headline tile); anything else gets
 * average and max speed in km/h. A speed of 0 gives no pace, so it is dropped.
 */
function paceAndSpeedRows(activity: GarminActivityDetail): GarminRow[] {
  if (isFootActivity(activity.type)) {
    const best = activity.maximumSpeedMps;
    return isReported(best) && best > 0
      ? [{ label: "Best pace", value: formatPace(1_000 / best) }]
      : [];
  }
  return [
    ...metricRow("Avg speed", activity.averageSpeedMps, formatKmPerHour),
    ...metricRow("Max speed", activity.maximumSpeedMps, formatKmPerHour),
  ];
}

/**
 * The secondary sections below the headline grid, in a fixed order. A section
 * with no reported metric is left out entirely rather than rendered empty, and
 * a null never becomes a 0. Power and training load are always null for the
 * owner's runs today; they appear on their own once the worker fills them.
 */
export function garminActivitySections(activity: GarminActivityDetail): GarminSection[] {
  const benefit = humaniseTrainingEffectLabel(activity.trainingEffectLabel);
  const sections: GarminSection[] = [
    {
      title: "Effort",
      rows: [
        ...metricRow("Max HR", activity.maximumHeartRateBpm, (bpm) => formatHeartRate(bpm)),
        ...metricRow("Calories", activity.caloriesKcal, (kcal) => formatCalories(kcal)),
      ],
    },
    {
      title: "Elevation",
      rows: [
        ...metricRow("Gain", activity.elevationGainMeters, (m) => `${wholeNumber(m)} m`),
        ...metricRow("Loss", activity.elevationLossMeters, (m) => `${wholeNumber(m)} m`),
      ],
    },
    { title: "Pace and speed", rows: paceAndSpeedRows(activity) },
    {
      title: "Running form",
      rows: [
        ...metricRow("Avg cadence", activity.averageCadenceSpm, (spm) => `${wholeNumber(spm)} spm`),
        ...metricRow("Max cadence", activity.maximumCadenceSpm, (spm) => `${wholeNumber(spm)} spm`),
      ],
    },
    {
      title: "Training effect",
      rows: [
        ...metricRow("Aerobic", activity.aerobicTrainingEffect, oneDecimal),
        ...metricRow("Anaerobic", activity.anaerobicTrainingEffect, oneDecimal),
        ...(benefit ? [{ label: "Primary benefit", value: benefit }] : []),
      ],
    },
    {
      title: "Time",
      rows: [
        ...secondaryTimeRow("Moving", activity.movingDurationSeconds, activity.durationSeconds),
        ...secondaryTimeRow("Elapsed", activity.elapsedDurationSeconds, activity.durationSeconds),
      ],
    },
    {
      title: "Power and training load",
      rows: [
        ...metricRow("Avg power", activity.averagePowerWatts, (w) => `${wholeNumber(w)} W`),
        ...metricRow("Max power", activity.maximumPowerWatts, (w) => `${wholeNumber(w)} W`),
        ...metricRow(
          "Normalized power",
          activity.normalizedPowerWatts,
          (w) => `${wholeNumber(w)} W`,
        ),
        ...metricRow("Training load", activity.trainingLoad, wholeNumber),
      ],
    },
  ];
  return sections.filter((section) => section.rows.length > 0);
}

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

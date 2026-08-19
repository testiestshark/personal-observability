// Turning a list of weigh-ins into something that shows direction.
//
// A run of raw weigh-ins is close to unreadable as a trend: bodyweight moves a
// kilogram or two a day on water, salt and what time you stood on the scale, which
// is noise an order of magnitude larger than the signal anyone is watching for. So
// the chart draws both — the raw readings, faintly, and a smoothed average that is
// the line you actually read.
//
// Pure functions, no I/O. Days are "YYYY-MM-DD" London keys throughout (see
// londonDayKey): a weigh-in belongs to the day it happened in London, never to a UTC
// date, and averaging over calendar days rather than over readings is what keeps a
// gap in the record from quietly compressing the window.

import { londonDayKey } from "./units";

/** One reading, on the London day it belongs to. */
export type DayPoint = {
  day: string;
  weightKg: number;
};

/** A day on the chart: the reading, plus the trailing average ending that day. */
export type TrendPoint = DayPoint & {
  /** Null until enough days are in range to average — see MIN_WINDOW_READINGS. */
  averageKg: number | null;
};

export type TrendSummary = {
  /** Most recent reading in range. */
  latestKg: number;
  /** Most recent trailing average, or null if too few readings to smooth. */
  latestAverageKg: number | null;
  /**
   * Change across the range, measured average-to-average so a single heavy or
   * light day at either end cannot invent a trend. Null when not smoothable.
   */
  changeKg: number | null;
  /** Readings in range. */
  count: number;
  /** Calendar days between the first and last reading in range, inclusive. */
  spanDays: number;
};

/** Days in the smoothing window. A week, so every weekday is represented once. */
export const WINDOW_DAYS = 7;

/**
 * Readings a window needs before it reports an average.
 *
 * One reading is not an average, and drawing it as though it were makes a lone
 * weigh-in after a gap look like a trend. Two is the smallest honest answer.
 */
export const MIN_WINDOW_READINGS = 2;

const MS_PER_DAY = 86_400_000;

/**
 * "2026-08-06" → a day number that can be subtracted.
 *
 * Via UTC deliberately. The keys are already London calendar dates, so all that is
 * wanted here is date arithmetic; going back through a timezone would reintroduce
 * DST, where a "day" is 23 or 25 hours and differences stop being whole numbers.
 */
function dayNumber(day: string): number {
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  return Date.UTC(Number(year), Number(month) - 1, Number(dayOfMonth)) / MS_PER_DAY;
}

/**
 * Collapse weigh-ins to one reading per London day, oldest first.
 *
 * Where a day has several, the earliest wins — usually the morning reading, and the
 * more consistent one to compare across days. This matches what the calendar shows
 * (see listMonthWeights), so the two never disagree about a given day.
 */
export function dailySeries(
  entries: readonly { recordedAt: string; weightKg: number }[],
): DayPoint[] {
  const byDay = new Map<string, { at: string; weightKg: number }>();

  for (const entry of entries) {
    const day = londonDayKey(entry.recordedAt);
    const existing = byDay.get(day);
    if (!existing || entry.recordedAt < existing.at) {
      byDay.set(day, { at: entry.recordedAt, weightKg: entry.weightKg });
    }
  }

  return [...byDay.entries()]
    .map(([day, { weightKg }]) => ({ day, weightKg }))
    .sort((a, b) => a.day.localeCompare(b.day));
}

/**
 * Attach a trailing average to each point.
 *
 * The window is `windowDays` **calendar** days ending on the point's own day, not
 * the previous N readings. With daily weigh-ins the two are identical; across a gap
 * they are not, and the calendar version is the one that keeps "7-day average"
 * meaning seven days. A week you did not weigh in simply has no average.
 */
export function withMovingAverage(
  points: readonly DayPoint[],
  windowDays: number = WINDOW_DAYS,
): TrendPoint[] {
  const numbers = points.map((point) => dayNumber(point.day));

  return points.map((point, index) => {
    const oldest = numbers[index]! - (windowDays - 1);

    let total = 0;
    let count = 0;
    // Walk back while the window still reaches. Points are sorted, so the first
    // day that falls outside ends it.
    for (let i = index; i >= 0; i--) {
      if (numbers[i]! < oldest) break;
      total += points[i]!.weightKg;
      count += 1;
    }

    return {
      ...point,
      averageKg: count >= MIN_WINDOW_READINGS ? total / count : null,
    };
  });
}

/**
 * Drop everything before the last `rangeDays` days.
 *
 * Counted back from the most recent reading rather than from today, so opening the
 * page after a fortnight away still shows the last stretch of data instead of an
 * empty chart.
 */
export function withinRange(points: readonly TrendPoint[], rangeDays: number | null): TrendPoint[] {
  if (rangeDays === null || points.length === 0) return [...points];

  const newest = dayNumber(points[points.length - 1]!.day);
  const oldest = newest - (rangeDays - 1);

  return points.filter((point) => dayNumber(point.day) >= oldest);
}

export function summarise(points: readonly TrendPoint[]): TrendSummary | null {
  if (points.length === 0) return null;

  const first = points[0]!;
  const last = points[points.length - 1]!;

  // Average-to-average, so neither end can be dragged by one unusual morning.
  //
  // Anchored on the first point that *has* an average, not on the first point:
  // the earliest day in any series has nothing behind it to average, so anchoring
  // positionally would report no change at all for a series that plainly moved.
  const firstAveraged = points.find((point) => point.averageKg !== null);
  const changeKg =
    firstAveraged && last.averageKg !== null && firstAveraged !== last
      ? last.averageKg - firstAveraged.averageKg!
      : null;

  return {
    latestKg: last.weightKg,
    latestAverageKg: last.averageKg,
    changeKg,
    count: points.length,
    spanDays: dayNumber(last.day) - dayNumber(first.day) + 1,
  };
}

/**
 * Everything the chart needs, from raw entries.
 *
 * The average is computed over the full history and only then filtered to the
 * range, so the first day shown already carries a settled average rather than
 * climbing out of nothing — the alternative makes every range change look like the
 * weight moved.
 */
export function buildTrend(
  entries: readonly { recordedAt: string; weightKg: number }[],
  options: { rangeDays?: number | null; windowDays?: number } = {},
): { points: TrendPoint[]; summary: TrendSummary | null } {
  const { rangeDays = null, windowDays = WINDOW_DAYS } = options;

  const points = withinRange(withMovingAverage(dailySeries(entries), windowDays), rangeDays);

  return { points, summary: summarise(points) };
}

// Weight unit conversion and formatting.
//
// Entries are stored canonically in kilograms (see the weight_entries migration)
// so history stays comparable across unit changes; these helpers convert at the
// edges. Pure functions — no I/O — so they are safe on both server and client.
//
// New entries are kilograms only — the scroll wheel is kg, and stone would need
// a different control shape (a 0–13 pounds column, not a decimal). lb and st are
// kept here because rows recorded before that change still render in the unit
// they were typed in, and the column's CHECK constraint still permits them.

export const WEIGHT_UNITS = ["kg", "lb", "st"] as const;
export type WeightUnit = (typeof WEIGHT_UNITS)[number];

// The single source in TypeScript for the sanity bounds on weight_entries.weight_kg,
// mirroring the CHECK constraint in the create_weight_entries migration so a bad value
// produces a readable message instead of a raw Postgres constraint violation.
//
// Both are EXCLUSIVE, matching the SQL `weight_kg > 0.5 and weight_kg < 1000`.
// They live here, in the pure leaf module, because weight.functions.ts already imports
// from it — so this adds no new dependency edge. units.test.ts reads the migration and
// fails if these drift from it: the numbers existing in two languages is the part that
// cannot be designed away, so it is pinned instead.
export const MIN_KG = 0.5;
export const MAX_KG = 1000;

/** Short suffix for display, e.g. "82.4 kg". */
export const UNIT_SUFFIX: Record<WeightUnit, string> = {
  kg: "kg",
  lb: "lb",
  st: "st",
};

const LB_PER_KG = 2.2046226218487757;
const LB_PER_STONE = 14;

/** Convert canonical kilograms back into `unit`. */
export function fromKilograms(kilograms: number, unit: WeightUnit): number {
  switch (unit) {
    case "kg":
      return kilograms;
    case "lb":
      return kilograms * LB_PER_KG;
    case "st":
      return (kilograms * LB_PER_KG) / LB_PER_STONE;
  }
}

/**
 * Render a stored weight in the unit it was entered in.
 *
 * One decimal place: finer than anyone weighs themselves, and it keeps a value
 * round-tripped through kilograms (e.g. 12.6 st) from displaying as 12.5999.
 */
export function formatWeight(kilograms: number, unit: WeightUnit): string {
  return `${fromKilograms(kilograms, unit).toFixed(1)} ${UNIT_SUFFIX[unit]}`;
}

// en-CA renders as YYYY-MM-DD, which sorts lexicographically and slices cleanly
// into a YYYY-MM month key.
const LONDON_DAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/London",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/**
 * The calendar day an instant falls on **in London**, as "YYYY-MM-DD".
 *
 * Timestamps are stored as UTC, so the UTC date is not the date the weigh-in
 * happened: during BST anything from 23:00 onwards is already the next day in
 * UTC, and a 00:30 weigh-in is stored under the previous one. Bucketing by this
 * key rather than by the raw timestamp — or by the viewing device's clock — is
 * what puts an entry in the right cell of the calendar.
 */
export function londonDayKey(isoTimestamp: string): string {
  return LONDON_DAY.format(new Date(isoTimestamp));
}

/** The current month in London, as "YYYY-MM". */
export function currentLondonMonth(): string {
  return londonDayKey(new Date().toISOString()).slice(0, 7);
}

/** Today in London, as "YYYY-MM-DD". */
export function currentLondonDay(): string {
  return londonDayKey(new Date().toISOString());
}

/**
 * The instant to store for a weigh-in on a given London day.
 *
 * A weigh-in is now a date with no time, but the column is a timestamptz, so one
 * has to be chosen. Noon UTC is deliberate: London runs at UTC+0 or UTC+1, so
 * noon UTC is 12:00 or 13:00 London — the same calendar day either way, and
 * nowhere near the 01:00/02:00 DST switchovers. Midnight would sit right on the
 * boundary and could land on the previous day.
 */
export function londonDayToInstant(day: string): string {
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  return new Date(Date.UTC(Number(year), Number(month) - 1, Number(dayOfMonth), 12)).toISOString();
}

/** "2026-08-06" → "Thu 06 Aug 2026". */
const LONDON_DATE_LABEL = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  weekday: "short",
  day: "2-digit",
  month: "short",
  year: "numeric",
});

export function formatDayLabel(day: string): string {
  return LONDON_DATE_LABEL.format(new Date(londonDayToInstant(day)));
}

/**
 * Format a stored weigh-in as the day it belongs to, e.g. "Thu, 06 Aug 2026".
 *
 * A weigh-in is a day, not an instant. Entries are written at noon UTC (see
 * londonDayToInstant), so displaying a time would show an artefact of that
 * choice rather than anything the user recorded — every row would read 12:00 or
 * 13:00 depending on the season. Going through londonDayKey also keeps this
 * agreeing with the calendar, which labels the same entry from the same helper.
 */
export function formatEntryDay(isoTimestamp: string): string {
  return formatDayLabel(londonDayKey(isoTimestamp));
}

/**
 * Split a "YYYY-MM-DD" key into numbers.
 *
 * Destructuring `split("-")` directly gives `string | undefined` under
 * noUncheckedIndexedAccess, so every caller would otherwise repeat the same
 * narrowing. Callers pass keys already validated against DAY_PATTERN.
 */
export function parseDayKey(day: string): {
  year: number;
  monthNumber: number;
  dayOfMonth: number;
} {
  const [year, monthNumber, dayOfMonth] = day.split("-");
  return { year: Number(year), monthNumber: Number(monthNumber), dayOfMonth: Number(dayOfMonth) };
}

/**
 * Split a "YYYY-MM" key into numbers.
 *
 * Destructuring `split("-")` directly gives `string | undefined` under
 * noUncheckedIndexedAccess, so every caller would otherwise repeat the same
 * narrowing. Callers pass keys already validated against MONTH_PATTERN.
 */
export function parseMonthKey(month: string): { year: number; monthNumber: number } {
  const [year, monthNumber] = month.split("-");
  return { year: Number(year), monthNumber: Number(monthNumber) };
}

const MONTH_LABEL = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  month: "long",
  year: "numeric",
});

/** "2026-08" → "August 2026". */
export function formatMonthLabel(month: string): string {
  const { year, monthNumber } = parseMonthKey(month);
  // Mid-month, so the label cannot be dragged into a neighbouring month by an
  // offset at the boundary.
  return MONTH_LABEL.format(new Date(Date.UTC(year, monthNumber - 1, 15)));
}

/** Step a "YYYY-MM" month key by whole months. */
export function shiftMonth(month: string, delta: number): string {
  const { year, monthNumber } = parseMonthKey(month);
  const shifted = new Date(Date.UTC(year, monthNumber - 1 + delta, 1));
  return `${shifted.getUTCFullYear()}-${String(shifted.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** Step a "YYYY-MM-DD" day key by whole days. */
export function shiftDay(day: string, delta: number): string {
  const { year, monthNumber, dayOfMonth } = parseDayKey(day);
  const shifted = new Date(Date.UTC(year, monthNumber - 1, dayOfMonth + delta));
  const y = shifted.getUTCFullYear();
  const m = String(shifted.getUTCMonth() + 1).padStart(2, "0");
  const d = String(shifted.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

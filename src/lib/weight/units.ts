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

/** Short suffix for display, e.g. "82.4 kg". */
export const UNIT_SUFFIX: Record<WeightUnit, string> = {
  kg: "kg",
  lb: "lb",
  st: "st",
};

const LB_PER_KG = 2.2046226218487757;
const LB_PER_STONE = 14;

/** Convert a value the user typed in `unit` into canonical kilograms. */
export function toKilograms(value: number, unit: WeightUnit): number {
  switch (unit) {
    case "kg":
      return value;
    case "lb":
      return value / LB_PER_KG;
    case "st":
      return (value * LB_PER_STONE) / LB_PER_KG;
  }
}

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

const UK_DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/London",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * Format an instant as UK date and time.
 *
 * Timestamps are stored as UTC; using an explicit Europe/London time zone means
 * GMT/BST is applied correctly for the date in question rather than assuming the
 * viewing device is set to UK time.
 */
export function formatUkDateTime(isoTimestamp: string): string {
  return UK_DATE_TIME.format(new Date(isoTimestamp));
}

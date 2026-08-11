// Parsing for weigh-in CSV exports, so historic entries can be imported rather
// than retyped a day at a time.
//
// Pure functions — no I/O — so the import dialog can parse and summarise a file
// in the browser before anything is sent to the server. That is what lets the
// preview be honest about what will be written: the same code produces the
// summary and the rows.
//
// Expected shape is a date in the left column and a weight in kilograms in the
// right, which is what the weight-diary apps export. Dates are dd/mm/yyyy with an
// optional time.

import { MAX_KG, MIN_KG } from "./units";

// numeric(6, 3) — anything finer is rounded by Postgres on the way in, so it is
// rounded here instead and reported, rather than storing something that differs
// from what the preview showed.
const DECIMAL_PLACES = 3;

/** A row that parsed cleanly. `time` is "hh:mm", or null when the file had none. */
export type ParsedRow = {
  lineNumber: number;
  day: string;
  time: string | null;
  weightKg: number;
  rounded: boolean;
};

export type SkippedRow = { lineNumber: number; raw: string; reason: string };

export type ParsedCsv = {
  /** One row per day, earliest weigh-in kept, oldest first. */
  days: ParsedRow[];
  skipped: SkippedRow[];
  /** Rows dropped because another row covered the same day. */
  duplicates: ParsedRow[];
  roundedCount: number;
  /**
   * Whether any row has a day above 12.
   *
   * When nothing does, the file reads identically as mm/dd/yyyy and importing it
   * would silently swap day and month. The caller warns rather than guessing.
   */
  provesDayFirst: boolean;
};

/** Split one CSV line, honouring quoted fields and doubled quotes inside them. */
function splitCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];

    if (inQuotes) {
      if (char !== '"') {
        current += char;
      } else if (line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = false;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      fields.push(current);
      current = "";
    } else {
      current += char;
    }
  }

  fields.push(current);
  return fields.map((field) => field.trim());
}

// dd/mm/yyyy, with an optional trailing time. Separators vary between exports, so
// both / and - are accepted; the time may be space- or T-separated.
const DATE_PATTERN = /^(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:[ T](\d{1,2}):(\d{2}))?/;

/**
 * Parse a dd/mm/yyyy cell into a London day key and an optional time.
 *
 * The date is validated by round-tripping through Date.UTC: a value that comes
 * back different (31/04, or an mm/dd date like 03/25) is rejected rather than
 * being rolled over into the next month the way the Date constructor would.
 */
function parseDayCell(cell: string): { day: string; time: string | null } | null {
  const match = cell.match(DATE_PATTERN);
  if (!match) return null;

  const [, dayPart, monthPart, yearPart, hourPart, minutePart] = match;
  const dayOfMonth = Number(dayPart);
  const month = Number(monthPart);
  const year = Number(yearPart);

  const asDate = new Date(Date.UTC(year, month - 1, dayOfMonth));
  if (
    asDate.getUTCFullYear() !== year ||
    asDate.getUTCMonth() !== month - 1 ||
    asDate.getUTCDate() !== dayOfMonth
  ) {
    return null;
  }

  const day = `${yearPart}-${String(month).padStart(2, "0")}-${String(dayOfMonth).padStart(2, "0")}`;
  const time = hourPart && minutePart ? `${hourPart.padStart(2, "0")}:${minutePart}` : null;

  return { day, time };
}

/** Parse a weight cell, tolerating a trailing unit ("82.4 kg"). */
function parseWeightCell(cell: string): number | null {
  const cleaned = cell.replace(/[^\d.]/g, "");
  if (!cleaned) return null;

  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

/**
 * Collapse rows to one per day, keeping the earliest weigh-in.
 *
 * Matches listMonthWeights, which shows a day's earliest entry — usually the
 * morning reading, and the more consistent one to compare across days. A row with
 * no time loses to one that has a time, since a bare date says nothing about when.
 */
function oneRowPerDay(rows: ParsedRow[]): { kept: ParsedRow[]; duplicates: ParsedRow[] } {
  const byDay = new Map<string, ParsedRow>();
  const duplicates: ParsedRow[] = [];

  for (const row of rows) {
    const existing = byDay.get(row.day);

    if (!existing) {
      byDay.set(row.day, row);
      continue;
    }

    const incomingIsEarlier =
      row.time !== null && (existing.time === null || row.time < existing.time);

    if (incomingIsEarlier) {
      byDay.set(row.day, row);
      duplicates.push(existing);
    } else {
      duplicates.push(row);
    }
  }

  const kept = [...byDay.values()].sort((left, right) => left.day.localeCompare(right.day));
  return { kept, duplicates };
}

/** Parse a weigh-in CSV into one row per day, plus everything that was dropped. */
export function parseWeightCsv(text: string): ParsedCsv {
  const rows: ParsedRow[] = [];
  const skipped: SkippedRow[] = [];

  // Strip a UTF-8 BOM, which Excel writes and which would otherwise break the
  // date match on the very first cell.
  const withoutBom = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;

  withoutBom.split(/\r?\n/).forEach((line, index) => {
    const lineNumber = index + 1;
    if (!line.trim()) return;

    const fields = splitCsvLine(line);
    const parsedDay = parseDayCell(fields[0] ?? "");

    if (!parsedDay) {
      // An unreadable first line is the header row, not a problem worth
      // reporting; anywhere else it is a row that needs looking at.
      if (lineNumber > 1) {
        skipped.push({ lineNumber, raw: line, reason: "could not read the date" });
      }
      return;
    }

    const weight = parseWeightCell(fields[1] ?? "");
    if (weight === null) {
      skipped.push({ lineNumber, raw: line, reason: "could not read the weight" });
      return;
    }

    const weightKg = Number(weight.toFixed(DECIMAL_PLACES));

    if (weightKg <= MIN_KG || weightKg >= MAX_KG) {
      skipped.push({
        lineNumber,
        raw: line,
        reason: `${weightKg} kg is outside the allowed range`,
      });
      return;
    }

    rows.push({
      lineNumber,
      day: parsedDay.day,
      time: parsedDay.time,
      weightKg,
      rounded: weightKg !== weight,
    });
  });

  const { kept, duplicates } = oneRowPerDay(rows);

  return {
    days: kept,
    skipped,
    duplicates,
    roundedCount: kept.filter((row) => row.rounded).length,
    provesDayFirst: rows.some((row) => Number(row.day.slice(8, 10)) > 12),
  };
}

/**
 * One-off backfill: import historic weigh-ins from a CSV into HOSTED Supabase.
 *
 *   bun scripts/import-weights.ts <file.csv>            # dry run — writes nothing
 *   bun scripts/import-weights.ts <file.csv> --commit   # actually inserts
 *
 * Credentials come from the environment, so the password never reaches shell
 * history or a file:
 *
 *   $env:WEIGHT_IMPORT_EMAIL = "you@example.com"
 *   $env:WEIGHT_IMPORT_PASSWORD = "..."
 *
 * CSV shape: date in the left column, weight in kilograms in the right. Dates are
 * dd/mm/yyyy, optionally followed by a time (`dd/mm/yyyy hh:mm`). A header row is
 * detected and skipped.
 *
 * This signs in as a real user and inserts under Row Level Security, so rows are
 * owned by `auth.uid()` exactly as if they had been entered in the app. It does
 * NOT use the service role key — see CLAUDE.md § Roles and ownership.
 */
import { readFile } from "node:fs/promises";

import { createClient } from "@supabase/supabase-js";

import { londonDayKey, londonDayToInstant } from "../src/lib/weight/units";

// Mirrors the CHECK constraint in the weight_entries migration.
const MIN_KG = 0.5;
const MAX_KG = 1000;

// numeric(6, 3) — anything finer is silently rounded by Postgres, so round here
// instead and report it, rather than having stored values differ from the file.
const DECIMAL_PLACES = 3;

const DAY_MS = 24 * 60 * 60 * 1000;
const CHUNK_SIZE = 500;

/** A row that parsed cleanly. `time` is "hh:mm", or null when the file had none. */
type ParsedRow = {
  lineNumber: number;
  day: string;
  time: string | null;
  weightKg: number;
  rounded: boolean;
};

type SkippedRow = { lineNumber: number; raw: string; reason: string };

/**
 * Hosted connection details, read from the committed .env.production.
 *
 * Deliberately not from the environment or .env.local: .env.local points at the
 * local Docker stack, so an import meant for hosted would silently land in a
 * throwaway database. Reading the hosted file directly makes the target explicit.
 */
async function readHostedConfig(): Promise<{ url: string; key: string }> {
  const text = await readFile(".env.production", "utf8");

  const read = (name: string): string => {
    const match = text.match(new RegExp(`^${name}=(.*)$`, "m"));
    const value = match?.[1]?.trim().replace(/^["']|["']$/g, "");
    if (!value) throw new Error(`${name} is missing from .env.production.`);
    return value;
  };

  const url = read("VITE_SUPABASE_URL");

  // A local URL here would mean .env.production has been pointed somewhere else;
  // fail loudly rather than writing the backfill into the wrong database.
  if (/localhost|127\.0\.0\.1/.test(url)) {
    throw new Error(`Refusing to run: ${url} is a local Supabase URL, not hosted.`);
  }

  return { url, key: read("VITE_SUPABASE_PUBLISHABLE_KEY") };
}

/**
 * supabase-js sends the API key as `Authorization: Bearer <key>`, which the new
 * opaque `sb_publishable_` keys are rejected for — they belong in `apikey`. Same
 * shim as src/lib/auth/supabase-request.server.ts; without it sign-in 401s.
 */
function createSupabaseFetch(supabaseKey: string): typeof fetch {
  return (input, init) => {
    const headers = new Headers(input instanceof Request ? input.headers : undefined);

    if (init?.headers) {
      new Headers(init.headers).forEach((value, key) => headers.set(key, value));
    }

    if (
      supabaseKey.startsWith("sb_publishable_") &&
      headers.get("Authorization") === `Bearer ${supabaseKey}`
    ) {
      headers.delete("Authorization");
    }

    headers.set("apikey", supabaseKey);
    return fetch(input, { ...init, headers });
  };
}

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
 * The month is validated by round-tripping through Date.UTC: a value that comes
 * back different (31/04, or an mm/dd date like 03/25) never reaches the database.
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

/** Parse a weight cell, tolerating a trailing unit ("82.4 kg") and thousands commas. */
function parseWeightCell(cell: string): number | null {
  const cleaned = cell.replace(/[^\d.]/g, "");
  if (!cleaned) return null;

  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

function parseCsv(text: string): { rows: ParsedRow[]; skipped: SkippedRow[] } {
  const rows: ParsedRow[] = [];
  const skipped: SkippedRow[] = [];

  // Strip a UTF-8 BOM, which Excel writes and which would otherwise break the
  // date match on the very first cell.
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/);

  lines.forEach((line, index) => {
    const lineNumber = index + 1;
    if (!line.trim()) return;

    const fields = splitCsvLine(line);
    const dayCell = fields[0] ?? "";
    const weightCell = fields[1] ?? "";

    const parsedDay = parseDayCell(dayCell);
    if (!parsedDay) {
      // An unparseable first line is the header row, not a problem worth
      // reporting; anywhere else it is a row that needs looking at.
      if (lineNumber > 1) {
        skipped.push({ lineNumber, raw: line, reason: "could not read the date" });
      }
      return;
    }

    const weight = parseWeightCell(weightCell);
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

  return { rows, skipped };
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

async function main() {
  const args = process.argv.slice(2);
  const commit = args.includes("--commit");
  const path = args.find((arg) => !arg.startsWith("--"));

  if (!path) {
    console.error("Usage: bun scripts/import-weights.ts <file.csv> [--commit]");
    process.exit(1);
  }

  const { rows, skipped } = parseCsv(await readFile(path, "utf8"));

  if (rows.length === 0) {
    console.error(`No usable rows found in ${path}.`);
    process.exit(1);
  }

  const { kept, duplicates } = oneRowPerDay(rows);
  const roundedCount = kept.filter((row) => row.rounded).length;

  // A file that never has a first component above 12 is indistinguishable from
  // mm/dd/yyyy, and would import with the day and month swapped. Say so rather
  // than guessing.
  const provesDayFirst = rows.some((row) => Number(row.day.slice(8, 10)) > 12);

  const firstDay = kept[0]!.day;
  const lastDay = kept[kept.length - 1]!.day;

  // Everything above is derived from the file alone, so it is reported before any
  // network call — checking how the CSV parsed should not need credentials.
  console.log(`\nSource              ${path}`);
  console.log(`Rows read           ${rows.length}`);
  console.log(`Unreadable rows     ${skipped.length}`);
  console.log(`Same-day duplicates ${duplicates.length} (earliest weigh-in kept)`);
  console.log(`Rounded to 3dp      ${roundedCount}`);
  console.log(`Distinct days       ${kept.length}`);
  console.log(`Date range          ${firstDay} to ${lastDay}`);

  if (!provesDayFirst) {
    console.log(
      "\nNote: no row has a day above 12, so this file reads identically as" +
        "\nmm/dd/yyyy. Check a known date below before committing.",
    );
  }

  if (skipped.length > 0) {
    console.log("\nSkipped:");
    for (const row of skipped.slice(0, 20)) {
      console.log(`  line ${row.lineNumber}: ${row.reason} — ${row.raw}`);
    }
    if (skipped.length > 20) console.log(`  …and ${skipped.length - 20} more`);
  }

  // Head and tail only once there is enough to be worth abbreviating, and showing
  // the exact stored value rather than a rounded one — the point of the preview is
  // to confirm what will land in the database.
  const preview = kept.length > 10 ? [...kept.slice(0, 5), null, ...kept.slice(-5)] : [...kept];

  console.log(kept.length > 10 ? "\nFirst and last few days parsed:" : "\nDays parsed:");
  for (const row of preview) {
    if (row === null) {
      console.log(`  … ${kept.length - 10} more`);
      continue;
    }
    console.log(`  ${row.day}  ${row.weightKg} kg  (line ${row.lineNumber})`);
  }

  const email = process.env["WEIGHT_IMPORT_EMAIL"];
  const password = process.env["WEIGHT_IMPORT_PASSWORD"];

  if (!email || !password) {
    console.error(
      "\nSet WEIGHT_IMPORT_EMAIL and WEIGHT_IMPORT_PASSWORD to check these" +
        "\nagainst the database.\n",
    );
    process.exit(1);
  }

  const { url, key } = await readHostedConfig();
  const supabase = createClient(url, key, {
    auth: { persistSession: false },
    global: { fetch: createSupabaseFetch(key) },
  });

  const { data: signIn, error: signInError } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (signInError || !signIn.user) {
    console.error(`Could not sign in: ${signInError?.message ?? "no user returned"}`);
    process.exit(1);
  }

  const userId = signIn.user.id;

  // Widened a day at each end for the same reason listMonthWeights widens its
  // range: a London day and a UTC day do not line up, so an exact-boundary query
  // would miss entries. londonDayKey below decides the day each row belongs to.
  const from = new Date(new Date(londonDayToInstant(firstDay)).getTime() - DAY_MS).toISOString();
  const to = new Date(new Date(londonDayToInstant(lastDay)).getTime() + DAY_MS).toISOString();

  const { data: existingRows, error: existingError } = await supabase
    .from("weight_entries")
    .select("recorded_at")
    .eq("user_id", userId)
    .gte("recorded_at", from)
    .lt("recorded_at", to);

  if (existingError) {
    console.error(`Could not read existing entries: ${existingError.message}`);
    process.exit(1);
  }

  const existingDays = new Set((existingRows ?? []).map((row) => londonDayKey(row.recorded_at)));
  const toInsert = kept.filter((row) => !existingDays.has(row.day));
  const alreadyPresent = kept.length - toInsert.length;

  console.log(`\nTarget              ${url}`);
  console.log(`Signed in           ${email}`);
  console.log(`Already in database ${alreadyPresent}`);
  console.log(`To insert           ${toInsert.length}`);

  if (!commit) {
    console.log("\nDry run — nothing written. Re-run with --commit to insert.\n");
    return;
  }

  if (toInsert.length === 0) {
    console.log("\nNothing to insert.\n");
    return;
  }

  let inserted = 0;

  for (let index = 0; index < toInsert.length; index += CHUNK_SIZE) {
    const chunk = toInsert.slice(index, index + CHUNK_SIZE);

    const { error } = await supabase.from("weight_entries").insert(
      chunk.map((row) => ({
        user_id: userId,
        // Noon UTC for the day, the same instant the app writes — see
        // londonDayToInstant for why midnight would be wrong.
        recorded_at: londonDayToInstant(row.day),
        weight_kg: row.weightKg,
        entered_unit: "kg" as const,
      })),
    );

    if (error) {
      console.error(`\nFailed after ${inserted} rows: ${error.message}`);
      process.exit(1);
    }

    inserted += chunk.length;
    console.log(`  inserted ${inserted}/${toInsert.length}`);
  }

  console.log(`\nDone — ${inserted} entries imported.\n`);
}

await main();

// Server functions for weight tracking. Ships RPC stubs to the client bundle, so
// the server-only Supabase client is imported dynamically inside each handler.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

import {
  londonDayKey,
  londonDayToInstant,
  MAX_KG,
  MIN_KG,
  parseMonthKey,
  type WeightUnit,
} from "./units";

const DAY_MS = 24 * 60 * 60 * 1000;

export type WeightEntry = {
  id: string;
  recordedAt: string;
  weightKg: number;
  unit: WeightUnit;
};

// How many weigh-ins the History list will show. A cap exists only to bound the
// size of the server-rendered payload — it is not a page size, and there is no
// "load more", so anything past it is simply invisible in History (the calendar
// still shows every month).
//
// 10,000 is roughly 27 years of daily weigh-ins, so it is not a limit this app
// will meet. Deliberately settled rather than solved: no pagination is planned.
const HISTORY_LIMIT = 10000;

const newEntrySchema = z.object({
  weight: z.number().finite().positive("Enter a weight greater than zero."),
  day: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Expected a YYYY-MM-DD day."),
});

export type NewWeightEntry = z.infer<typeof newEntrySchema>;

async function requireUser() {
  const { createSupabaseRequestClient } = await import("@/lib/auth/supabase-request.server");
  const supabase = createSupabaseRequestClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) throw new Error("Not signed in.");
  return { supabase, userId: data.user.id };
}

type RequestClient = Awaited<ReturnType<typeof requireUser>>["supabase"];

/**
 * The entry recorded on a given London day, if there is one.
 *
 * Queries a day either side and then filters by londonDayKey, for the same
 * reason listMonthWeights widens its range: the London day and the UTC day do
 * not line up, so an exact-boundary query would miss entries.
 */
async function findEntryForDay(
  supabase: RequestClient,
  userId: string,
  day: string,
): Promise<{ id: string; weightKg: number } | null> {
  const instant = new Date(londonDayToInstant(day)).getTime();

  const { data, error } = await supabase
    .from("weight_entries")
    .select("id, recorded_at, weight_kg")
    .eq("user_id", userId)
    .gte("recorded_at", new Date(instant - DAY_MS).toISOString())
    .lt("recorded_at", new Date(instant + DAY_MS).toISOString())
    .order("recorded_at", { ascending: true });

  if (error) throw new Error(error.message);

  const row = (data ?? []).find((candidate) => londonDayKey(candidate.recorded_at) === day);
  return row ? { id: row.id, weightKg: Number(row.weight_kg) } : null;
}

/** This user's weigh-ins, newest first. */
export const listWeightEntries = createServerFn({ method: "GET" }).handler(
  async (): Promise<WeightEntry[]> => {
    const { supabase, userId } = await requireUser();

    const { data, error } = await supabase
      .from("weight_entries")
      .select("id, recorded_at, weight_kg, entered_unit")
      .eq("user_id", userId)
      .order("recorded_at", { ascending: false })
      .limit(HISTORY_LIMIT);

    if (error) throw new Error(error.message);

    return (data ?? []).map((row) => ({
      id: row.id,
      recordedAt: row.recorded_at,
      // numeric comes back as a string from postgrest to preserve precision.
      weightKg: Number(row.weight_kg),
      unit: row.entered_unit as WeightUnit,
    }));
  },
);

/** One calendar day's weight, keyed by London date ("2026-08-06"). */
export type DayWeight = {
  id: string;
  day: string;
  weightKg: number;
};

const monthSchema = z.object({
  month: z.string().regex(/^\d{4}-(0[1-9]|1[0-2])$/, "Expected a YYYY-MM month."),
});

/**
 * One weight per day for a given month, for the calendar.
 *
 * Where a day has several weigh-ins the earliest wins — that is usually the
 * morning reading, which is the more consistent measurement to compare across
 * days.
 */
export const listMonthWeights = createServerFn({ method: "GET" })
  .validator((data: { month: string }) => monthSchema.parse(data))
  .handler(async ({ data }): Promise<DayWeight[]> => {
    const { supabase, userId } = await requireUser();

    const { year, monthNumber } = parseMonthKey(data.month);

    // Widened by a day at each end: a weigh-in belonging to this month in London
    // can sit in the neighbouring month in UTC, and would be missed by a query
    // cut exactly on the UTC month boundary. londonDayKey below decides which day
    // each row actually belongs to, and anything outside the month is dropped.
    const from = new Date(Date.UTC(year, monthNumber - 1, 1) - DAY_MS).toISOString();
    const to = new Date(Date.UTC(year, monthNumber, 1) + DAY_MS).toISOString();

    const { data: rows, error } = await supabase
      .from("weight_entries")
      .select("id, recorded_at, weight_kg")
      .eq("user_id", userId)
      .gte("recorded_at", from)
      .lt("recorded_at", to)
      // Ascending, so the first row seen for a day is that day's earliest. New
      // entries are one-per-day, but rows predating that rule may not be.
      .order("recorded_at", { ascending: true });

    if (error) throw new Error(error.message);

    const byDay = new Map<string, DayWeight>();
    for (const row of rows ?? []) {
      const day = londonDayKey(row.recorded_at);
      if (!day.startsWith(data.month)) continue;
      if (!byDay.has(day)) {
        byDay.set(day, { id: row.id, day, weightKg: Number(row.weight_kg) });
      }
    }

    return [...byDay.values()];
  });

export const addWeightEntry = createServerFn({ method: "POST" })
  .validator((data: NewWeightEntry) => newEntrySchema.parse(data))
  .handler(async ({ data }): Promise<{ error: string | null }> => {
    const { supabase, userId } = await requireUser();

    // Round to the 3 decimal places the column stores, so what is written back
    // matches what a later read returns.
    const weightKg = Number(data.weight.toFixed(3));

    if (weightKg <= MIN_KG || weightKg >= MAX_KG) {
      return { error: "That weight looks out of range. Check the value." };
    }

    // One weigh-in per day. Checked here rather than only in the form so the
    // rule holds however the server function is called.
    //
    // This is an application-level guard, not a database constraint: enforcing
    // it in Postgres would need a unique index on the London date, and
    // `recorded_at AT TIME ZONE 'Europe/London'` is STABLE rather than
    // IMMUTABLE, so it cannot be indexed. A real constraint would mean a
    // separate date column. Two submissions racing each other could still both
    // land — vanishingly unlikely for one person tapping one button.
    const existing = await findEntryForDay(supabase, userId, data.day);
    if (existing) {
      return { error: `You already recorded ${existing.weightKg.toFixed(1)} kg on that day.` };
    }

    const { error } = await supabase.from("weight_entries").insert({
      user_id: userId,
      recorded_at: londonDayToInstant(data.day),
      weight_kg: weightKg,
      entered_unit: "kg",
    });

    return { error: error ? error.message : null };
  });

export const deleteWeightEntry = createServerFn({ method: "POST" })
  .validator((data: { id: string }) => z.object({ id: z.string().uuid() }).parse(data))
  .handler(async ({ data }): Promise<{ error: string | null }> => {
    const { supabase, userId } = await requireUser();

    // user_id is redundant with RLS, but scoping the delete explicitly means a
    // policy regression cannot turn this into a cross-user delete.
    const { error } = await supabase
      .from("weight_entries")
      .delete()
      .eq("id", data.id)
      .eq("user_id", userId);

    return { error: error ? error.message : null };
  });

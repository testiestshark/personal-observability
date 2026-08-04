// Server functions for weight tracking. Ships RPC stubs to the client bundle, so
// the server-only Supabase client is imported dynamically inside each handler.
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

import { WEIGHT_UNITS, toKilograms, type WeightUnit } from "./units";

export type WeightEntry = {
  id: string;
  recordedAt: string;
  weightKg: number;
  unit: WeightUnit;
};

// Mirrors the CHECK constraints in the weight_entries migration, so a bad value
// produces a readable message instead of a raw Postgres constraint violation.
const MIN_KG = 0.5;
const MAX_KG = 1000;

const newEntrySchema = z.object({
  weight: z.number().finite().positive("Enter a weight greater than zero."),
  unit: z.enum(WEIGHT_UNITS),
  recordedAt: z.string().datetime({ offset: true }),
});

export type NewWeightEntry = z.infer<typeof newEntrySchema>;

async function requireUser() {
  const { createSupabaseRequestClient } = await import("@/lib/auth/supabase-request.server");
  const supabase = createSupabaseRequestClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) throw new Error("Not signed in.");
  return { supabase, userId: data.user.id };
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
      .limit(200);

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

export const addWeightEntry = createServerFn({ method: "POST" })
  .validator((data: NewWeightEntry) => newEntrySchema.parse(data))
  .handler(async ({ data }): Promise<{ error: string | null }> => {
    const { supabase, userId } = await requireUser();

    // Round to the 3 decimal places the column stores, so what is written back
    // matches what a later read returns.
    const weightKg = Number(toKilograms(data.weight, data.unit).toFixed(3));

    if (weightKg <= MIN_KG || weightKg >= MAX_KG) {
      return { error: "That weight looks out of range. Check the value and unit." };
    }

    const { error } = await supabase.from("weight_entries").insert({
      user_id: userId,
      recorded_at: data.recordedAt,
      weight_kg: weightKg,
      entered_unit: data.unit,
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
